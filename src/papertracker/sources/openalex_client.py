"""OpenAlex client — abstract fallback only.

OpenAlex stores abstracts as `abstract_inverted_index` mapping word -> [positions].
We reconstruct the abstract by placing each word at every position and joining.
"""
from __future__ import annotations

import logging

import requests

from .. import config

log = logging.getLogger(__name__)

_ENDPOINT = "https://api.openalex.org/works"


def fetch_abstract(doi: str) -> str | None:
    if not doi:
        return None
    url = f"{_ENDPOINT}/https://doi.org/{doi}"
    params = {"mailto": config.USER_EMAIL} if config.USER_EMAIL else {}
    try:
        resp = requests.get(
            url,
            params=params,
            headers={"User-Agent": config.USER_AGENT},
            timeout=15,
        )
        if resp.status_code != 200:
            log.debug("OpenAlex %s -> %d", doi, resp.status_code)
            return None
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        log.debug("OpenAlex error for %s: %s", doi, e)
        return None

    inv = data.get("abstract_inverted_index")
    if not inv:
        return None
    return _reconstruct_abstract(inv)


def _reconstruct_abstract(inv: dict) -> str:
    positions: list[tuple[int, str]] = []
    for word, idxs in inv.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort(key=lambda t: t[0])
    return " ".join(w for _, w in positions)
