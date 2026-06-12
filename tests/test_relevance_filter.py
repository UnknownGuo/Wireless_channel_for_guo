from zotero_arxiv_daily.relevance_filter import (
    RelevanceFilter,
    ProfileKeywords,
    KW_CORE,
    KW_SCENARIO,
    KW_NEGATIVE,
)


def test_relevance_filter_passes_good_paper():
    prof = ProfileKeywords(
        core_keywords=KW_CORE,
        scenario_keywords=KW_SCENARIO,
        negative_keywords=KW_NEGATIVE,
    )
    filt = RelevanceFilter(prof)

    result = filt.evaluate(
        title="A 3D Non-Stationary GBSM for UAV-to-Ground MIMO Channels",
        abstract="This paper proposes a geometry-based stochastic channel model for UAV-to-Ground MIMO communications.",
    )
    assert result.passed is True, f"Good paper should pass but got: {result.reason}"
    assert result.score > 0


def test_relevance_filter_rejects_off_topic():
    prof = ProfileKeywords(
        core_keywords=KW_CORE,
        scenario_keywords=KW_SCENARIO,
        negative_keywords=KW_NEGATIVE,
    )
    filt = RelevanceFilter(prof)

    result = filt.evaluate(
        title="Optimal Wiener Filter Solutions for Graph Signal Denoising",
        abstract="This paper presents a new approach to denoising signals on directed graphs using optimal Wiener filters.",
    )
    assert result.passed is False, f"Off-topic paper should be rejected but got: {result.reason}"
    assert result.score <= 0


def test_relevance_filter_edge_case_no_core():
    prof = ProfileKeywords(
        core_keywords=KW_CORE,
        scenario_keywords=KW_SCENARIO,
        negative_keywords=KW_NEGATIVE,
    )
    filt = RelevanceFilter(prof)

    result = filt.evaluate(
        title="A Novel Optimization Framework for Cloud Computing",
        abstract="We propose an optimization algorithm for resource allocation in cloud computing environments.",
    )
    assert result.passed is False
    assert result.score <= 0


def test_relevance_filter_barely_passes():
    prof = ProfileKeywords(
        core_keywords=KW_CORE,
        scenario_keywords=KW_SCENARIO,
        negative_keywords=KW_NEGATIVE,
    )
    filt = RelevanceFilter(prof)

    result = filt.evaluate(
        title="Channel Estimation for mmWave Communication Systems",
        abstract="This paper studies the channel estimation problem in mmWave MIMO systems.",
    )
    assert result.passed is True
    assert result.score > 0
