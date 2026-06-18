"""Relevance filter for paper recommendation.

Filters papers based on a group profile:
- Must match at least one core keyword (hard gate)
- Combined core/scenario score must clear a threshold
- If negative keywords dominate, reject
"""

import re
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path

import yaml

# Group research profile is maintained in config/group_profile.yaml, not here.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_GROUP_PROFILE_PATH = _PROJECT_ROOT / "config" / "group_profile.yaml"

# Fallback used only if config/group_profile.yaml is missing (e.g. installed package).
_FALLBACK_KW_CORE: list[str] = [
    "channel model",
    "channel modeling",
    "non-stationary",
    "geometry-based",
    "gbsm",
    "channel measurement",
    "channel sounding",
    "path loss",
    "shadow fading",
    "doppler",
    "channel estimation",
    "propagation channel",
    "mimo channel",
    "massive mimo",
]
_FALLBACK_KW_SCENARIO: list[str] = [
    "uav",
    "v2v",
    "vehicular",
    "mmwave",
    "ris",
    "isac",
    "integrated sensing",
]
_FALLBACK_KW_NEGATIVE: list[str] = [
    "graph signal",
    "blockchain",
    "supply chain",
    "financial",
    "social network",
]


def _load_group_profile(path: Path = _GROUP_PROFILE_PATH) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("profile", {})


_profile_data = _load_group_profile()

KW_CORE: list[str] = _profile_data.get("core_keywords") or _FALLBACK_KW_CORE
KW_SCENARIO: list[str] = _profile_data.get("scenario_keywords") or _FALLBACK_KW_SCENARIO
KW_NEGATIVE: list[str] = _profile_data.get("negative_keywords") or _FALLBACK_KW_NEGATIVE

_scoring = _profile_data.get("scoring", {})


@dataclass
class ProfileKeywords:
    core_keywords: list[str]
    scenario_keywords: list[str]
    negative_keywords: list[str]


@dataclass
class FilterResult:
    passed: bool
    score: float  # positive = relevant, <=0 should be dropped
    reason: str = ""


_BASE_CORE_WEIGHT = _scoring.get("core_weight", 2.0)
_SCENARIO_WEIGHT = _scoring.get("scenario_weight", 1.5)
_NEGATIVE_PENALTY = _scoring.get("negative_penalty", -5.0)


class RelevanceFilter:
    """Check if a paper matches the group's research profile."""

    def __init__(self, profile: ProfileKeywords):
        self.core = _compile_keywords(profile.core_keywords)
        self.scenario = _compile_keywords(profile.scenario_keywords)
        self.negative = _compile_keywords(profile.negative_keywords)

    def evaluate(self, title: str, abstract: str = "") -> FilterResult:
        text = (title + " " + abstract).lower()

        core_hits = sum(1 for pat in self.core if pat.search(text))
        scenario_hits = sum(1 for pat in self.scenario if pat.search(text))
        negative_hits = sum(1 for pat in self.negative if pat.search(text))

        score = (
            core_hits * _BASE_CORE_WEIGHT
            + scenario_hits * _SCENARIO_WEIGHT
            + negative_hits * _NEGATIVE_PENALTY
        )

        if negative_hits >= 1 and core_hits <= 1 and scenario_hits <= 1:
            return FilterResult(
                passed=False,
                score=score,
                reason=f"Negative keywords dominate: {negative_hits} negatives vs core={core_hits}, scenario={scenario_hits}",
            )

        if core_hits == 0:
            return FilterResult(
                passed=False,
                score=score,
                reason=f"No core keyword matched (scenario={scenario_hits}, negative={negative_hits})",
            )

        pass_threshold = 3.0
        if score < pass_threshold:
            return FilterResult(
                passed=False,
                score=score,
                reason=f"Score below threshold: score={score:.2f} < {pass_threshold:.2f} (core={core_hits}, scenario={scenario_hits})",
            )

        return FilterResult(
            passed=True,
            score=score,
            reason=f"core={core_hits}, scenario={scenario_hits}, negative={negative_hits}",
        )


def _compile_keywords(kws: list[str]) -> list[re.Pattern]:
    """Compile keyword list into regex patterns for matching."""
    result = []
    for kw in kws:
        kw = kw.strip().lower()
        # Use word-boundary matching for multi-word phrases
        if " " in kw:
            pattern = r"\b" + re.escape(kw) + r"\b"
        else:
            pattern = r"\b" + re.escape(kw) + r"[a-z]*\b"
        try:
            result.append(re.compile(pattern))
        except re.error:
            pass
    return result


# Default profile instance
_DEFAULT_PROFILE = ProfileKeywords(
    core_keywords=KW_CORE,
    scenario_keywords=KW_SCENARIO,
    negative_keywords=KW_NEGATIVE,
)

_default_filter: RelevanceFilter | None = None


def get_default_filter() -> RelevanceFilter:
    global _default_filter
    if _default_filter is None:
        _default_filter = RelevanceFilter(_DEFAULT_PROFILE)
    return _default_filter


def filter_papers(
    papers: list,
    title_attr: str = "title",
    abstract_attr: str = "abstract",
) -> list:
    """Filter a list of Paper objects, returning only those that pass.

    Sets a ``_filter_score`` and ``_filter_reason`` attribute on each paper.
    """
    filt = get_default_filter()
    kept: list = []
    for p in papers:
        t = getattr(p, title_attr, "")
        a = getattr(p, abstract_attr, "")
        result = filt.evaluate(t, a)
        setattr(p, "_filter_score", result.score)
        setattr(p, "_filter_reason", result.reason)
        if result.passed:
            kept.append(p)
    return kept


def filter_by_target_date(papers: list, target: datetime | None) -> list:
    """Keep only papers whose published_date matches *exactly* the target date.

    Papers without a published_date are discarded.
    """
    if target is None:
        return papers
    kept: list = []
    for p in papers:
        pd = getattr(p, "published_date", None)
        if pd is None:
            continue
        if pd.date() == target.date():
            kept.append(p)
    return kept


def parse_target_date(date_str: str | None) -> datetime | None:
    """Parse a 'YYYY-MM-DD' string into a datetime, or return None."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d")
    except (ValueError, AttributeError):
        return None
