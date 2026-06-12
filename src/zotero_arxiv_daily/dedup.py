import re
from copy import copy

from zotero_arxiv_daily.protocol import Paper


def normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    value = doi.strip().lower()
    value = re.sub(r"^https?://(dx\.)?doi\.org/", "", value)
    value = value.removeprefix("doi:").strip()
    return value or None


def normalize_title(title: str | None) -> str:
    value = (title or "").lower()
    value = value.replace("3-d", "3d")
    value = value.replace("non-stationary", "non stationary")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def paper_identity(paper: Paper) -> str:
    doi = normalize_doi(getattr(paper, "doi", None))
    if doi:
        return f"doi:{doi}"
    arxiv_id = getattr(paper, "arxiv_id", None)
    if arxiv_id:
        return f"arxiv:{str(arxiv_id).lower().replace('v1', '').replace('v2', '').replace('v3', '')}"
    return f"title:{normalize_title(paper.title)}"


def deduplicate_papers(papers: list[Paper]) -> list[Paper]:
    merged: dict[str, Paper] = {}
    order: list[str] = []

    for paper in papers:
        key = paper_identity(paper)
        if key not in merged:
            item = copy(paper)
            item.doi = normalize_doi(getattr(item, "doi", None))
            item.source_urls = dict(getattr(item, "source_urls", None) or {})
            item.source_urls.setdefault(item.source, item.url)
            merged[key] = item
            order.append(key)
            continue

        existing = merged[key]
        existing_sources = set(existing.source.split("+"))
        existing_sources.add(paper.source)
        existing.source = "+".join(sorted(existing_sources))

        if not existing.doi:
            existing.doi = normalize_doi(getattr(paper, "doi", None))
        if not existing.arxiv_id:
            existing.arxiv_id = getattr(paper, "arxiv_id", None)
        if not existing.venue:
            existing.venue = getattr(paper, "venue", None)
        if not existing.pdf_url:
            existing.pdf_url = paper.pdf_url
        if len(paper.abstract or "") > len(existing.abstract or ""):
            existing.abstract = paper.abstract
        if len(paper.title or "") > len(existing.title or ""):
            existing.title = paper.title
        if not existing.published_date:
            existing.published_date = getattr(paper, "published_date", None)

        if existing.source_urls is None:
            existing.source_urls = {}
        existing.source_urls.setdefault(paper.source, paper.url)

    return [merged[key] for key in order]
