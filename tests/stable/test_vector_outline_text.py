import ezdxf
import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from pdf2dxf_stable.engine.text.font_catalog import FontCatalogError, build_font_catalog
from pdf2dxf_stable.engine.text.outline_text import recover_outline_text


CHARS = "口日目田由"


def _shapes():
    outer = [(0, 0), (800, 0), (800, 800), (0, 800)]
    result = {}
    for count, char in enumerate(CHARS[:3], 1):
        holes = []
        for i in range(count):
            y = 100 + i * 600 / count
            holes.append(
                [(100, y), (100, y + 450 / count), (700, y + 450 / count), (700, y)]
            )
        result[char] = [outer, *holes]
    holes = [
        [(x, y), (x, y + 220), (x + 220, y + 220), (x + 220, y)]
        for x in (100, 480)
        for y in (100, 480)
    ]
    result["田"] = [outer, *holes]
    result["由"] = [
        [
            (0, 0),
            (800, 0),
            (800, 800),
            (440, 800),
            (440, 980),
            (360, 980),
            (360, 800),
            (0, 800),
        ],
        *holes,
    ]
    return result


def _font(path):
    shapes = _shapes()
    order = [".notdef", *shapes]
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap({ord(c): c for c in shapes})
    glyphs = {}
    for name in order:
        pen = TTGlyphPen(None)
        for ring in shapes.get(name, []):
            pen.moveTo(ring[0])
            for p in ring[1:]:
                pen.lineTo(p)
            pen.closePath()
        glyphs[name] = pen.glyph()
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics({n: (1000, 0) for n in order})
    fb.setupHorizontalHeader(ascent=1000, descent=-100)
    fb.setupNameTable({"familyName": "Vector Test", "styleName": "Regular"})
    fb.setupOS2(
        sTypoAscender=1000, sTypoDescender=-100, usWinAscent=1000, usWinDescent=100
    )
    fb.setupPost(keepGlyphNames=False)
    fb.setupMaxp()
    fb.save(path)
    return path


def _drawing(path, rows=2):
    doc = ezdxf.new("R2018")
    doc.appids.new("PDF2DXF15")
    doc.layers.new("OUTLINE")
    for row in range(rows):
        for i, char in enumerate(CHARS):
            hatch = doc.modelspace().add_hatch(dxfattribs={"layer": "OUTLINE"})
            for j, ring in enumerate(_shapes()[char]):
                points = [(x * 0.005 + i * 5, y * 0.01 + row * 15) for x, y in ring]
                # A real vector perturbation, below the geometric error budget.
                points[1] = (points[1][0] + 0.008, points[1][1] + 0.006)
                hatch.paths.add_polyline_path(
                    points, is_closed=True, flags=1 if j == 0 else 0
                )
            hatch.set_xdata(
                "PDF2DXF15",
                [(1000, "hatch"), (1070, 0), (1070, row * 100 + i), (1000, "f")],
            )
    doc.saveas(path)
    return path


def test_compressed_resampled_han_need_vector_geometry(tmp_path):
    font = _font(tmp_path / "font.ttf")
    source = _drawing(tmp_path / "drawing.dxf")
    legacy = tmp_path / "old.p2dfont"
    build_font_catalog(font, legacy, codepoints=map(ord, CHARS))
    assert (
        recover_outline_text(
            source, mode="required", policy="keep", font_catalog_paths=[legacy]
        )["emitted_text_entities"]
        == 0
    )
    from pdf2dxf_stable.engine.text.vector_catalog import build_vector_font_catalog

    catalog = tmp_path / "font.p2dvec"
    build_vector_font_catalog(font, catalog, codepoints=map(ord, CHARS))
    font.unlink()  # Recognition must use persisted DXF/templates only.
    before = ezdxf.readfile(source)
    report = recover_outline_text(
        source, mode="required", policy="keep", font_catalog_paths=[catalog]
    )
    after = ezdxf.readfile(source)
    assert [r["text"] for r in report["accepted"]] == [CHARS, CHARS]
    assert report["font_vector_glyph_matches"] == 10
    assert len(after.modelspace().query("HATCH")) == len(
        before.modelspace().query("HATCH")
    )
    assert not after.audit().errors
    again = recover_outline_text(
        source, mode="required", policy="keep", font_catalog_paths=[catalog]
    )
    assert again["emitted_text_entities"] == 0


