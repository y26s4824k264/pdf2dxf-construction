import itertools
import math

import ezdxf
import pytest

from pdf2dxf_stable.dimension_instances import insert_placements
from pdf2dxf_stable.options import output_unit_info
from pdf2dxf_stable.profiles import emit_legacy_r12


@pytest.mark.parametrize("unit,mm_per_unit", [(4, 1), (5, 10), (6, 1000), (1, 25.4)])
def test_r12_curve_error_has_same_physical_tolerance_in_every_unit(
    tmp_path, unit, mm_per_unit
):
    doc = ezdxf.new("R2007")
    doc.header["$INSUNITS"] = unit
    radius = 1000 / mm_per_unit
    doc.modelspace().add_ellipse((0, 0), major_axis=(radius, 0), ratio=1)
    source, output = tmp_path / "curve.dxf", tmp_path / "r12.dxf"
    doc.saveas(source)
    emit_legacy_r12(source, output, seed="physical-tolerance")
    final = ezdxf.readfile(output)
    assert output_unit_info(final)[1] == mm_per_unit
    polyline = next(iter(final.modelspace().query("POLYLINE")))
    points = [v.dxf.location for v in polyline.vertices]
    # Exact sagitta of each chord of this known 1000 mm radius circle.
    errors = [
        1000 - math.sqrt(1000**2 - (a.distance(b) * mm_per_unit / 2) ** 2)
        for a, b in itertools.pairwise(points)
    ]
    assert max(errors) <= 0.05


def test_r12_preserves_all_rotated_array_cells(tmp_path):
    doc = ezdxf.new("R2007")
    block = doc.blocks.new("CELL")
    block.add_line((0, 0), (1, 0))
    doc.modelspace().add_blockref(
        "CELL",
        (10, 20),
        dxfattribs={
            "rotation": 90,
            "xscale": 2,
            "yscale": 2,
            "row_count": 2,
            "column_count": 3,
            "row_spacing": 5,
            "column_spacing": 10,
        },
    )
    source, output = tmp_path / "array.dxf", tmp_path / "r12.dxf"
    doc.saveas(source)
    report = emit_legacy_r12(source, output, seed="array")
    assert not report.warnings
    lines = list(ezdxf.readfile(output).modelspace().query("LINE"))
    assert len(lines) == 6
    actual = {
        (
            round(e.dxf.start.x, 8),
            round(e.dxf.start.y, 8),
            round(e.dxf.end.x, 8),
            round(e.dxf.end.y, 8),
        )
        for e in lines
    }
    assert actual == {
        (10 - 5 * r, 20 + 10 * c, 10 - 5 * r, 22 + 10 * c)
        for r in range(2)
        for c in range(3)
    }


def test_zero_spacing_array_is_collapsed_before_iteration(monkeypatch):
    doc = ezdxf.new("R2007")
    doc.blocks.new("CELL").add_line((0, 0), (1, 0))
    insert = doc.modelspace().add_blockref(
        "CELL",
        (0, 0),
        dxfattribs={
            "row_count": 100_000_000,
            "column_count": 2,
            "row_spacing": 0,
            "column_spacing": 10,
        },
    )
    original = type(insert).multi_insert

    def bounded(entity):
        assert entity.dxf.row_count == 1
        yield from original(entity)

    monkeypatch.setattr(type(insert), "multi_insert", bounded)
    assert [e.dxf.insert.x for e in insert_placements(insert, limit=2)] == [0, 10]
    assert insert.dxf.row_count == 100_000_000
