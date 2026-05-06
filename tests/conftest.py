from datetime import datetime, timezone

import pytest


@pytest.fixture
def now_utc() -> datetime:
    return datetime(2026, 5, 6, 6, 0, tzinfo=timezone.utc)