def test_single_row_cannot_lock_vector_font(tmp_path):
    from pdf2dxf_stable.engine.text.vector_catalog import build_vector_font_catalog

    font = _font(tmp_path / "font.ttf")
    catalog = tmp_path / "font.p2dvec"
    build_vector_font_catalog(font, catalog, codepoints=map(ord, CHARS))
    report = recover_outline_text(
        _drawing(tmp_path / "single.dxf", rows=1),
        mode="required",
        font_catalog_paths=[catalog],
    )
    assert report["emitted_text_entities"] == 0


def test_vector_catalog_rejects_corruption(tmp_path):
    from pdf2dxf_stable.engine.text.vector_catalog import (
        build_vector_font_catalog,
        load_vector_font_catalog,
    )

    font = _font(tmp_path / "font.ttf")
    path = tmp_path / "font.p2dvec"
    build_vector_font_catalog(font, path, codepoints=map(ord, CHARS))
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0xFF
    path.write_bytes(data)
    with pytest.raises(FontCatalogError):
        load_vector_font_catalog(path)


def test_same_outline_different_unicode_is_not_guessed(tmp_path):
    from fontTools.ttLib import TTFont
    from pdf2dxf_stable.engine.text.vector_catalog import build_vector_font_catalog

    path = _font(tmp_path / "font.ttf")
    with TTFont(path) as font:
        for table in font["cmap"].tables:
            if table.isUnicode():
                table.cmap[ord("回")] = table.cmap[ord("口")]
        font.save(tmp_path / "alias.ttf")
    catalog = tmp_path / "alias.p2dvec"
    build_vector_font_catalog(tmp_path / "alias.ttf", catalog)
    report = recover_outline_text(
        _drawing(tmp_path / "drawing.dxf"),
        mode="required",
        font_catalog_paths=[catalog],
    )
    assert report["font_vector_ambiguous_glyphs"] >= 2
    assert report["emitted_text_entities"] == 0


def test_incomplete_paint_cannot_become_a_character(tmp_path):
    from pdf2dxf_stable.engine.text.vector_catalog import build_vector_font_catalog

    catalog = tmp_path / "font.p2dvec"
    build_vector_font_catalog(_font(tmp_path / "font.ttf"), catalog)
    path = _drawing(tmp_path / "drawing.dxf")
    doc = ezdxf.readfile(path)
    for seq in [0, 100]:
        large = doc.modelspace().add_hatch(dxfattribs={"layer": "OUTLINE"})
        large.paths.add_polyline_path([(30, 30), (60, 30), (60, 60), (30, 60)])
        large.set_xdata(
            "PDF2DXF15", [(1000, "hatch"), (1070, 0), (1070, seq), (1000, "f")]
        )
    doc.saveas(path)
    report = recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert report["emitted_text_entities"] == 0


def test_changed_stroke_is_not_matched_by_word_context(tmp_path):
    from pdf2dxf_stable.engine.text.vector_catalog import build_vector_font_catalog

    catalog = tmp_path / "font.p2dvec"
    build_vector_font_catalog(_font(tmp_path / "font.ttf"), catalog)
    path = _drawing(tmp_path / "drawing.dxf")
    doc = ezdxf.readfile(path)
    for row in [0, 1]:
        extra = doc.modelspace().add_hatch(dxfattribs={"layer": "OUTLINE"})
        extra.paths.add_polyline_path(
            [
                (1, 2 + row * 15),
                (1.3, 2 + row * 15),
                (1.3, 3 + row * 15),
                (1, 3 + row * 15),
            ]
        )
        extra.set_xdata(
            "PDF2DXF15", [(1000, "hatch"), (1070, 0), (1070, row * 100), (1000, "f")]
        )
    doc.saveas(path)
    report = recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert report["emitted_text_entities"] == 0


