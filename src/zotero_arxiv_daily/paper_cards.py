from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import pymupdf


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_text_from_pdf(path: Path, max_pages: int = 3, tail_pages: int = 0) -> str:
    parts: list[str] = []
    with pymupdf.open(path) as doc:
        total_pages = len(doc)
        head_count = min(max_pages, total_pages)
        indices = list(range(head_count))
        if tail_pages > 0:
            tail_start = max(0, total_pages - tail_pages)
            for idx in range(tail_start, total_pages):
                if idx not in indices:
                    indices.append(idx)
        for idx in indices:
            parts.append(str(doc[idx].get_text("text")))
    return "\n".join(parts)


def _normalize_line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", text or ""))


def _looks_like_author_or_affiliation(line: str) -> bool:
    s = _normalize_line(line)
    if not s:
        return False
    lower = s.lower()
    affiliation_markers = (
        "university",
        "institute",
        "department",
        "laboratory",
        "school of",
        "college",
        "faculty",
        "academy",
        "technische universität",
        "technology",
    )
    if any(marker in lower for marker in affiliation_markers):
        return True
    if re.fullmatch(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,4}(?:,\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,4})+", s):
        return True
    return False


def _is_bad_title_candidate(line: str) -> bool:
    s = _normalize_line(line)
    if not s:
        return True
    lower = s.lower()
    bad_patterns = (
        "abstract",
        "summary",
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
    if _looks_like_author_or_affiliation(s):
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
        if re.match(r"(?i)^\s*(abstract|summary|keywords|index terms)\b", _normalize_line(line)):
            break
        preamble.append(line)

    candidate_lines = [
        _normalize_line(line)
        for line in (preamble[:20] if preamble else [])
        if _normalize_line(line)
    ]
    if not candidate_lines:
        return path.stem.replace("_", " ").replace("-", " ").strip()

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
        r"(?ism)^\s*summary\s*[-—:：]\s*(.*?)(?:\n\s*(?:index terms|keywords|introduction|i\.\s+introduction|1\.?\s+introduction)\b)",
        r"(?ism)^\s*summary\s*[-—:：]\s*(.{80,2500})",
        r"(?is)\b摘要\b\s*[-—:：]?\s*(.*?)(?:\n\s*(?:关键词|关键字|引言|1\.?\s*引言)\b)",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            abstract = re.sub(r"\s+", " ", match.group(1)).strip()
            if len(abstract) >= 80:
                return abstract[:3000]
    return ""


def extract_keywords(text: str) -> list[str]:
    patterns = [
        r"(?im)^\s*keywords?\s*[-—:：]\s*(.+)$",
        r"(?im)^\s*index terms\s*[-—:：]\s*(.+)$",
        r"(?im)^\s*(?:关键词|关键字)\s*[-—:：]\s*(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        raw = _normalize_line(match.group(1))
        if not raw:
            continue
        parts = [
            p.strip(" ;,，；。.·•")
            for p in re.split(r"[;,，；]", raw)
        ]
        keywords = [p for p in parts if p]
        if keywords:
            return keywords[:12]
    return []


def _looks_like_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith("#"):
        return True
    reference_headings = r"(?:references?|refrences?|refrence|bibliography|works cited)"
    back_matter_headings = rf"(?:{reference_headings}|acknowledg(?:e)?ments?|参考文献|致谢)"
    if re.match(r"^\d+(?:\.\d+)*\s+[A-Z]", stripped):
        return True
    if re.match(r"^(?:[IVXLCDM]+)\.?(?:\s+[A-Z]|\s*$)", stripped, re.I):
        return True
    if re.match(rf"^\d+(?:\.\d+)*\s*[-—:]?\s*{back_matter_headings}$", stripped, re.I):
        return True
    if re.match(rf"^(?:[IVXLCDM]+)\.?(?:\s*[-—:]?\s*)?{back_matter_headings}$", stripped, re.I):
        return True
    if re.match(rf"^{back_matter_headings}$", stripped, re.I):
        return True
    words = re.findall(r"[A-Za-z][A-Za-z0-9'\-]*", stripped)
    if len(stripped) <= 90 and words and not stripped.endswith((".", ":")):
        title_case_words = sum(1 for word in words if word[:1].isupper())
        if title_case_words >= max(2, int(len(words) * 0.7)):
            return True
    return False


def extract_conclusion(full_text: str, max_chars: int = 1600) -> str:
    if not full_text:
        return ""
    heading_re = re.compile(
        r"^(?:#{1,6}\s*)?(?:(?:\d+(?:\.\d+)*)|(?:[IVXLCDM]+))?\.?\s*(?:conclusion(?:s)?(?: and comments?)?|discussion and conclusions?|summary(?: and conclusions?)?|concluding remarks?|final remarks?|结论|总结|结语)\.?\s*$",
        re.I | re.M,
    )
    match = heading_re.search(full_text)
    if not match:
        return ""
    remainder = full_text[match.end():]
    lines = remainder.splitlines()
    collected: list[str] = []
    started = False
    for line in lines:
        stripped = line.strip()
        if not started:
            if not stripped:
                continue
            started = True
        if _looks_like_heading(stripped):
            break
        if stripped:
            collected.append(stripped)
            if len(" ".join(collected)) >= max_chars:
                break
    return _normalize_line(" ".join(collected))[:max_chars]


def build_text_for_embedding(title: str, abstract: str, keywords: list[str], conclusion: str) -> str:
    parts: list[str] = []
    if title:
        parts.append(f"Title: {title}")
    if abstract:
        parts.append(f"Abstract: {abstract}")
    if keywords:
        parts.append(f"Keywords: {', '.join(keywords)}")
    if conclusion:
        parts.append(f"Conclusion: {conclusion}")
    return "\n\n".join(parts)


def build_status(
    title: str,
    abstract: str,
    keywords: list[str],
    conclusion: str,
    *,
    skipped: bool = False,
    skip_reason: str = "",
) -> dict[str, bool | str]:
    title_ok = bool(_normalize_line(title)) and not skipped
    abstract_ok = bool(_normalize_line(abstract)) and not skipped
    keywords_ok = bool(keywords) and not skipped
    conclusion_ok = bool(_normalize_line(conclusion)) and not skipped
    return {
        "title_ok": title_ok,
        "abstract_ok": abstract_ok,
        "keywords_ok": keywords_ok,
        "conclusion_ok": conclusion_ok,
        "usable_for_embedding": (title_ok and abstract_ok) and not skipped,
        "skipped": skipped,
        "skip_reason": skip_reason,
    }


def compute_quality_score(status: dict[str, Any]) -> float:
    score = 0.0
    score += 0.35 if status["title_ok"] else 0.0
    score += 0.4 if status["abstract_ok"] else 0.0
    score += 0.1 if status["keywords_ok"] else 0.0
    score += 0.15 if status["conclusion_ok"] else 0.0
    return round(min(score, 1.0), 4)


def record_for_pdf(path: Path, corpus_root: Path | None = None, max_pages: int = 3) -> dict[str, Any]:
    text = extract_text_from_pdf(path, max_pages=max_pages)
    conclusion_text = extract_text_from_pdf(path, max_pages=max_pages, tail_pages=3)
    rel_paths = ["uploaded"]
    if corpus_root:
        try:
            rel_parent = path.parent.relative_to(corpus_root)
            if str(rel_parent) != ".":
                rel_paths.extend(rel_parent.parts)
        except ValueError:
            pass

    if _contains_cjk(path.name) or _contains_cjk(text[:4000]):
        status = build_status("", "", [], "", skipped=True, skip_reason="chinese_detected")
        now = datetime.now().isoformat(timespec="seconds")
        return {
            "id": file_sha256(path),
            "path": str(path),
            "title": "",
            "abstract": "",
            "keywords": [],
            "conclusion": "",
            "text_for_embedding": "",
            "status": status,
            "quality_score": compute_quality_score(status),
            "source": "local_pdf",
            "added_date": now,
            "extracted_at": now,
            "paths": rel_paths,
            "pdf_path": str(path),
            "full_text": "",
        }

    title = extract_title(text, path)
    abstract = extract_abstract(text)
    keywords = extract_keywords(text)
    conclusion = extract_conclusion(conclusion_text)
    status = build_status(title, abstract, keywords, conclusion)

    return {
        "id": file_sha256(path),
        "path": str(path),
        "title": title,
        "abstract": abstract,
        "keywords": keywords,
        "conclusion": conclusion,
        "text_for_embedding": build_text_for_embedding(title, abstract, keywords, conclusion),
        "status": status,
        "quality_score": compute_quality_score(status),
        "source": "local_pdf",
        "added_date": datetime.now().isoformat(timespec="seconds"),
        "extracted_at": datetime.now().isoformat(timespec="seconds"),
        "paths": rel_paths,
        "pdf_path": str(path),
        "full_text": text,
    }


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


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    field_counts = Counter({
        "title_ok": 0,
        "abstract_ok": 0,
        "keywords_ok": 0,
        "conclusion_ok": 0,
    })
    usable = 0
    skipped = 0
    failed_examples: list[dict[str, Any]] = []

    for record in records:
        status = record.get("status") or {}
        if status.get("skipped"):
            skipped += 1
            continue
        for field in field_counts:
            if status.get(field):
                field_counts[field] += 1
        if status.get("usable_for_embedding"):
            usable += 1
        else:
            failed_examples.append({
                "path": record.get("path") or record.get("pdf_path"),
                "status": status,
            })

    processed = total - skipped
    rates = {
        field: (count / processed if processed else 0.0)
        for field, count in field_counts.items()
    }
    return {
        "total_records": total,
        "processed_records": processed,
        "skipped_records": skipped,
        "usable_for_embedding": usable,
        "usable_rate": usable / processed if processed else 0.0,
        "field_success": dict(field_counts),
        "field_success_rate": rates,
        "failed_examples": failed_examples[:20],
    }


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def extract_cards_from_directory(
    input_root: Path,
    output_jsonl: Path,
    failed_jsonl: Path | None = None,
    summary_json: Path | None = None,
    limit: int | None = None,
    max_pages: int = 3,
) -> dict[str, Any]:
    pdf_paths = sorted(input_root.rglob("*.pdf"))
    if limit is not None:
        pdf_paths = pdf_paths[:limit]

    records = [record_for_pdf(path, corpus_root=input_root, max_pages=max_pages) for path in pdf_paths]
    _write_jsonl(output_jsonl, records)

    failed_records = [record for record in records if not record.get("status", {}).get("usable_for_embedding")]
    if failed_jsonl is not None:
        _write_jsonl(failed_jsonl, failed_records)

    summary = summarize_records(records)
    if summary_json is not None:
        summary_json.parent.mkdir(parents=True, exist_ok=True)
        summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
