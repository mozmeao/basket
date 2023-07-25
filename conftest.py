import pytest
from markus.testing import MetricsMock


@pytest.fixture
def metrics_mock():
    with MetricsMock() as mm:
        yield mm
