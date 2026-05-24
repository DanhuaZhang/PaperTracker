"""ACM source = CrossRef member:320. No ACM Digital Library API key required."""
from __future__ import annotations

import datetime as dt

from . import crossref_client

ACM_MEMBER_ID = 320


def fetch(start_date: dt.date, end_date: dt.date) -> list[dict]:
    return crossref_client.search(
        member_id=ACM_MEMBER_ID, source_label="acm",
        start_date=start_date, end_date=end_date,
    )
