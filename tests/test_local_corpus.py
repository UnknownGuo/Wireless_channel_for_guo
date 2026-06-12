import json
from datetime import datetime

from omegaconf import OmegaConf


def test_local_jsonl_corpus_provider_reads_corpus_papers(tmp_path):
    db_path = tmp_path / "corpus.jsonl"
    db_path.write_text(
        json.dumps(
            {
                "title": "A General 3D Non-Stationary Wireless Channel Model",
                "abstract": "This paper studies wireless channel modeling for 5G and beyond.",
                "added_date": "2026-06-09T12:00:00",
                "paths": ["uploaded", "GBSM"],
                "pdf_path": "/tmp/paper.pdf",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    config = OmegaConf.create({"paper_corpus": {"db_path": str(db_path)}})

    from zotero_arxiv_daily.corpus import get_corpus_provider_cls

    provider = get_corpus_provider_cls("local_pdf")(config)
    corpus = provider.fetch_corpus()

    assert len(corpus) == 1
    assert corpus[0].title == "A General 3D Non-Stationary Wireless Channel Model"
    assert "wireless channel" in corpus[0].abstract
    assert corpus[0].added_date == datetime(2026, 6, 9, 12, 0, 0)
    assert corpus[0].paths == ["uploaded", "GBSM"]


def test_local_jsonl_corpus_provider_skips_records_without_abstract(tmp_path):
    db_path = tmp_path / "corpus.jsonl"
    db_path.write_text(
        json.dumps({"title": "No abstract", "abstract": "", "added_date": "2026-06-09T12:00:00"}) + "\n",
        encoding="utf-8",
    )
    config = OmegaConf.create({"paper_corpus": {"db_path": str(db_path)}})

    from zotero_arxiv_daily.corpus import get_corpus_provider_cls

    provider = get_corpus_provider_cls("local_pdf")(config)

    assert provider.fetch_corpus() == []
