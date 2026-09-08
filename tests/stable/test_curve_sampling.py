"""PDF numeric noise must not change a glyph's curve sampling at integer ties."""

import math

import numpy as np
import pytest

from pdf2dxf_stable.engine.geometry.base import CubicSeg, flatten_cubic
from pdf2dxf_stable.engine.text.font_catalog import _flatten_cubic


@pytest.mark.parametrize("font_builder", [False, True])
@pytest.mark.parametrize("samples", [9, 32])
@pytest.mark.parametrize("noise", [-0.00008, 0.00008, 0.0002, 0.25])
def test_sampling_count_stabilizes_only_a_bounded_integer_tie(
    font_builder, samples, noise
):
    # Equal-height controls over a horizontal chord give an independently
    # specified flatness. The sample-count boundary is the source of the bug,
    # not a tolerance on glyph masks or DXF coordinates.
    flatness = 0.12 * ((samples + noise - 2) / 5) ** 2
    controls = ((0, 0), (1, flatness), (2, flatness), (3, 0))
    actual = (
        _flatten_cubic(*controls, 0.12)
        if font_builder
        else flatten_cubic(CubicSeg(*controls), 0.12)
    )
    expected_count = samples if abs(noise) < 0.0001 else samples + 1
    assert len(actual) == expected_count
    t = np.linspace(0, 1, expected_count)
    # Analytical cubic: x=3t, y=3h*t*(1-t). No coordinate rounding,
    # endpoint movement, or substitution of a neighboring curve is allowed.
    np.testing.assert_allclose(
        actual,
        np.column_stack((3 * t, 3 * flatness * t * (1 - t))),
        rtol=0,
        atol=1e-12,
    )
    assert actual[0] == controls[0] and actual[-1] == controls[-1]


@pytest.mark.parametrize(
    "scale,offset", [(1, (0, 0)), (20, (713, 40)), (1000, (1e6, -1e6))]
)
def test_font_and_converter_sampling_remain_in_step(scale, offset):
    flatness = 0.12 * ((9.000077 - 2) / 5) ** 2
    controls = np.array(((0, 0), (1, flatness), (2, flatness), (3, 0)))
    moved = controls * scale + offset
    converter = np.array(flatten_cubic(CubicSeg(*moved), 0.12 * scale))
    builder = np.array(_flatten_cubic(*moved, 0.12 * scale))
    assert len(converter) == len(builder) == 9
    np.testing.assert_allclose(converter, builder, rtol=0, atol=1e-9)
    t = np.linspace(0, 1, 9)
    expected = np.column_stack((3 * t, 3 * flatness * t * (1 - t)))
    np.testing.assert_allclose(
        (converter - offset) / scale, expected, rtol=0, atol=1e-10
    )


@pytest.mark.parametrize("flatness,cap", [(0, 96), (1e-10, 96), (1e8, 96), (100, 12)])
def test_sampling_limits_and_non_boundary_behavior_are_preserved(flatness, cap):
    controls = ((0, 0), (1, flatness), (2, flatness), (3, 0))
    expected = max(4, min(cap, math.ceil(2 + math.sqrt(flatness / 0.12) * 5)))
    assert len(flatten_cubic(CubicSeg(*controls), 0.12, cap)) == expected
    assert len(_flatten_cubic(*controls, 0.12, cap)) == expected
