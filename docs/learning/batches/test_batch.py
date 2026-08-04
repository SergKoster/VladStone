import pytest
from batch import process, StopBatch

def test_all_success():
    result = process([1, 2, 3], lambda x: x * 2)
    assert result == [2, 4, 6]


def test_one_item_fails():

    def risky(x):
        return 10 // x

    result = process([1, 0, 5], risky)
    assert result == [10, 2]


def test_stop_batch():

    def risky(x):
        if x == 52:
            raise StopBatch
        else:
            return x * 5

    with pytest.raises(StopBatch):
        process([1, 52, 5], risky)
    

