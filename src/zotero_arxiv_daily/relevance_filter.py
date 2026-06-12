"""Relevance filter for paper recommendation.

Filters papers based on a group profile:
- Must match at least one core keyword
- Must match at least one scenario keyword (unless core is very strong)
- If negative keywords dominate, reject
"""

import re
from datetime import datetime
from dataclasses import dataclass

# Default keywords extracted from the group's 84 papers
KW_CORE: list[str] = [
    "channel model",
    "channel modeling",
    "non-stationary",
    "geometry-based",
    "gbsm",
    "geometry-based stochastic model",
    "geometry based stochastic model",
    "channel measurement",
    "channel sounding",
    "path loss",
    "shadow fading",
    "doppler",
    "doppler frequency",
    "radio map",
    "spectrum map",
    "beam training",
    "angle estimation",
    "ray tracing",
    "channel estimation",
    "channel parameter",
    "channel characteristic",
    "channel fading",
    "propagation channel",
    "twin-cluster",
    "mimo channel",
    "massive mimo",
    "channel emulator",
    "channel gain map",
    "channel capacity",
    "channel characteristics",
    "channel simulation",
    "isac",
    "integrated sensing",
    "communication and sensing",
    "communications and sensing",
    "sensing and communication",
    "communication-sensing",
    "wireless sensing and communication",
    "spectrum sensing",
    "sensing communication",
]

KW_SCENARIO: list[str] = [
    "uav",
    "uavs",
    "unmanned aerial",
    "unmanned aerial vehicle",
    "airborne",
    "air-to-ground",
    "air-to-air",
    "ground-to-air",
    "space-air-ground",
    "space-ground",
    "spaceborne",
    "satcom",
    "satellite",
    "ntn",
    "non-terrestrial",
    "leo",
    "haps",
    "high altitude platform",
    "v2v",
    "vehicular",
    "mmwave",
    "millimeter wave",
    "ultra-wideband",
    "uwb",
    "ris",
    "reconfigurable intelligent surface",
    "isac",
    "integrated sensing",
    "visible light",
    "maritime",
    "ship",
    "vessel",
    "harbor",
    "port",
    "coastal",
    "railway",
    "hst",
    "high-speed train",
    "lunar",
    "indoor office",
    "cell-free",
    "massive mimo",
    "sub-6 ghz",
    "terahertz",
    "thz",
    "holographic mimo",
    "urban canyon",
    "suburban",
    "rural",
    "mountainous terrain",
    "hilly terrain",
    "rugged terrain",
    "complex terrain",
    "terrain-aware",
    "valley",
    "desert",
    "forest",
    "tunnel",
]

KW_NEGATIVE: list[str] = [
    "graph signal",
    "crisis management",
    "cloud security",
    "traffic volume",
    "traffic estimation",
    "space debris",
    "blockchain",
    "cyber-physical",
    "generic denoising",
    "polynomial chaos",
    "denoising of graph",
    "supply chain",
    "financial",
    "healthcare management",
    "food safety",
    "social network",
]


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


_BASE_CORE_WEIGHT = 2.0
_SCENARIO_WEIGHT = 1.5
_NEGATIVE_PENALTY = -5.0


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

        # Balanced mode: core keywords are strong signals, but not a hard gate.
        # Papers with no core hit can still pass if the overall signal is strong enough.
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
