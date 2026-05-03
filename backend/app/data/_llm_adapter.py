"""Backward-compat shim — moved to app.services.openai_client.

Kept to avoid breaking any out-of-tree references.  New code should import
directly from ``app.services.openai_client``.
"""

from app.services.openai_client import build_llm_service_from_env  # noqa: F401

__all__ = ["build_llm_service_from_env"]
