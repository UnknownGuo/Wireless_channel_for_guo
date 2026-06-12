import json
from datetime import datetime
from pathlib import Path

import pymupdf
from loguru import logger

from zotero_arxiv_daily.protocol import CorpusPaper

from .base import BaseCorpusProvider, register_corpus_provider


@register_corpus_provider("local_pdf")
class LocalPdfCorpusProvider(BaseCorpusProvider):
    def fetch_corpus(self) -> list[CorpusPaper]:
        db_path = Path(self.config.paper_corpus.db_path)
        if not db_path.exists():
            logger.warning(f"Local corpus database does not exist: {db_path}")
            return []

        corpus: list[CorpusPaper] = []
        with db_path.open("r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    abstract = (record.get("abstract") or "").strip()
                    if not abstract:
                        continue
                    full_text = (record.get("full_text") or "").strip()
                    pdf_path = (record.get("pdf_path") or "").strip()
                    if not full_text and pdf_path:
                        full_text = _extract_pdf_text(Path(pdf_path))
                    raw_paths = record.get("paths") or []
                    if isinstance(raw_paths, list):
                        paths = [str(p) for p in raw_paths]
                    else:
                        paths = [str(raw_paths)]
                    corpus.append(
                        CorpusPaper(
                            title=(record.get("title") or "Untitled").strip(),
                            abstract=abstract,
                            added_date=_parse_datetime(record.get("added_date")),
                            paths=paths,
                            full_text=full_text or None,
                        )
                    )
                except Exception as exc:
                    logger.warning(f"Skip malformed corpus record {db_path}:{line_no}: {exc}")
        logger.info(f"Loaded {len(corpus)} local corpus papers from {db_path}")
        return corpus


def _extract_pdf_text(path: Path, max_pages: int = 9999) -> str:
    if not path.exists():
        return ""
    parts: list[str] = []
    with pymupdf.open(path) as doc:
        for page in doc[: min(max_pages, len(doc))]:
            parts.append(page.get_text("text"))
    return "\n".join(parts)


def _parse_datetime(value) -> datetime:
    if not value:
        return datetime.fromtimestamp(0)
    if isinstance(value, datetime):
        return value
    value = str(value).replace("Z", "+00:00")
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt
