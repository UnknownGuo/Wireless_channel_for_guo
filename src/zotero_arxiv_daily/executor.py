from loguru import logger
from omegaconf import DictConfig
from .retriever import get_retriever_cls
from .reranker import get_reranker_cls
from .construct_email import render_email
from .utils import send_email
from .dedup import deduplicate_papers
from openai import OpenAI
from tqdm import tqdm
from .corpus import get_corpus_provider_cls
from .relevance_filter import filter_papers
from .reranker.base import get_reranker_cls as get_rr_cls
from .seen_tracker import filter_seen_papers, mark_seen, paper_identity


class Executor:
    def __init__(self, config:DictConfig):
        self.config = config
        self.retrievers = {
            source: get_retriever_cls(source)(config) for source in config.executor.source
        }
        self.reranker = get_reranker_cls(config.executor.reranker)(config)
        provider_name = config.get("corpus", {}).get("provider", "local_pdf")
        self.corpus_provider = get_corpus_provider_cls(provider_name)(config)
        self.openai_client = OpenAI(api_key=config.llm.api.key, base_url=config.llm.api.base_url)

    def run(self):
        corpus = self.corpus_provider.fetch_corpus()
        if len(corpus) == 0:
            logger.info("No local corpus — using keyword-only ranking (no embedding)")
            use_embedding = False
        else:
            use_embedding = True

        # Auto-select reranker: if no corpus, fall back to keyword_only
        if not use_embedding and self.reranker.__class__.__name__ not in ("KeywordOnlyReranker", "DebugLexicalReranker"):
            logger.info("Switching reranker to 'keyword_only' (no corpus available)")
            self.reranker = get_rr_cls("keyword_only")(self.config)

        all_papers = []
        for source, retriever in self.retrievers.items():
            logger.info(f"Retrieving {source} papers...")
            papers = retriever.retrieve_papers()
            if len(papers) == 0:
                logger.info(f"No {source} papers found")
                continue
            logger.info(f"Retrieved {len(papers)} {source} papers")
            all_papers.extend(papers)
        logger.info(f"Total {len(all_papers)} papers retrieved from all sources")

        # Step 2: deduplication
        all_papers = deduplicate_papers(all_papers)
        logger.info(f"Total {len(all_papers)} papers after deduplication")

        # Step 2: relevance filter
        if len(all_papers) > 0:
            before = len(all_papers)
            all_papers = filter_papers(all_papers)
            logger.info(f"Total {before} -> {len(all_papers)} papers after relevance filter")

        # Step 3: cross-day dedup — don't re-send papers from previous days.
        # commit=False: only mark these as "seen" after the email actually sends,
        # so a dry run or a failed send doesn't burn papers from future recommendations.
        seen_file = self.config.executor.get("seen_papers_file", None)
        pending_seen_ids: set[str] = set()
        if len(all_papers) > 0:
            before = len(all_papers)
            all_papers = filter_seen_papers(all_papers, seen_file, commit=False)
            pending_seen_ids = {pid for p in all_papers if (pid := paper_identity(p))}
            logger.info(f"Total {before} -> {len(all_papers)} papers after cross-day dedup")
        reranked_papers = []
        if len(all_papers) > 0:
            logger.info("Reranking papers...")
            reranked_papers = self.reranker.rerank(all_papers, corpus)
            reranked_papers = reranked_papers[:self.config.executor.max_paper_num]
            if self.config.executor.get("generate_details", True):
                logger.info("Generating TLDR and affiliations...")
                for p in tqdm(reranked_papers):
                    p.generate_tldr(self.openai_client, self.config.llm)
                    p.generate_affiliations(self.openai_client, self.config.llm)
            else:
                for p in reranked_papers:
                    p.tldr = p.abstract
        elif not self.config.executor.send_empty:
            logger.info("No new papers found. No email will be sent.")
            return
        logger.info("Rendering email/report...")
        email_content = render_email(reranked_papers)
        report_path = self.config.executor.get("report_path", None)
        if report_path:
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(email_content)
            logger.info(f"Report written to {report_path}")
        send_email_flag = self.config.executor.get("send_email", True)
        if isinstance(send_email_flag, str):
            send_email_flag = send_email_flag.strip().lower() == "true"
        if send_email_flag:
            logger.info("Sending email...")
            send_email(self.config, email_content)
            logger.info("Email sent successfully")
            mark_seen(seen_file, pending_seen_ids)
        else:
            logger.info("Email sending disabled by executor.send_email=false")