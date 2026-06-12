import pymupdf


def _make_pdf(path, lines, metadata_title=""):
    doc = pymupdf.open()
    page = doc.new_page()
    y = 72
    for line in lines:
        page.insert_text((72, y), line, fontsize=12)
        y += 18
    if metadata_title:
        doc.set_metadata({"title": metadata_title})
    doc.save(path)
    doc.close()


def _make_multipage_pdf(path, pages, metadata_title=""):
    doc = pymupdf.open()
    for page_lines in pages:
        page = doc.new_page()
        y = 72
        for line in page_lines:
            page.insert_text((72, y), line, fontsize=12)
            y += 18
    if metadata_title:
        doc.set_metadata({"title": metadata_title})
    doc.save(path)
    doc.close()


def test_record_for_pdf_builds_offline_card_with_status_and_embedding_text(tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    _make_pdf(
        pdf_path,
        [
            "Received 1 January 2026",
            "A Geometry-Based Wireless Channel Modeling Framework",
            "Abstract",
            "This paper proposes a geometry-based wireless channel modeling framework for UAV and V2V scenarios. "
            "It studies channel evolution, path structure, and non-stationary behavior with enough detail to exceed the abstract threshold.",
            "Keywords: wireless channel modeling; UAV; V2V; non-stationary channel",
            "1 Introduction",
            "Introduction body.",
            "Conclusion",
            "The proposed framework improves modeling fidelity and supports robust comparison against related literature.",
        ],
    )

    from zotero_arxiv_daily.paper_cards import record_for_pdf

    record = record_for_pdf(pdf_path, corpus_root=tmp_path)

    assert record["title"] == "A Geometry-Based Wireless Channel Modeling Framework"
    assert "geometry-based wireless channel modeling" in record["abstract"].lower()
    assert record["keywords"] == ["wireless channel modeling", "UAV", "V2V", "non-stationary channel"]
    assert "improves modeling fidelity" in record["conclusion"].lower()
    assert record["status"]["title_ok"] is True
    assert record["status"]["abstract_ok"] is True
    assert record["status"]["keywords_ok"] is True
    assert record["status"]["conclusion_ok"] is True
    assert record["status"]["usable_for_embedding"] is True
    assert "Title: A Geometry-Based Wireless Channel Modeling Framework" in record["text_for_embedding"]
    assert "Keywords: wireless channel modeling, UAV, V2V, non-stationary channel" in record["text_for_embedding"]
    assert record["quality_score"] > 0.8
    assert record["paths"] == ["uploaded"]


def test_record_for_pdf_keeps_partial_card_when_keywords_and_conclusion_are_missing(tmp_path):
    pdf_path = tmp_path / "fallback-title-paper.pdf"
    _make_pdf(
        pdf_path,
        [
            "Abstract",
            "This paper studies radio environment maps for spectrum awareness in non-stationary channels. "
            "The abstract is intentionally long enough to be accepted as the main semantic payload for embedding.",
            "1 Introduction",
            "Body without explicit keywords or conclusion section.",
        ],
        metadata_title="",
    )

    from zotero_arxiv_daily.paper_cards import record_for_pdf

    record = record_for_pdf(pdf_path, corpus_root=tmp_path)

    assert record["title"] == "fallback title paper"
    assert record["status"]["title_ok"] is True
    assert record["status"]["abstract_ok"] is True
    assert record["status"]["keywords_ok"] is False
    assert record["status"]["conclusion_ok"] is False
    assert record["status"]["usable_for_embedding"] is True
    assert record["keywords"] == []
    assert record["conclusion"] == ""
    assert "Keywords:" not in record["text_for_embedding"]
    assert "Conclusion:" not in record["text_for_embedding"]


def test_record_for_pdf_falls_back_to_summary_style_abstract_and_avoids_author_affiliation_title(tmp_path):
    pdf_path = tmp_path / "legacy-paper.pdf"
    _make_pdf(
        pdf_path,
        [
            "Characterization of Randomly Time-Variant Linear Channels",
            "John Smith, Jane Doe",
            "Vienna University of Technology, Vienna, Austria",
            "Summary-This paper is concerned with various aspects of the characterization of randomly time-variant linear channels. "
            "At the outset, it is demonstrated that time-varying linear channels may be characterized in a symmetrical manner in time and frequency variables. "
            "Following this, a statistical characterization is carried out in terms of correlation functions for the various system functions.",
            "1 Introduction",
            "Body text.",
        ],
    )

    from zotero_arxiv_daily.paper_cards import record_for_pdf

    record = record_for_pdf(pdf_path, corpus_root=tmp_path)

    assert record["title"] == "Characterization of Randomly Time-Variant Linear Channels"
    assert record["status"]["title_ok"] is True
    assert record["status"]["abstract_ok"] is True
    assert "this paper is concerned with various aspects" in record["abstract"].lower()
    assert "Vienna University of Technology" not in record["title"]


def test_record_for_pdf_extracts_summary_conclusion_variant(tmp_path):
    pdf_path = tmp_path / "summary-conclusion.pdf"
    _make_pdf(
        pdf_path,
        [
            "A Useful Wireless Paper",
            "Abstract",
            "This paper studies non-stationary radio channels with enough abstract text to satisfy the extractor and make the card usable for embedding.",
            "5 Summary and Conclusions",
            "The proposed method improves robustness, keeps the model compact, and works well in measurement-driven evaluation.",
            "References",
            "[1] Ref.",
        ],
    )

    from zotero_arxiv_daily.paper_cards import record_for_pdf

    record = record_for_pdf(pdf_path, corpus_root=tmp_path)

    assert record["status"]["conclusion_ok"] is True
    assert "improves robustness" in record["conclusion"].lower()


def test_record_for_pdf_reads_tail_pages_for_conclusion_when_head_pages_miss_it(tmp_path):
    pdf_path = tmp_path / "tail-conclusion.pdf"
    _make_multipage_pdf(
        pdf_path,
        [
            [
                "Tail Conclusion Paper",
                "Abstract",
                "This paper studies wideband channel modeling with enough abstract content to remain usable for embedding.",
                "It also exercises the head-page extraction path while leaving the conclusion only on the tail page.",
            ],
            ["2 Methods", "Method body."],
            ["3 Results", "Results body."],
            ["4 Discussion", "Discussion body."],
            ["5 Conclusion", "The tail-page conclusion confirms the method remains stable on held-out measurements."],
        ],
    )

    from zotero_arxiv_daily.paper_cards import record_for_pdf

    record = record_for_pdf(pdf_path, corpus_root=tmp_path, max_pages=2)

    assert record["status"]["abstract_ok"] is True
    assert record["status"]["conclusion_ok"] is True
    assert "tail-page conclusion confirms" in record["conclusion"].lower()


def test_record_for_pdf_extracts_roman_numeral_conclusions_heading(tmp_path):
    pdf_path = tmp_path / "roman-conclusion.pdf"
    _make_pdf(
        pdf_path,
        [
            "Roman Heading Paper",
            "Abstract",
            "This paper studies vehicular radio channels with enough abstract text to remain usable for embedding and support a regression test.",
            "VI. CONCLUSIONS",
            "The roman-numeral conclusion heading should be recognized by the extractor.",
            "References",
        ],
    )

    from zotero_arxiv_daily.paper_cards import record_for_pdf

    record = record_for_pdf(pdf_path, corpus_root=tmp_path)

    assert record["status"]["conclusion_ok"] is True
    assert "roman-numeral conclusion heading" in record["conclusion"].lower()


def test_extract_conclusion_keeps_sentence_lines_after_heading_even_without_terminal_punctuation():
    from zotero_arxiv_daily.paper_cards import extract_conclusion

    text = """VI. CONCLUSIONS
To which extent the mobile radio channel can be consid-
ered as stationary is crucial for the performance of advanced
MIMO transmission schemes.
References
"""

    conclusion = extract_conclusion(text)

    assert "to which extent the mobile radio channel" in conclusion.lower()
    assert "mimo transmission schemes" in conclusion.lower()


def test_extract_conclusion_stops_at_reference_heading_variants():
    from zotero_arxiv_daily.paper_cards import extract_conclusion

    text = """Conclusion
This is the real conclusion text.
Refrence
[1] first ref
"""
    text2 = """Conclusion
This is the real conclusion text.
Bibliography
[1] first ref
"""

    conclusion1 = extract_conclusion(text)
    conclusion2 = extract_conclusion(text2)

    assert "real conclusion text" in conclusion1.lower()
    assert "[1]" not in conclusion1
    assert "real conclusion text" in conclusion2.lower()
    assert "[1]" not in conclusion2


def test_extract_conclusion_stops_at_acknowledgment_heading_variants():
    from zotero_arxiv_daily.paper_cards import extract_conclusion

    text = """Conclusion
This is the real conclusion text.
Acknowledgment
Thanks to everyone.
"""
    text2 = """Conclusion
This is the real conclusion text.
ACKNOWLEDGEMENTS
Thanks to everyone.
"""

    conclusion1 = extract_conclusion(text)
    conclusion2 = extract_conclusion(text2)

    assert "real conclusion text" in conclusion1.lower()
    assert "thanks to everyone" not in conclusion1.lower()
    assert "real conclusion text" in conclusion2.lower()
    assert "thanks to everyone" not in conclusion2.lower()


def test_extract_conclusion_stops_at_acknowledgment_and_chinese_back_matter_headings():
    from zotero_arxiv_daily.paper_cards import extract_conclusion

    text_ack = """Conclusion
This is the real conclusion text.
Acknowledgments
Thanks to everyone.
"""
    text_cn_ref = """结论
这是真正的结论内容。
参考文献
[1] 第一条参考文献
"""
    text_cn_ack = """结论
这是真正的结论内容。
致谢
感谢团队支持。
"""

    conclusion_ack = extract_conclusion(text_ack)
    conclusion_cn_ref = extract_conclusion(text_cn_ref)
    conclusion_cn_ack = extract_conclusion(text_cn_ack)

    assert "real conclusion text" in conclusion_ack.lower()
    assert "thanks to everyone" not in conclusion_ack.lower()
    assert "真正的结论内容" in conclusion_cn_ref
    assert "第一条参考文献" not in conclusion_cn_ref
    assert "真正的结论内容" in conclusion_cn_ack
    assert "感谢团队支持" not in conclusion_cn_ack


def test_record_for_pdf_skips_chinese_documents(tmp_path):
    pdf_path = tmp_path / "中文论文.pdf"
    _make_pdf(
        pdf_path,
        [
            "中文论文标题",
            "摘要",
            "这是一篇中文论文，用来验证遇到中文内容时直接跳过。",
            "关键词：信道；建模",
        ],
    )

    from zotero_arxiv_daily.paper_cards import record_for_pdf

    record = record_for_pdf(pdf_path, corpus_root=tmp_path)

    assert record["status"]["skipped"] is True
    assert record["status"]["skip_reason"] == "chinese_detected"
    assert record["status"]["usable_for_embedding"] is False
    assert record["text_for_embedding"] == ""
    assert record["quality_score"] == 0.0


def test_record_for_pdf_does_not_skip_english_pdf_just_because_parent_folder_is_chinese(tmp_path):
    chinese_dir = tmp_path / "中文目录"
    chinese_dir.mkdir()
    pdf_path = chinese_dir / "english-paper.pdf"
    _make_pdf(
        pdf_path,
        [
            "An English Wireless Paper",
            "Abstract",
            "This paper studies wireless channels with enough English abstract text to remain usable for embedding in the regression test.",
            "Keywords: wireless channel; modeling",
        ],
    )

    from zotero_arxiv_daily.paper_cards import record_for_pdf

    record = record_for_pdf(pdf_path, corpus_root=tmp_path)

    assert record["status"]["skipped"] is False
    assert record["status"]["abstract_ok"] is True
    assert record["status"]["usable_for_embedding"] is True


def test_summarize_records_counts_success_rates_and_failed_examples():
    from zotero_arxiv_daily.paper_cards import summarize_records

    records = [
        {
            "path": "/tmp/a.pdf",
            "status": {
                "title_ok": True,
                "abstract_ok": True,
                "keywords_ok": True,
                "conclusion_ok": False,
                "usable_for_embedding": True,
            },
        },
        {
            "path": "/tmp/b.pdf",
            "status": {
                "title_ok": True,
                "abstract_ok": False,
                "keywords_ok": False,
                "conclusion_ok": False,
                "usable_for_embedding": False,
            },
        },
    ]

    summary = summarize_records(records)

    assert summary["total_records"] == 2
    assert summary["usable_for_embedding"] == 1
    assert summary["field_success"]["title_ok"] == 2
    assert summary["field_success"]["abstract_ok"] == 1
    assert summary["field_success_rate"]["abstract_ok"] == 0.5
    assert summary["failed_examples"][0]["path"] == "/tmp/b.pdf"


def test_extract_cards_from_directory_writes_jsonl_and_summary(tmp_path):
    input_root = tmp_path / "papers"
    input_root.mkdir()
    _make_pdf(
        input_root / "paper-a.pdf",
        [
            "Paper A Title",
            "Abstract",
            "This paper studies stochastic wireless channel evolution for UAV communication with enough text to pass extraction.",
            "Keywords: UAV; wireless channel",
            "Conclusion",
            "Paper A conclusion text.",
        ],
    )
    _make_pdf(
        input_root / "paper-b.pdf",
        [
            "Paper B Title",
            "Abstract",
            "This paper studies radio maps and spectrum sensing with enough text to pass extraction and remain usable.",
        ],
    )

    from zotero_arxiv_daily.paper_cards import extract_cards_from_directory

    output_jsonl = tmp_path / "cards.jsonl"
    failed_jsonl = tmp_path / "failed.jsonl"
    summary_json = tmp_path / "summary.json"

    result = extract_cards_from_directory(
        input_root=input_root,
        output_jsonl=output_jsonl,
        failed_jsonl=failed_jsonl,
        summary_json=summary_json,
    )

    assert result["total_records"] == 2
    assert output_jsonl.exists()
    assert summary_json.exists()
    assert failed_jsonl.exists()
    lines = output_jsonl.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert '"title": "Paper A Title"' in lines[0] or '"title": "Paper A Title"' in lines[1]
