"""Emergent-managed Google OAuth side-by-side with guest JWT auth."""
from .router import router, is_guest_auth_enabled

__all__ = ["router", "is_guest_auth_enabled"]
