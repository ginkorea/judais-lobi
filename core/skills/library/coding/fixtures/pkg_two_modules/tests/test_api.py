import pytest

from api import compute


def test_add():
    assert compute("add", 2, 3) == 5


def test_unknown_operation_is_refused():
    with pytest.raises(ValueError):
        compute("nope", 1, 1)
