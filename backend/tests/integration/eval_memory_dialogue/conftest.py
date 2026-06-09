"""转发 backend/tests/integration/memory/conftest.py 的真 PG fixture。

不用 pytest_plugins(非根 conftest 声明会在与 memory 目录同跑时触发
插件重复注册);import-star 让 fixture 在本目录可见,plan 预留的 fallback。
"""

from __future__ import annotations

from tests.integration.memory.conftest import *  # noqa: F401,F403
