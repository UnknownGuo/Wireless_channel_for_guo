from abc import ABC, abstractmethod
from typing import Type

from omegaconf import DictConfig

from zotero_arxiv_daily.protocol import CorpusPaper


class BaseCorpusProvider(ABC):
    def __init__(self, config: DictConfig):
        self.config = config

    @abstractmethod
    def fetch_corpus(self) -> list[CorpusPaper]:
        raise NotImplementedError


registered_corpus_providers: dict[str, Type[BaseCorpusProvider]] = {}


def register_corpus_provider(name: str):
    def decorator(cls):
        registered_corpus_providers[name] = cls
        return cls

    return decorator


def get_corpus_provider_cls(name: str) -> Type[BaseCorpusProvider]:
    if name not in registered_corpus_providers:
        raise ValueError(f"Corpus provider {name} not found")
    return registered_corpus_providers[name]
