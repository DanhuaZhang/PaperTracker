"""IEEE source = CrossRef member:263. No IEEE Xplore API key required."""

from __future__ import annotations

import datetime as dt

from .. import config
from . import crossref_client

IEEE_MEMBER_ID = 263


def fetch(
    start_date: dt.date,
    end_date: dt.date,
    profile: config.ProjectProfile | None = None,
) -> list[dict]:
    return crossref_client.search(
        member_id=IEEE_MEMBER_ID,
        source_label="ieee",
        start_date=start_date,
        end_date=end_date,
        profile=profile,
    )
