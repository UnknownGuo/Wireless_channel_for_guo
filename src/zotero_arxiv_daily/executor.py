from loguru import logger
from pyzotero import zotero
from omegaconf import DictConfig
from .utils import glob_match
from .retriever import get_retriever_cls
from .protocol import CorpusPaper
import random
from datetime import datetime
from .reranker import get_reranker_cls
from .construct_email import render_email
from .utils import send_email
from .dedup import deduplicate_papers
from openai import OpenAI
from tqdm import tqdm
from .corpus import get_corpus_provider_cls
from .relevance_filter import filter_papers, filter_by_target_date, parse_target_date
from .reranker.base import get_reranker_cls as get_rr_cls
from .seen_tracker import filter_seen_papers


class Executor:
    def __init__(self, config:DictConfig):
        self.config = config
        self.retrievers = {
            source: get_retriever_cls(source)(config) for source in config.executor.source
        }
        self.reranker = get_reranker_cls(config.executor.reranker)(config)
        provider_name = config.get("corpus", {}).get("provider", "zotero")
        self.corpus_provider = None if provider_name == "zotero" else get_corpus_provider_cls(provider_name)(config)
        self.openai_client = OpenAI(api_key=config.llm.api.key, base_url=config.llm.api.base_url)
    def fetch_zotero_corpus(self) -> list[CorpusPaper]:
        logger.info("Fetching zotero corpus")
        zot = zotero.Zotero(self.config.zotero.user_id, 'user', self.config.zotero.api_key)
        collections = zot.everything(zot.collections())
        collections = {c['key']:c for c in collections}
        corpus = zot.everything(zot.items(itemType='conferencePaper || journalArticle || preprint'))
        corpus = [c for c in corpus if c['data']['abstractNote'] != '']
        def get_collection_path(col_key:str) -> str:
            if p := collections[col_key]['data']['parentCollection']:
                return get_collection_path(p) + '/' + collections[col_key]['data']['name']
            else:
                return collections[col_key]['data']['name']
        for c in corpus:
            paths = [get_collection_path(col) for col in c['data']['collections']]
            c['paths'] = paths
        logger.info(f"Fetched {len(corpus)} zotero papers")
        return [CorpusPaper(
            title=c['data']['title'],
            abstract=c['data']['abstractNote'],
            added_date=datetime.strptime(c['data']['dateAdded'], '%Y-%m-%dT%H:%M:%SZ'),
            paths=c['paths']
        ) for c in corpus]
    
    def filter_corpus(self, corpus:list[CorpusPaper]) -> list[CorpusPaper]:
        if not self.config.zotero.include_path:
            return corpus
        new_corpus = []
        logger.info(f"Selecting zotero papers matching include_path: {self.config.zotero.include_path}")
        for c in corpus:
            match_results = [glob_match(p, self.config.zotero.include_path) for p in c.paths]
            if any(match_results):
                new_corpus.append(c)
        samples = random.sample(new_corpus, min(5, len(new_corpus)))
        samples = '\n'.join([c.title + ' - ' + '\n'.join(c.paths) for c in samples])
        logger.info(f"Selected {len(new_corpus)} zotero papers:\n{samples}\n...")
        return new_corpus

    
    def run(self):
        corpus = self.corpus_provider.fetch_corpus() if self.corpus_provider else self.fetch_zotero_corpus()
        corpus = self.filter_corpus(corpus)
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

        # Step 1: date filter — keep only papers from 7 days ago (or explicit TARGET_DATE)
        target_date = parse_target_date(self.config.get("target_date", None))
        if not target_date:
            # Default: 7 days ago
            from datetime import timedelta
            target_date = datetime.now() - timedelta(days=7)
            logger.info(f"No TARGET_DATE set — filtering to {target_date.date()} (7 days ago)")
        before = len(all_papers)
        all_papers = filter_by_target_date(all_papers, target_date)
        logger.info(f"Total {before} -> {len(all_papers)} papers after date filter")

        # Step 2: deduplication
        all_papers = deduplicate_papers(all_papers)
        logger.info(f"Total {len(all_papers)} papers after deduplication")

        # Step 2: relevance filter
        if len(all_papers) > 0:
            before = len(all_papers)
            all_papers = filter_papers(all_papers)
            logger.info(f"Total {before} -> {len(all_papers)} papers after relevance filter")

        # Step 3: cross-day dedup — don't re-send papers from previous days
        if len(all_papers) > 0:
            before = len(all_papers)
            seen_file = self.config.executor.get("seen_papers_file", None)
            all_papers = filter_seen_papers(all_papers, seen_file)
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
        if self.config.executor.get("send_email", True):
            logger.info("Sending email...")
            send_email(self.config, email_content)
            logger.info("Email sent successfully")
        else:
            logger.info("Email sending disabled by executor.send_email=false")