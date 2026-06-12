from abc import ABC, abstractmethod
import re
from typing import Type

import numpy as np
from omegaconf import DictConfig

from ..protocol import CorpusPaper, Paper


_CONCLUSION_HEADING_RE = re.compile(
    r"^(?:#{1,6}\s*)?(?:\d+(?:\.\d+)*\s*)?(?:conclusion(?:s)?|discussion and conclusions?|final remarks?)\.?\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _looks_like_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith("#"):
        return True
    if re.match(r"^\d+(?:\.\d+)*\s+[A-Z]", stripped):
        return True
    if len(stripped) <= 90 and re.match(r"^[A-Z][A-Za-z0-9 ,:&()/\-]{3,}$", stripped) and not stripped.endswith((".", ":")):
        return True
    return False


def extract_conclusion_text(full_text: str | None, max_chars: int = 1200) -> str:
    if not full_text:
        return ""

    text = full_text.replace("\r\n", "\n")
    match = _CONCLUSION_HEADING_RE.search(text)
    if not match:
        return ""

    remainder = text[match.end():]
    lines = remainder.splitlines()
    collected: list[str] = []
    started = False

    for line in lines:
        stripped = line.strip()
        if not started:
            if not stripped:
                continue
            started = True
        if _looks_like_heading(stripped):
            break
        if stripped:
            collected.append(stripped)
            if len(" ".join(collected)) >= max_chars:
                break

    return _normalize_whitespace(" ".join(collected))[:max_chars]


def build_embedding_text(paper: Paper | CorpusPaper) -> str:
    parts: list[str] = []

    title = getattr(paper, "title", "") or ""
    abstract = getattr(paper, "abstract", "") or ""
    full_text = getattr(paper, "full_text", None)

    if title.strip():
        parts.append(f"Title: {title.strip()}")
    if abstract.strip():
        parts.append(f"Abstract: {abstract.strip()}")

    conclusion = extract_conclusion_text(full_text)
    if conclusion:
        parts.append(f"Conclusion: {conclusion}")

    return "\n\n".join(parts)


class BaseReranker(ABC):
    def __init__(self, config: DictConfig):
        self.config = config

    def rerank(self, candidates: list[Paper], corpus: list[CorpusPaper]) -> list[Paper]:
        corpus = sorted(corpus, key=lambda x: x.added_date, reverse=True)
        time_decay_weight = 1 / (1 + np.log10(np.arange(len(corpus)) + 1))
        time_decay_weight: np.ndarray = time_decay_weight / time_decay_weight.sum()
        sim = self.get_similarity_score(
            [build_embedding_text(c) for c in candidates],
            [build_embedding_text(c) for c in corpus],
        )
        assert sim.shape == (len(candidates), len(corpus))
        scores = (sim * time_decay_weight).sum(axis=1) * 10  # [n_candidate]
        for s, c in zip(scores, candidates):
            c.score = s
        candidates = sorted(candidates, key=lambda x: float(x.score or 0.0), reverse=True)
        return candidates

    @abstractmethod
    def get_similarity_score(self, s1: list[str], s2: list[str]) -> np.ndarray:
        raise NotImplementedError


registered_rerankers = {}


def register_reranker(name: str):
    def decorator(cls):
        registered_rerankers[name] = cls
        return cls

    return decorator


def get_reranker_cls(name: str) -> Type[BaseReranker]:
    if name not in registered_rerankers:
        raise ValueError(f"Reranker {name} not found")
    return registered_rerankers[name]