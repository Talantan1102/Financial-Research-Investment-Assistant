"""L0 — Bocha error class hierarchy and instantiation."""

from app.services.bocha_errors import (
    BochaAuthError,
    BochaClientError,
    BochaError,
    BochaNetworkError,
    BochaRateLimitError,
    BochaServerError,
)


def test_all_inherit_from_base() -> None:
    for cls in (
        BochaNetworkError,
        BochaRateLimitError,
        BochaAuthError,
        BochaServerError,
        BochaClientError,
    ):
        assert issubclass(cls, BochaError)


def test_can_instantiate_with_message() -> None:
    e = BochaNetworkError("connection reset")
    assert str(e) == "connection reset"


def test_can_chain_with_cause() -> None:
    try:
        try:
            raise OSError("dns failure")
        except OSError as orig:
            raise BochaNetworkError("wrap") from orig
    except BochaNetworkError as e:
        assert isinstance(e.__cause__, OSError)


def test_distinct_classes() -> None:
    """Each class is its own subtype — except blocks can target one without catching others."""
    classes = [
        BochaNetworkError,
        BochaRateLimitError,
        BochaAuthError,
        BochaServerError,
        BochaClientError,
    ]
    for i, c1 in enumerate(classes):
        for j, c2 in enumerate(classes):
            if i != j:
                assert not issubclass(c1, c2)
