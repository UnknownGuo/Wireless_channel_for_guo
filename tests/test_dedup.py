from datetime import datetime

from zotero_arxiv_daily.dedup import deduplicate_papers
from zotero_arxiv_daily.protocol import Paper


def make_paper(title, doi=None, arxiv_id=None, source="test", abstract="abstract", authors=None):
    return Paper(
        source=source,
        title=title,
        authors=authors or ["Alice Smith", "Bob Chen"],
        abstract=abstract,
        url=f"https://example.com/{title}",
        doi=doi,
        arxiv_id=arxiv_id,
        venue="IEEE Transactions on Wireless Communications" if source == "ieee" else None,
        published_date=datetime(2026, 6, 9),
    )


def test_deduplicate_papers_merges_same_doi_and_preserves_sources():
    arxiv = make_paper("RIS Assisted Channel Modeling", doi="10.1109/example", source="arxiv")
    ieee = make_paper(
        "RIS Assisted Channel Modeling",
        doi="https://doi.org/10.1109/example",
        source="ieee",
        abstract="longer abstract from ieee about wireless channel modeling",
    )

    result = deduplicate_papers([arxiv, ieee])

    assert len(result) == 1
    assert result[0].doi == "10.1109/example"
    assert result[0].source == "arxiv+ieee"
    assert result[0].abstract == "longer abstract from ieee about wireless channel modeling"
    assert "arxiv" in result[0].source_urls
    assert "ieee" in result[0].source_urls


def test_deduplicate_papers_merges_same_normalized_title():
    first = make_paper("A General 3-D Non-Stationary Wireless Channel Model", source="openalex")
    second = make_paper("A General 3D Non Stationary Wireless Channel Model", source="semantic_scholar")

    result = deduplicate_papers([first, second])

    assert len(result) == 1
    assert result[0].source == "openalex+semantic_scholar"
