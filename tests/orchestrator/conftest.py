import pytest


@pytest.fixture
def pool(tmp_path):
    p = tmp_path / "pool"
    (p / "tickets").mkdir(parents=True)
    return p
