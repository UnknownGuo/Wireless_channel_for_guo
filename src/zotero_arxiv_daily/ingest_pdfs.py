import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

import dotenv
import hydra
import pymupdf
from loguru import logger
from omegaconf import DictConfig


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_existing_ids(db_path: Path) -> set[str]:
    if not db_path.exists():
        return set()
    ids = set()
    with db_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if record.get("id"):
                    ids.add(record["id"])
            except json.JSONDecodeError:
                continue
    return ids


def extract_text_from_pdf(path: Path, max_pages: int = 3) -> str:
    parts: list[str] = []
    with pymupdf.open(path) as doc:
        for page in doc[: min(max_pages, len(doc))]:
            parts.append(page.get_text("text"))
    return "\n".join(parts)


def _normalize_line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _is_bad_title_candidate(line: str) -> bool:
    s = _normalize_line(line)
    if not s:
        return True
    lower = s.lower()
    bad_patterns = (
        "abstract",
        "keywords",
        "index terms",
        "received ",
        "revised ",
        "accepted ",
        "date of publication",
        "copyright",
        "doi",
        "vol.",
        "volume",
        "issue",
        "ieee",
        "springer",
        "elsevier",
        "arxiv",
        "this article",
        "all rights reserved",
        "proof",
    )
    if lower.startswith(bad_patterns) or any(p in lower for p in bad_patterns[4:]):
        return True
    if s.lower().endswith(".pdf") or "_proof" in lower or " proof" in lower:
        return True
    if re.search(r"[_.-]{2,}", s):
        return True
    if re.search(r"\b\d{4}\b", s) and len(s) < 80:
        return True
    if len(s) < 12:
        return True
    return False


def _title_score(line: str) -> float:
    s = _normalize_line(line)
    if _is_bad_title_candidate(s):
        return float("-inf")
    words = s.split()
    score = 0.0
    score += min(len(s), 180) / 4.0
    if 4 <= len(words) <= 18:
        score += 25.0
    if len(words) <= 3:
        score -= 15.0
    alpha_ratio = sum(ch.isalpha() for ch in s) / max(len(s), 1)
    score += alpha_ratio * 20.0
    if s[:1].isupper():
        score += 8.0
    if s.endswith((".", ":", ";")):
        score -= 10.0
    if re.search(r"\b(?:and|of|for|to|in|with|on)\b", s.lower()):
        score += 4.0
    if s.count(",") > 2:
        score -= 6.0
    if s.count("(") + s.count(")") > 2:
        score -= 4.0
    return score


def extract_title(text: str, path: Path) -> str:
    try:
        with pymupdf.open(path) as doc:
            meta_title = _normalize_line((doc.metadata or {}).get("title") or "")
            if meta_title and not _is_bad_title_candidate(meta_title):
                return meta_title
    except Exception:
        pass

    lines = text.splitlines()
    preamble: list[str] = []
    for line in lines[:40]:
        if re.match(r"(?i)^\s*(abstract|keywords|index terms)\b", _normalize_line(line)):
            break
        preamble.append(line)

    candidate_lines = [
        _normalize_line(line)
        for line in (preamble[:20] if preamble else lines[:15])
        if _normalize_line(line)
    ]
    best_title = ""
    best_score = float("-inf")
    max_run = min(3, len(candidate_lines))
    for start in range(len(candidate_lines)):
        combined_parts: list[str] = []
        for end in range(start, min(start + max_run, len(candidate_lines))):
            line = candidate_lines[end]
            if _is_bad_title_candidate(line):
                break
            combined_parts.append(line)
            combined = _normalize_line(" ".join(combined_parts))
            score = _title_score(combined) + len(combined_parts) * 6.0
            if score > best_score:
                best_score = score
                best_title = combined

    if best_title and best_score > float("-inf"):
        return best_title
    return path.stem.replace("_", " ").replace("-", " ").strip()


def extract_abstract(text: str) -> str:
    normalized = re.sub(r"\r", "\n", text)
    patterns = [
        r"(?is)\babstract\b\s*[-—:：]?\s*(.*?)(?:\n\s*(?:index terms|keywords|introduction|i\.\s+introduction|1\.?\s+introduction)\b)",
        r"(?is)\babstract\b\s*[-—:：]?\s*(.{200,2500})",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            abstract = re.sub(r"\s+", " ", match.group(1)).strip()
            if len(abstract) >= 80:
                return abstract[:3000]
    fallback = re.sub(r"\s+", " ", normalized).strip()
    return fallback[:1200]


def record_for_pdf(path: Path, corpus_root: Path | None = None) -> dict:
    text = extract_text_from_pdf(path)
    rel_paths = ["uploaded"]
    if corpus_root:
        try:
            rel_parent = path.parent.relative_to(corpus_root)
            if str(rel_parent) != ".":
                rel_paths.extend(rel_parent.parts)
        except ValueError:
            pass
    return {
        "id": file_sha256(path),
        "title": extract_title(text, path),
        "abstract": extract_abstract(text),
        "added_date": datetime.now().isoformat(timespec="seconds"),
        "paths": rel_paths,
        "pdf_path": str(path),
        "full_text": text,
    }


def ingest_pdfs(config: DictConfig) -> int:
    inbox_dir = Path(config.paper_corpus.inbox_dir)
    processed_dir = Path(config.paper_corpus.processed_dir)
    failed_dir = Path(config.paper_corpus.failed_dir)
    db_path = Path(config.paper_corpus.db_path)
    max_files = int(config.paper_corpus.get("max_ingest_files", 0) or 0)

    inbox_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)
    failed_dir.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    existing_ids = load_existing_ids(db_path)
    pdfs = sorted(inbox_dir.rglob("*.pdf"))
    if max_files > 0:
        pdfs = pdfs[:max_files]

    ingested = 0
    with db_path.open("a", encoding="utf-8") as db:
        for pdf in pdfs:
            try:
                digest = file_sha256(pdf)
                if digest in existing_ids:
                    logger.info(f"Skip duplicate PDF: {pdf}")
                    target = processed_dir / pdf.name
                    if pdf.resolve() != target.resolve():
                        shutil.move(str(pdf), str(_unique_path(target)))
                    continue
                target = _unique_path(processed_dir / pdf.name)
                record = record_for_pdf(pdf, inbox_dir)
                record["pdf_path"] = str(target)
                db.write(json.dumps(record, ensure_ascii=False) + "\n")
                db.flush()
                existing_ids.add(record["id"])
                shutil.move(str(pdf), str(target))
                ingested += 1
                logger.info(f"Ingested PDF: {pdf}")
            except Exception as exc:
                logger.exception(f"Failed to ingest PDF {pdf}: {exc}")
                try:
                    shutil.move(str(pdf), str(_unique_path(failed_dir / pdf.name)))
                except Exception:
                    pass
    logger.info(f"Ingested {ingested} PDF files into {db_path}")
    return ingested


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for i in range(1, 10000):
        candidate = path.with_name(f"{stem}_{i}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Cannot create unique path for {path}")


dotenv.load_dotenv()


@hydra.main(version_base=None, config_path="../../config", config_name="default")
def main(config: DictConfig):
    ingest_pdfs(config)


if __name__ == "__main__":
    main()
