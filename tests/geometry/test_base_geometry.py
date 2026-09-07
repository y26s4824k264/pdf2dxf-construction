from pdf2dxf_stable.engine.geometry.base import CubicSeg, cubic_flatness


def test_cubic_flatness_supports_numpy_without_two_dimensional_cross():
    assert cubic_flatness(CubicSeg((0, 0), (0, 3), (10, -4), (10, 0))) == 4
    assert cubic_flatness(CubicSeg((0, 0), (3, 4), (0, 2), (0, 0))) == 5
