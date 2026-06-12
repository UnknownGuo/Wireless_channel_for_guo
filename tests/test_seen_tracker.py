import json
from datetime import datetime
from pathlib import Path

from zotero_arxiv_daily.protocol import Paper
from zotero_arxiv_daily.seen_tracker import (
    filter_seen_papers,
    load_seen_papers,
    save_seen_papers,
    paper_identity,
)


def make_paper(title, doi=None, arxiv_id=None):
    return Paper(
        source="test",
        title=title,
        authors=["Test Author"],
        abstract="A test paper abstract about channel modeling.",
        url=f"https://example.com/{title.replace(' ', '_')}",
        doi=doi,
        arxiv_id=arxiv_id,
        published_date=datetime(2026, 6, 9),
    )


def test_paper_identity_doi():
    p = make_paper("Test Paper", doi="10.1109/TWC.2026.12345")
    pid = paper_identity(p)
    assert pid == "doi:10.1109/twc.2026.12345"


def test_paper_identity_arxiv():
    p = make_paper("Test Paper", arxiv_id="2606.12345v2")
    pid = paper_identity(p)
    assert pid == "arxiv:2606.12345"


def test_paper_identity_title_fallback():
    p = make_paper("A Novel 3D Non-Stationary Channel Model for UAV MIMO Systems")
    pid = paper_identity(p)
    assert pid is not None
    assert pid.startswith("title:")


def test_filter_seen_papers_removes_known_dois(tmp_path):
    seen_file = tmp_path / "seen.json"
    save_seen_papers(seen_file, {"doi:10.1109/twc.2026.12345"})

    papers = [
        make_paper("New Paper", doi="10.1109/NEW.2026.99999"),
        make_paper("Seen Paper", doi="10.1109/TWC.2026.12345"),
    ]
    result = filter_seen_papers(papers, str(seen_file))
    assert len(result) == 1
    assert result[0].title == "New Paper"


def test_filter_seen_papers_stores_new_identifiers(tmp_path):
    seen_file = tmp_path / "seen.json"
    papers = [
        make_paper("Paper A", doi="10.1109/A.2026.11111"),
        make_paper("Paper B", arxiv_id="2606.99999v1"),
    ]
    result = filter_seen_papers(papers, str(seen_file))
    assert len(result) == 2

    stored = load_seen_papers(seen_file)
    assert "doi:10.1109/a.2026.11111" in stored
    assert "arxiv:2606.99999" in stored
