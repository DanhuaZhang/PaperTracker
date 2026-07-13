from papertracker import summary_cache


def test_lookup_is_template_scoped():
    cache = {
        "arxiv:1::A": {"summary": "A result"},
        "arxiv:1::B": {"summary": "B result"},
    }
    paper = {"canonical_id": "arxiv:1"}

    assert summary_cache.lookup(cache, paper, "A") == "A result"
    assert summary_cache.lookup(cache, paper, "B") == "B result"


def test_lookup_misses_other_template():
    cache = {"arxiv:1::A": {"summary": "A result"}}

    assert summary_cache.lookup(cache, {"canonical_id": "arxiv:1"}, "B") is None


def test_cache_key_uses_template_id():
    assert summary_cache.cache_key("arxiv:1", "deep") == "arxiv:1::deep"
