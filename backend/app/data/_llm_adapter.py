# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""Backward-compat shim — moved to app.services.openai_client.

Kept to avoid breaking any out-of-tree references.  New code should import
directly from ``app.services.openai_client``.
"""

from app.services.openai_client import build_llm_service_from_env  # noqa: F401

__all__ = ["build_llm_service_from_env"]
