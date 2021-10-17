import numpy as np
import pytest

from iplotlib.core.signal import SimpleSignal


def test_numpy_pick_smaller(example_numpy_data):
    assert do_pick(example_numpy_data, 1.3) == [1, 6]


def test_numpy_pick_bigger(example_numpy_data):
    assert do_pick(example_numpy_data, 1.7) == [2, 7]


def test_numpy_pick_equal(example_numpy_data):
    assert do_pick(example_numpy_data, 0) == [0, 5]


def test_pick_smaller(example_data):
    assert do_pick(example_data, 1.3) == [1, 6]


def test_pick_bigger(example_data):
    assert do_pick(example_data, 1.7) == [2, 7]


def test_pick_equal(example_data):
    assert do_pick(example_data, 0) == [0, 5]


def test_pick_none():
    assert do_pick(None, 0) is None


def test_pick_elements_none():
    assert do_pick([None, None], 0) is None


def test_pick_elements_invalid():
    assert do_pick([[0, 1, 2], None], 0) == [0, None]


def test_pick_equal64(example_int64_data):
    assert do_pick(example_int64_data, 1607941560000000102) == [1607941560000000102, 7]

@pytest.fixture
def example_int64_data():
    return [[1607941560000000100, 1607941560000000101, 1607941560000000102, 1607941560000000103, 1607941560000000104], [5, 6, 7, 8, 9]]


@pytest.fixture
def example_data():
    return [[0, 1, 2, 3, 4], [5, 6, 7, 8, 9]]


@pytest.fixture
def example_numpy_data():
    return [np.array([0, 1, 2, 3, 4]), np.array([5, 6, 7, 8, 9])]


def do_pick(data, sample):
    signal = SimpleSignal()
    signal.set_data(data)
    return signal.pick(sample)
