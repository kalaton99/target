from __future__ import annotations

import os


LOCAL_TABLE_BOOTSTRAP_COUNT = 5
LOCAL_DEMO_CREATOR_PREFIX = "local_demo_bootstrap"


def local_table_bootstrap_enabled() -> bool:
    value = os.environ.get("WINSGET_LOCAL_TABLE_BOOTSTRAP", "0").strip().lower()
    return value in {"1", "true", "yes", "on"}


def is_local_demo_creator(user_id: str) -> bool:
    return str(user_id or "").startswith(LOCAL_DEMO_CREATOR_PREFIX)