def test_source_sequence_gap_breaks_vector_consensus(tmp_path):
    from pdf2dxf_stable.engine.text.vector_catalog import build_vector_font_catalog

    catalog = tmp_path / "font.p2dvec"
    build_vector_font_catalog(_font(tmp_path / "font.ttf"), catalog)
    path = _drawing(tmp_path / "drawing.dxf")
    doc = ezdxf.readfile(path)
    for row, entity in enumerate(list(doc.modelspace().query("HATCH"))[2::5]):
        entity.set_xdata(
            "PDF2DXF15",
            [(1000, "hatch"), (1070, 0), (1070, row * 100 + 50), (1000, "f")],
        )
    doc.saveas(path)
    report = recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert report["emitted_text_entities"] == 0


def test_cli_builds_and_inspects_vector_catalog(tmp_path, capsys):
    import json
    from pdf2dxf_stable.cli import main

    source = _font(tmp_path / "font.ttf")
    target = tmp_path / "font.p2dvec"
    assert (
        main(["font-catalog", "build", str(source), "--vector", "-o", str(target)]) == 0
    )
    assert json.loads(capsys.readouterr().out)["mapped_codepoints"] == len(CHARS)
    assert main(["font-catalog", "inspect", str(target)]) == 0
    assert (
        json.loads(capsys.readouterr().out)["schema"]
        == "pdf2dxf.vector_font_catalog.v1"
    )


def test_printer_budget_requires_saved_paper_mm_lattice():
    import numpy as np
    from pdf2dxf_stable.engine.text.vector_text import _printer_grid

    pitch = 25.4 / 600
    points = np.array([(x, y) for x in range(4) for y in range(4)], dtype=float) * pitch
    points += [0.12345, 0.31415]
    assert _printer_grid(points, paper_mm=True) == pitch
    assert _printer_grid(points, paper_mm=False) == 0
    points[2, 0] += pitch * 0.05
    assert _printer_grid(points, paper_mm=True) == 0


def test_boundary_match_also_checks_nesting_topology():
    import numpy as np
    from pdf2dxf_stable.engine.text.vector_catalog import _topology

    def ring(a, b):
        return np.array([(a, a), (b, a), (b, b), (a, b), (a, a)], dtype=float)

    assert _topology([ring(0, 10), ring(2, 8), ring(4, 6)]) == (0, 1, 2)
    assert _topology([ring(0, 2), ring(3, 5), ring(6, 8)]) == (0, 0, 0)


def test_font_catalog_and_saved_hatch_agree_on_nested_ink(tmp_path, monkeypatch):
    from pdf2dxf_stable.engine.text.vector_catalog import (
        build_vector_font_catalog,
        load_vector_font_catalog,
    )

    shapes = _shapes()
    shapes["口"].append([(250, 250), (450, 250), (450, 450), (250, 450)])
    monkeypatch.setitem(globals(), "_shapes", lambda: shapes)
    catalog = tmp_path / "nested.p2dvec"
    build_vector_font_catalog(_font(tmp_path / "nested.ttf"), catalog)
    resource = load_vector_font_catalog(catalog)
    row = list(resource.arrays["codepoints.npy"]).index(ord("口"))
    assert len(resource.paths(row)) == 3
    result = recover_outline_text(
        _drawing(tmp_path / "nested.dxf"),
        mode="required",
        policy="keep",
        font_catalog_paths=[catalog],
    )
    assert [r["text"] for r in result["accepted"]] == [CHARS, CHARS]
