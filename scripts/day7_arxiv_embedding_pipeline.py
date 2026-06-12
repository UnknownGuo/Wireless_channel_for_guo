from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import arxiv
import dotenv
from loguru import logger
from openai import OpenAI
from omegaconf import OmegaConf

from zotero_arxiv_daily.construct_email import framework, get_block_html, get_empty_html
from zotero_arxiv_daily.dedup import deduplicate_papers
from zotero_arxiv_daily.protocol import Paper
from zotero_arxiv_daily.relevance_filter import filter_papers, filter_by_target_date, parse_target_date
from zotero_arxiv_daily.reranker.api import ApiReranker
from zotero_arxiv_daily.seen_tracker import load_seen_papers, save_seen_papers, paper_identity
from zotero_arxiv_daily.utils import send_email
from zotero_arxiv_daily.corpus import get_corpus_provider_cls

REPO_ROOT = Path(__file__).resolve().parents[1]
DOTENV_PATH = REPO_ROOT / ".env"
LOCAL_CORPUS_PATH = REPO_ROOT / "data" / "card_qa_kingston_save_paper" / "import_ready.jsonl"
OUTPUT_DIR = REPO_ROOT / "outputs" / "day7_arxiv_embedding"
USER_EMAIL = "guomingqi99@gmail.com"


