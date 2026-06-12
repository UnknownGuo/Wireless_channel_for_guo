import pytest
from datetime import datetime
from zotero_arxiv_daily.protocol import Paper


def make_paper(title, published_date=None):
    p = Paper(
        source="test",
        title=title,
        authors=["Test Author"],
        abstract="A paper about channel modeling for UAV communications.",
        url="https://example.com/paper",
    )
    if published_date:
        p.published_date = published_date
    return p


def test_target_date_filter_keeps_exact_match():
    from zotero_arxiv_daily.relevance_filter import filter_by_target_date

    papers = [
        make_paper("paper1", datetime(2026, 6, 8)),
        make_paper("paper2", datetime(2026, 6, 7)),
        make_paper("paper3", datetime(2026, 6, 9)),
    ]
    target = datetime(2026, 6, 8)
    result = filter_by_target_date(papers, target)
    assert len(result) == 1
    assert result[0].title == "paper1"


def test_target_date_filter_returns_empty_when_none_match():
    from zotero_arxiv_daily.relevance_filter import filter_by_target_date

    papers = [make_paper("paper1", datetime(2026, 6, 7))]
    target = datetime(2026, 6, 8)
    result = filter_by_target_date(papers, target)
    assert len(result) == 0


def test_target_date_filter_skips_papers_without_date():
    from zotero_arxiv_daily.relevance_filter import filter_by_target_date

    papers = [make_paper("no_date_paper")]  # no published_date set
    target = datetime(2026, 6, 8)
    result = filter_by_target_date(papers, target)
    assert len(result) == 0


def test_target_date_parse():
    from zotero_arxiv_daily.relevance_filter import parse_target_date

    dt = parse_target_date("2026-06-08")
    assert dt == datetime(2026, 6, 8)

    dt2 = parse_target_date(None)
    assert dt2 is None
