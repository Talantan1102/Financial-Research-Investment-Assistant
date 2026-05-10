"""L2 e2e memory fixtures — re-export pg_memory_fixture from integration conftest.

pytest does not auto-share fixtures across sibling test directories, so we
explicitly re-export from `tests.integration.memory.conftest` so cassette
tests can hit the same provisioned PG container as L1 integration tests.
"""

from __future__ import annotations

from tests.integration.memory.conftest import (  # noqa: F401
    milvus_memory_fixture,
    pg_memory_fixture,
    pg_memory_session,
    pg_memory_session_factory,
)