def load_config():
    base = OmegaConf.load(REPO_ROOT / "config" / "base.yaml")
    custom = OmegaConf.load(REPO_ROOT / "config" / "custom.yaml")
    cfg = OmegaConf.merge(base, custom)

    cfg.corpus.provider = "local_pdf"
    cfg.paper_corpus.db_path = str(LOCAL_CORPUS_PATH)
    cfg.executor.source = ["arxiv"]
    cfg.executor.reranker = "api"
    cfg.executor.max_paper_num = 5
    cfg.executor.generate_details = True
    cfg.executor.send_email = True
    cfg.executor.send_empty = False
    cfg.executor.seen_papers_file = str(REPO_ROOT / "data" / "seen_papers.json")
    cfg.executor.report_path = str(OUTPUT_DIR / "report.html")

    cfg.email.receivers = [USER_EMAIL]
    cfg.email.hide_receivers = True
    cfg.llm.language = "Chinese"
    cfg.llm.generation_kwargs.model = "deepseek-chat"
    cfg.llm.generation_kwargs.max_tokens = 2048

    cfg.reranker.api.key = os.environ.get("SILICONFLOW_API_KEY")
    cfg.reranker.api.base_url = os.environ.get("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
    cfg.reranker.api.model = os.environ.get("SILICONFLOW_EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-0.6B")
    cfg.reranker.api.batch_size = 32

    return cfg


def query_arxiv_day(categories: list[str], target_date: datetime) -> tuple[list[Paper], dict[str, int]]:
    client = arxiv.Client(num_retries=8, delay_seconds=2)
    day = target_date.strftime("%Y%m%d")
    papers: list[Paper] = []
    counts: dict[str, int] = {}

    for cat in categories:
        query = f"cat:{cat} AND submittedDate:[{day}0000 TO {day}2359]"
        search = arxiv.Search(
            query=query,
            max_results=200,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending,
        )
        results = list(client.results(search))
        counts[cat] = len(results)
        for r in results:
            arxiv_id = r.entry_id.rstrip("/").split("/")[-1]
            authors = [a.name for a in r.authors]
            papers.append(
                Paper(
                    source="arxiv",
                    title=r.title,
                    authors=authors,
                    abstract=r.summary or "",
                    url=r.entry_id,
                    pdf_url=r.pdf_url,
                    arxiv_id=arxiv_id,
                    source_urls={"arxiv": r.entry_id},
                    published_date=r.published.replace(tzinfo=None) if r.published else None,
                )
            )
    return papers, counts


def safe_json(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: safe_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [safe_json(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "__dict__"):
        return safe_json(vars(obj))
    return obj


def build_overall_summary(client: OpenAI, selected: list[Paper], target_date: datetime) -> str:
    if not selected:
        return "没有可推荐的论文。"

    lines: list[str] = []
    for idx, p in enumerate(selected, start=1):
        score_str = f"{p.score:.2f}" if p.score is not None else "0.00"
        lines.append(
            f"{idx}. {p.title}\n"
            f"   - Score: {score_str}\n"
            f"   - TLDR: {p.tldr or p.abstract[:300]}"
        )

    prompt = (
        "你是科研论文推荐助手。请根据下面 5 篇候选论文，写一段适合邮件发送给课题组成员的中文总评，"
        "要求：\n"
        "1) 120~220 字，先概括这批论文的主题分布和与无线信道建模/UAV/MIMO/频谱图/ISAC 的相关性；\n"
        "2) 再给出 5 条要点，每条 1 句话；\n"
        "3) 语言简洁、直接、像真实科研助手写的邮件摘要。\n\n"
        f"目标日期：{target_date.date()}\n\n"
        + "\n\n".join(lines)
    )
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": "你是一个严谨的科研论文推荐助手，输出中文。"},
            {"role": "user", "content": prompt},
        ],
        max_tokens=900,
    )
    return resp.choices[0].message.content.strip()


def main() -> None:
    dotenv.load_dotenv(DOTENV_PATH)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    cfg = load_config()
    target_date = datetime.now() - timedelta(days=7)

    logger.info(f"Target day: {target_date.date()}")
    logger.info(f"Local corpus: {LOCAL_CORPUS_PATH}")

    arxiv_papers, counts = query_arxiv_day(list(cfg.source.arxiv.category), target_date)
    logger.info(f"Arxiv query counts: {counts}")
    logger.info(f"Retrieved {len(arxiv_papers)} arXiv papers before dedup/filter")

    # Relevance filter before reranking
    arxiv_papers = deduplicate_papers(arxiv_papers)
    logger.info(f"After dedup: {len(arxiv_papers)}")

    seen_path = REPO_ROOT / "data" / "seen_papers.json"
    seen_ids = load_seen_papers(seen_path)
    unseen_papers: list[Paper] = []
    for p in arxiv_papers:
        pid = paper_identity(p)
        if pid is not None and pid in seen_ids:
            continue
        unseen_papers.append(p)
    logger.info(f"After cross-day dedup: {len(unseen_papers)}")

    relevant_papers = filter_papers(unseen_papers)
    logger.info(f"After relevance filter: {len(relevant_papers)}")

    if not unseen_papers:
        logger.warning("No papers survived filtering; nothing to send.")
        return

    corpus_provider = get_corpus_provider_cls(cfg.corpus.provider)(cfg)
    corpus = corpus_provider.fetch_corpus()
    logger.info(f"Loaded local corpus: {len(corpus)} papers")

    reranker = ApiReranker(cfg)
    reranked = reranker.rerank(unseen_papers, corpus)

    relevant_ids = {paper_identity(p) for p in relevant_papers if paper_identity(p) is not None}
    selected = [p for p in reranked if paper_identity(p) in relevant_ids]
    selected_origin = ["relevance" for _ in selected]
    if len(selected) < int(cfg.executor.max_paper_num):
        for p in reranked:
            pid = paper_identity(p)
            if pid in relevant_ids:
                continue
            selected.append(p)
            selected_origin.append("embedding_fallback")
            if len(selected) >= int(cfg.executor.max_paper_num):
                break
    selected = selected[: int(cfg.executor.max_paper_num)]
    selected_origin = selected_origin[: len(selected)]

    logger.info("Top selected papers:")
    for idx, p in enumerate(selected, start=1):
        origin = selected_origin[idx - 1] if idx - 1 < len(selected_origin) else "unknown"
        logger.info(f"{idx:02d}. [{origin}] score={p.score:.3f} | {p.title}")

    fresh_seen = set(seen_ids)
    for p in selected:
        pid = paper_identity(p)
        if pid is not None:
            fresh_seen.add(pid)
    save_seen_papers(seen_path, fresh_seen)

    deepseek_client = OpenAI(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url=os.environ.get("DEEPSEEK_API_BASE", "https://api.deepseek.com"),
    )

    for p in selected:
        p.generate_tldr(deepseek_client, cfg.llm)
        p.generate_affiliations(deepseek_client, cfg.llm)

    overall_summary = build_overall_summary(deepseek_client, selected, target_date)

    items = []
    paper_blocks = []
    for i, p in enumerate(selected, start=1):
        score_str = f"{p.score:.2f}" if p.score is not None else "0.00"
        items.append(f"<li><b>{i}. {p.title}</b> — score {score_str}</li>")
        author_list = ", ".join(p.authors[:3] + (["..."] if len(p.authors) > 5 else []) + p.authors[-2:]) if len(p.authors) > 5 else ", ".join(p.authors)
        affiliations = ", ".join((p.affiliations or [])[:5]) if p.affiliations else "Unknown Affiliation"
        rate = score_str
        tldr = p.tldr or p.abstract
        paper_blocks.append(get_block_html(p.title, author_list, rate, tldr, p.pdf_url or p.url, affiliations))

    summary_html = f"""
    <div style="font-family: Arial, sans-serif; margin-bottom: 24px;">
      <h2>Day-7 arXiv 总结（{target_date.date()}）</h2>
      <p>{overall_summary.replace(chr(10), '<br>')}</p>
      <h3>本次选中的 5 篇</h3>
      <ol>{''.join(items)}</ol>
    </div>
    """

    report_body = summary_html + ("<br>".join(paper_blocks) if paper_blocks else get_empty_html())
    report_html = framework.replace("__CONTENT__", report_body)

    report_path = Path(cfg.executor.report_path)
    report_path.write_text(report_html, encoding="utf-8")

    payload = {
        "target_date": target_date.date().isoformat(),
        "source_counts": counts,
        "total_retrieved": len(arxiv_papers),
        "selected_count": len(selected),
        "selected": [
            {
                "title": p.title,
                "score": p.score,
                "abstract": p.abstract,
                "tldr": p.tldr,
                "pdf_url": p.pdf_url,
                "arxiv_id": p.arxiv_id,
                "authors": p.authors,
                "affiliations": p.affiliations,
            }
            for p in selected
        ],
        "overall_summary": overall_summary,
    }
    (OUTPUT_DIR / "result.json").write_text(json.dumps(safe_json(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT_DIR / "result.md").write_text(
        "# Day-7 arXiv selection\n\n" +
        f"Target date: {target_date.date()}\n\n" +
        overall_summary +
        "\n\n" +
        "\n\n".join([
            f"## {i+1}. {p.title}\n\nScore: {(f'{p.score:.2f}' if p.score is not None else '0.00')}\n\nTLDR: {p.tldr}\n\nPDF: {p.pdf_url}"
            for i, p in enumerate(selected)
        ]),
        encoding="utf-8",
    )

    logger.info(f"Report written to {report_path}")
    if cfg.executor.send_email:
        logger.info("Sending email...")
        send_email(cfg, report_html)
        logger.info("Email sent successfully")


if __name__ == "__main__":
    main()
