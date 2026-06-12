"""
Keyword-only reranker that ranks papers by keyword match score.

Works WITHOUT a local corpus — purely based on keyword hits
from the relevance filter. The _filter_score set on each paper
is used as the primary ranking signal.

This reranker is independent of the embedding API and local PDF corpus.
"""
from typing import Optional

import numpy as np

from ..protocol import Paper, CorpusPaper
from .base import BaseReranker, register_reranker


@register_reranker("keyword_only")
class KeywordOnlyReranker(BaseReranker):
    """Rank papers purely by keyword relevance, no embedding or corpus needed.

    Uses the ``_filter_score`` attribute set by the relevance filter.
    If ``_filter_score`` is absent, falls back to a simple TF-like count
    on title + abstract.
    """

    def rerank(self, candidates: list[Paper], corpus: Optional[list[CorpusPaper]] = None) -> list[Paper]:
        for c in candidates:
            filter_score = getattr(c, "_filter_score", None)
            if filter_score is not None:
                c.score = float(filter_score)
            else:
                # fallback: count meaningful words
                text = (c.title + " " + (c.abstract or "")).lower()
                c.score = len([w for w in text.split() if len(w) > 3]) / 20.0

        candidates.sort(key=lambda x: x.score if x.score is not None else 0.0, reverse=True)
        return candidates

    def get_similarity_score(self, s1: list[str], s2: list[str]) -> np.ndarray:
        raise NotImplementedError("keyword_only reranker does not use get_similarity_score")
