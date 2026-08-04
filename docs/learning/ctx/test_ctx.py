import pytest
from ctx import Resource
from ctx2 import Recource

def test_release_on_error():
    log = []
    with pytest.raises(ValueError):
        with Resource(log):
            log.append("работаю")
            raise ValueError("бум")
    assert log == ["acquire", "работаю", "release"]


def test_release_happy():
    log = []
    with Resource(log):
        log.append("работаю")
    assert log == ["acquire", "работаю", "release"]


def test_generator_on_error():
    log = []
    with pytest.raises(ValueError):
        with Recource(log):
            log.append("работаю")
            raise ValueError("бум")
    assert log == ["acquire", "работаю", "release"]


def test_generator_happy():
    log = []
    with Recource(log):
        log.append("работаю")
    assert log == ["acquire", "работаю", "release"]
