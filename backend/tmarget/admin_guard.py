from __future__ import annotations

import os

from fastapi import Header, HTTPException


async def demo_admin_guard(x_axwins_demo_admin: str | None = Header(default=None, alias="X-Axwins-Demo-Admin")) -> None:
    """Local/demo-only Tmarget admin guard.

    This is intentionally not production authorization. It only prevents the
    demo admin endpoints from being accidentally open during local Axwins MVP
    testing while real admin roles remain deferred.
    """
    enabled = os.environ.get("TMARGET_DEMO_ADMIN_ENABLED", "1").lower() not in {"0", "false", "no"}
    if not enabled or str(x_axwins_demo_admin or "").lower() not in {"1", "true", "demo"}:
        raise HTTPException(status_code=403, detail="TMARGET_DEMO_ADMIN_ONLY")
