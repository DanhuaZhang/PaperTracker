from papertracker import summary_cache


def test_lookup_is_mode_scoped():
    cache = {"arxiv:1::triage": {"summary": "T"}, "arxiv:1::deep": {"summary": "D"}}
    paper = {"canonical_id": "arxiv:1"}
    assert summary_cache.lookup(cache, paper, "triage") == "T"
    assert summary_cache.lookup(cache, paper, "deep") == "D"


def test_lookup_misses_other_mode():
    cache = {"arxiv:1::triage": {"summary": "T"}}
    assert summary_cache.lookup(cache, {"canonical_id": "arxiv:1"}, "deep") is None


def test_cache_key():
    assert summary_cache.cache_key("arxiv:1", "deep") == "arxiv:1::deep"
