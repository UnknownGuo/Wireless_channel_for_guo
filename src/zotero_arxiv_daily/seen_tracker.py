"""Cross-day duplicate prevention.

Records DOIs and arXiv IDs of already-sent papers in a JSON file
so they are not recommended again on subsequent days.
"""

import json
import os
from pathlib import Path
from typing import Optional

from loguru import logger

from zotero_arxiv_daily.protocol import Paper

DEFAULT_SEEN_FILE = "data/seen_papers.json"


def _get_seen_path(config_path: Optional[str] = None) -> Path:
    """Resolve path to the seen-papers tracking file."""
    if config_path:
        p = Path(config_path)
    else:
        p = Path(DEFAULT_SEEN_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_seen_papers(path: Path) -> set[str]:
    """Load previously-seen paper identifiers from the JSON file."""
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return set(data.get("seen", []))
    except (json.JSONDecodeError, KeyError, TypeError):
        logger.warning(f"Corrupted seen-papers file {path}, starting fresh")
        return set()


def save_seen_papers(path: Path, seen: set[str]) -> None:
    """Persist seen identifiers to the JSON file."""
    payload = {"seen": sorted(seen)}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def paper_identity(paper: Paper) -> str | None:
    """Return a stable, deduplicatable identifier for a paper."""
    if getattr(paper, "doi", None):
        # Normalize DOI
        doi = paper.doi.strip().lower()
        for prefix in ("https://doi.org/", "http://dx.doi.org/", "doi:"):
            if doi.startswith(prefix):
                doi = doi[len(prefix):]
        return f"doi:{doi}"
    if getattr(paper, "arxiv_id", None):
        aid = paper.arxiv_id.strip().lower().split("v")[0]  # remove version suffix
        return f"arxiv:{aid}"
    # fallback: normalized title (weaker, but catches the rest)
    title = (paper.title or "").lower().strip()
    import re
    title = re.sub(r"[^a-z0-9]+", " ", title).strip()
    if len(title) > 10:
        # Use first 80 chars as a fingerprint
        return f"title:{title[:80]}"
    return None


def filter_seen_papers(
    papers: list[Paper],
    seen_file: str | None = None,
    commit: bool = True,
) -> list[Paper]:
    """Remove papers that have already been sent on previous days.

    If ``commit`` is True (default), newly-seen identifiers are persisted
    immediately. Pass ``commit=False`` and call :func:`mark_seen` later —
    e.g. only after the email has actually been sent — so that a dry run
    or a failed send doesn't permanently remove papers from future
    recommendations.
    """
    path = _get_seen_path(seen_file)
    seen = load_seen_papers(path)

    kept: list[Paper] = []
    newly_seen: set[str] = set()

    for p in papers:
        pid = paper_identity(p)
        if pid is None:
            kept.append(p)
            continue
        if pid in seen:
            logger.debug(f"Skipping already-seen paper: {pid} — {p.title[:60]}")
            continue
        kept.append(p)
        newly_seen.add(pid)

    if commit and newly_seen:
        mark_seen(seen_file, newly_seen)

    return kept


def mark_seen(seen_file: str | None, identifiers: set[str]) -> None:
    """Persist additional identifiers as seen (e.g. after a successful send)."""
    if not identifiers:
        return
    path = _get_seen_path(seen_file)
    seen = load_seen_papers(path)
    fresh = seen | identifiers
    if fresh != seen:
        save_seen_papers(path, fresh)
