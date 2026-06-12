import re

import numpy as np

from .base import BaseReranker, register_reranker


@register_reranker("debug_lexical")
class DebugLexicalReranker(BaseReranker):
    """Offline deterministic reranker for local smoke tests when API keys are absent."""

    def get_similarity_score(self, s1: list[str], s2: list[str]) -> np.ndarray:
        token_sets_1 = [_tokens(text) for text in s1]
        token_sets_2 = [_tokens(text) for text in s2]
        sim = np.zeros((len(s1), len(s2)), dtype=float)
        for i, left in enumerate(token_sets_1):
            for j, right in enumerate(token_sets_2):
                if not left or not right:
                    continue
                sim[i, j] = len(left & right) / len(left | right)
        return sim


def _tokens(text: str) -> set[str]:
    return {tok for tok in re.findall(r"[a-zA-Z0-9]{3,}", (text or "").lower())}
