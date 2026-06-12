import urllib.parse
import urllib.request
import json
from datetime import datetime, date

from loguru import logger

from zotero_arxiv_daily.protocol import Paper

from .base import BaseRetriever, register_retriever


@register_retriever("openalex")
class OpenAlexRetriever(BaseRetriever):
    def _retrieve_raw_papers(self) -> list[dict]:
        queries = self.retriever_config.get("query") or []
        if isinstance(queries, str):
            queries = [queries]
        limit = int(self.retriever_config.get("limit", 25))
        per_query = max(1, limit // max(1, len(queries)))
        results: list[dict] = []
        seen_ids: set[str] = set()
        for query in queries:
            url = self._build_url(query, per_query)
            logger.info(f"Retrieving OpenAlex papers for query: {query}")
            req = urllib.request.Request(url, headers={"User-Agent": "WirelessChannelRecommender/0.1 (mailto:example@example.com)"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            for item in payload.get("results", []):
                item_id = item.get("id")
                if item_id and item_id not in seen_ids:
                    seen_ids.add(item_id)
                    results.append(item)
        return results[:limit]

    def _build_url(self, query: str, per_page: int) -> str:
        params = {
            "search": query,
            "per-page": str(per_page),
            "sort": "publication_date:desc",
        }
        filters = []
        target_date = self.retriever_config.get("target_date")
        if target_date:
            date_str = str(target_date)
        else:
            offset = int(self.retriever_config.get("date_offset_days", 7))
            date_str = (datetime.now() - __import__("datetime").timedelta(days=offset)).strftime("%Y-%m-%d")
        filters.append(f"from_publication_date:{date_str}")
        filters.append(f"to_publication_date:{date_str}")
        if filters:
            params["filter"] = ",".join(filters)
        return "https://api.openalex.org/works?" + urllib.parse.urlencode(params)

    def convert_to_paper(self, raw_paper: dict) -> Paper | None:
        title = raw_paper.get("title") or raw_paper.get("display_name")
        abstract = abstract_from_inverted_index(raw_paper.get("abstract_inverted_index"))
        if not title or not abstract or len(abstract) < 100:
            return None
        authors = []
        for authorship in raw_paper.get("authorships") or []:
            author = authorship.get("author") or {}
            if author.get("display_name"):
                authors.append(author["display_name"])
        primary_location = raw_paper.get("primary_location") or {}
        source = primary_location.get("source") or {}
        venue = source.get("display_name")
        oa = raw_paper.get("open_access") or {}
        pdf_url = oa.get("oa_url") or primary_location.get("pdf_url")
        url = raw_paper.get("doi") or raw_paper.get("id")
        published_date = None
        if raw_paper.get("publication_date"):
            try:
                published_date = datetime.fromisoformat(raw_paper["publication_date"])
            except ValueError:
                published_date = None
        return Paper(
            source=self.name,
            title=title,
            authors=authors,
            abstract=abstract,
            url=url,
            pdf_url=pdf_url,
            doi=raw_paper.get("doi"),
            venue=venue,
            published_date=published_date,
            source_urls={self.name: url},
        )


def abstract_from_inverted_index(index: dict | None) -> str | None:
    if not index:
        return None
    positions: list[tuple[int, str]] = []
    for word, locs in index.items():
        for loc in locs:
            positions.append((int(loc), word))
    if not positions:
        return None
    return " ".join(word for _, word in sorted(positions))
