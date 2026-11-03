import struct
import json

import ezdxf
import pytest

from pdf2dxf_stable.engine.text.outline_text import recover_outline_text

CHARS = "工木本大王"
SHAPES = {
    "工": [[(10, 90), (90, 90)], [(50, 90), (50, 10)], [(10, 10), (90, 10)]],
    "木": [
        [(10, 70), (90, 70)],
        [(50, 100), (50, 0)],
        [(50, 70), (10, 10)],
        [(50, 70), (90, 10)],
    ],
    "本": [
        [(10, 70), (90, 70)],
        [(50, 100), (50, 0)],
        [(50, 70), (10, 10)],
        [(50, 70), (90, 10)],
        [(30, 25), (70, 25)],
    ],
    "大": [
        [(10, 70), (90, 70)],
        [(50, 100), (45, 50), (10, 0)],
        [(50, 60), (65, 30), (90, 0)],
    ],
    "王": [
        [(10, 95), (90, 95)],
        [(20, 55), (80, 55)],
        [(50, 95), (50, 5)],
        [(10, 5), (90, 5)],
    ],
}


def font_file(path):
    records = {0: b"Test stroke\0" + bytes([128, 0, 2, 0])}
    for char, paths in SHAPES.items():
        program = bytearray(b"\0")
        x = y = 0

        def move(point):
            nonlocal x, y
            a, b = point
            program.extend([8, (a - x) % 256, (b - y) % 256])
            x, y = a, b

        for stroke in paths:
            program.append(2)
            move(stroke[0])
            program.append(1)
            for point in stroke[1:]:
                move(point)
        program.append(2)
        move((120, 0))
        program.append(0)
        records[int.from_bytes(char.encode("gbk"), "big")] = bytes(program)
    header = b"AutoCAD-86 bigfont 1.0\r\n\x1a" + struct.pack(
        "<HHHHH", 8, len(records), 1, 0xA1, 0xF7
    )
    offset = len(header) + 8 * len(records)
    index = bytearray()
    body = bytearray()
    for code, record in records.items():
        index.extend(struct.pack("<HHI", code, len(record), offset))
        body.extend(record)
        offset += len(record)
    path.write_bytes(header + index + body)
    return path


def stroke_dxf(path, rows=2):
    doc = ezdxf.new("R2018")
    doc.appids.new("PDF2DXF15")
    for row in range(rows):
        seq = row * 100
        for column, char in enumerate(CHARS):
            previous = None
            for stroke in SHAPES[char]:
                points = [
                    (x * 0.035 + column * 4.2, y * 0.07 + row * 12) for x, y in stroke
                ]
                if previous is None or stroke[0] != previous:
                    points[0] = (points[0][0] + 0.008, points[0][1] - 0.006)
                previous = stroke[-1]
                entity = doc.modelspace().add_lwpolyline(points)
                entity.set_xdata(
                    "PDF2DXF15", [(1000, "stroke"), (1070, 0), (1070, seq), (1000, "s")]
                )
                seq += 1
    doc.saveas(path)
    return path


def test_shx_strokes_recover_from_dxf_without_font_access(tmp_path):
    from pdf2dxf_stable.engine.text.shx_font import build_shx_vector_catalog

    catalog = tmp_path / "font.p2dvec"
    font = font_file(tmp_path / "font.shx")
    build_shx_vector_catalog(font, catalog, encoding="gbk")
    font.unlink()
    dxf = stroke_dxf(tmp_path / "strokes.dxf")
    before = ezdxf.readfile(dxf)
    report = recover_outline_text(
        dxf, mode="required", policy="keep", font_catalog_paths=[catalog]
    )
    json.dumps(report)
    assert [r["text"] for r in report["accepted"]] == [CHARS, CHARS]
    after = ezdxf.readfile(dxf)
    assert len(after.modelspace().query("LWPOLYLINE")) == len(
        before.modelspace().query("LWPOLYLINE")
    )
    assert not after.audit().errors
    assert (
        recover_outline_text(dxf, mode="required", font_catalog_paths=[catalog])[
            "emitted_text_entities"
        ]
        == 0
    )


def test_lone_stroke_row_cannot_lock_font(tmp_path):
    from pdf2dxf_stable.engine.text.shx_font import build_shx_vector_catalog

    catalog = tmp_path / "font.p2dvec"
    build_shx_vector_catalog(font_file(tmp_path / "font.shx"), catalog, encoding="gbk")
    report = recover_outline_text(
        stroke_dxf(tmp_path / "one.dxf", 1),
        mode="required",
        font_catalog_paths=[catalog],
    )
    assert report["emitted_text_entities"] == 0


def test_shx_requires_explicit_encoding(tmp_path):
    from pdf2dxf_stable.engine.text.shx_font import build_shx_vector_catalog

    with pytest.raises(ValueError, match="encoding"):
        build_shx_vector_catalog(
            font_file(tmp_path / "font.shx"), tmp_path / "font.p2dvec", encoding=None
        )


def test_shx_source_pdf_runs_through_public_converter(tmp_path):
    import fitz
    from pdf2dxf_stable import Converter, ConversionRequest
    from pdf2dxf_stable.engine.text.shx_font import build_shx_vector_catalog

    catalog = tmp_path / "stroke.p2dvec"
    font = font_file(tmp_path / "stroke.shx")
    build_shx_vector_catalog(font, catalog, encoding="gbk")
    font.unlink()
    source = tmp_path / "stroke.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page(width=200, height=150)
        for row in range(2):
            for i, char in enumerate(CHARS):
                for path in SHAPES[char]:
                    points = [
                        (20 + i * 18 + x * 0.15, 30 + row * 40 + (100 - y) * 0.3)
                        for x, y in path
                    ]
                    page.draw_polyline(
                        points, color=(0, 0, 0), width=0.1, closePath=False
                    )
        assert not page.get_texttrace()
        pdf.save(source)
    output = tmp_path / "output.dxf"
    result = Converter().convert(
        source,
        output,
        ConversionRequest(
            mode="sheet",
            scale_mode="page",
            outline_chinese="required",
            outline_font_catalogs=[str(catalog)],
            recover_pure_path_text=False,
            timeout_seconds=90,
        ),
    )
    assert result.status != "failed", result.to_dict()
    doc = ezdxf.readfile(output)
    texts = [e.dxf.text for block in doc.blocks for e in block if e.dxftype() == "TEXT"]
    assert texts == [CHARS, CHARS], result.to_dict()
    assert doc.layers.get("PDF_OUTLINE_BACKUP").is_off()
    assert not doc.audit().errors


def test_zero_length_pen_up_is_not_a_missing_stroke(tmp_path, monkeypatch):
    from pdf2dxf_stable.engine.text.shx_font import build_shx_vector_catalog

    shapes = [*SHAPES["木"]]
    shapes[:1] = [[(10, 70), (50, 70)], [(50, 70), (90, 70)]]
    monkeypatch.setitem(SHAPES, "木", shapes)
    catalog = tmp_path / "joined.p2dvec"
    build_shx_vector_catalog(
        font_file(tmp_path / "joined.shx"), catalog, encoding="gbk"
    )
    report = recover_outline_text(
        stroke_dxf(tmp_path / "joined.dxf"),
        mode="required",
        font_catalog_paths=[catalog],
    )
    assert [r["text"] for r in report["accepted"]] == [CHARS, CHARS]


def test_real_gap_is_never_bridged_in_template_geometry():
    import numpy as np
    from shapely.geometry import MultiLineString
    from pdf2dxf_stable.engine.text.vector_catalog import _join_stroke_paths

    paths = [np.array([(0, 0), (1, 1)]), np.array([(1.000001, 1), (2, 0)])]
    joined = _join_stroke_paths(paths)
    assert len(joined) == 2
    assert MultiLineString(joined).equals(MultiLineString(paths))


@pytest.mark.parametrize(
    "reverse_first,reverse_second",
    [(False, False), (True, False), (False, True), (True, True)],
)
def test_exact_pen_joint_ignores_drawing_direction(reverse_first, reverse_second):
    import numpy as np
    from shapely.geometry import MultiLineString
    from pdf2dxf_stable.engine.text.vector_catalog import _join_stroke_paths

    a = np.array([(0, 0), (1, 2), (2, 2)])
    b = np.array([(2, 2), (3, 1)])
    paths = [a[::-1] if reverse_first else a, b[::-1] if reverse_second else b]
    joined = _join_stroke_paths(paths)
    assert len(joined) == 1
    assert len(joined[0]) == 4
    assert MultiLineString(joined).equals(MultiLineString(paths))


def test_rc42_stroke_catalog_accepts_reversed_join_without_rebuild(
    tmp_path, monkeypatch
):
    import numpy as np
    import zipfile
    from pdf2dxf_stable.engine.text import shx_font

    def old_join(paths):
        result = []
        for path in paths:
            if result and np.array_equal(result[-1][-1], path[0]):
                result[-1] = np.vstack((result[-1], path[1:]))
            else:
                result.append(np.asarray(path))
        return tuple(result)

    original = SHAPES["木"]
    split = [[(10, 70), (50, 70)], [(90, 70), (50, 70)], *original[1:]]
    monkeypatch.setitem(SHAPES, "木", split)
    catalog = tmp_path / "legacy.p2dvec"
    with monkeypatch.context() as legacy:
        legacy.setattr(shx_font, "_join_stroke_paths", old_join)
        shx_font.build_shx_vector_catalog(
            font_file(tmp_path / "legacy.shx"), catalog, encoding="gbk"
        )
    with zipfile.ZipFile(catalog) as z:
        payloads = {name: z.read(name) for name in z.namelist()}
    manifest = json.loads(payloads["manifest.json"])
    manifest["font"]["path_join_policy"] = "exact_sequential_endpoint_v1"
    payloads["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(catalog, "w") as z:
        for name, data in payloads.items():
            z.writestr(name, data)
    monkeypatch.setitem(SHAPES, "木", original)
    dxf = stroke_dxf(tmp_path / "merged.dxf")
    report = recover_outline_text(dxf, mode="required", font_catalog_paths=[catalog])
    assert [row["text"] for row in report["accepted"]] == [CHARS, CHARS]


@pytest.mark.parametrize(
    "case",
    ["valid", "baseline", "width", "missing_paint", "wrong_layer", "no_font_lock"],
)
def test_single_han_needs_local_row_geometry_and_complete_separator(tmp_path, case):
    from pdf2dxf_stable.engine.text.shx_font import build_shx_vector_catalog

    catalog = tmp_path / "font.p2dvec"
    build_shx_vector_catalog(font_file(tmp_path / "font.shx"), catalog, encoding="gbk")
    path = stroke_dxf(tmp_path / "single.dxf", rows=1 if case == "no_font_lock" else 2)
    doc = ezdxf.readfile(path)
    if case != "missing_paint":
        if case == "wrong_layer":
            doc.layers.new("OTHER")
        separator = doc.modelspace().add_lwpolyline(
            [(21.5, 0.6), (21.7, 0.8)],
            dxfattribs={"layer": "OTHER" if case == "wrong_layer" else "0"},
        )
        separator.set_xdata(
            "PDF2DXF15", [(1000, "stroke"), (1070, 0), (1070, 19), (1000, "s")]
        )
    for seq, stroke in enumerate(SHAPES["木"], 20):
        points = [
            (
                25.0 + x * (0.05 if case == "width" else 0.035),
                y * 0.07 + (3 if case == "baseline" else 0),
            )
            for x, y in stroke
        ]
        entity = doc.modelspace().add_lwpolyline(points)
        entity.set_xdata(
            "PDF2DXF15", [(1000, "stroke"), (1070, 0), (1070, seq), (1000, "s")]
        )
    doc.saveas(path)
    report = recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    texts = [row["text"] for row in report["accepted"]]
    assert texts == (
        [CHARS, CHARS, "木"]
        if case == "valid"
        else []
        if case == "no_font_lock"
        else [CHARS, CHARS]
    )
    if case == "valid":
        assert report["font_stroke_anchored_single_glyphs"] == 1
        assert report["accepted"][-1]["font_vector_admissions"] == [
            "shx_stroke_row_anchor_consensus"
        ]


def test_alias_unicode_cannot_be_chosen_from_stroke_shape(tmp_path, monkeypatch):
    from pdf2dxf_stable.engine.text.shx_font import build_shx_vector_catalog

    monkeypatch.setitem(SHAPES, "玉", SHAPES["王"])
    catalog = tmp_path / "alias.p2dvec"
    build_shx_vector_catalog(font_file(tmp_path / "alias.shx"), catalog, encoding="gbk")
    report = recover_outline_text(
        stroke_dxf(tmp_path / "alias.dxf"),
        mode="required",
        font_catalog_paths=[catalog],
    )
    assert report["font_vector_ambiguous_glyphs"] >= 2
    assert report["emitted_text_entities"] == 0


def test_several_short_stroke_rows_cannot_bootstrap(tmp_path, monkeypatch):
    from pdf2dxf_stable.engine.text.shx_font import build_shx_vector_catalog

    monkeypatch.setitem(globals(), "CHARS", "工木")
    catalog = tmp_path / "short.p2dvec"
    build_shx_vector_catalog(font_file(tmp_path / "short.shx"), catalog, encoding="gbk")
    report = recover_outline_text(
        stroke_dxf(tmp_path / "short.dxf", rows=4),
        mode="required",
        font_catalog_paths=[catalog],
    )
    assert report["emitted_text_entities"] == 0


@pytest.mark.parametrize("bad_offset", [0, 10000000])
def test_bigfont_rejects_out_of_bounds_records(tmp_path, bad_offset):
    from pdf2dxf_stable.engine.text.shx_font import Bigfont, SIGNATURE

    path = font_file(tmp_path / "broken.shx")
    data = bytearray(path.read_bytes())
    index = len(SIGNATURE) + 10
    struct.pack_into("<I", data, index + 4, bad_offset)
    with pytest.raises(ValueError, match="record"):
        Bigfont(bytes(data))


def test_shx_cli_requires_encoding_and_builds_resource(tmp_path, capsys):
    from pdf2dxf_stable.cli import main

    font = font_file(tmp_path / "cli.shx")
    out = tmp_path / "cli.p2dvec"
    assert (
        main(
            [
                "font-catalog",
                "build",
                str(font),
                "--vector",
                "--encoding",
                "gbk",
                "-o",
                str(out),
            ]
        )
        == 0
    )
    assert out.is_file()
    assert main(["font-catalog", "inspect", str(out)]) == 0
    assert "open_stroke_paths_v1" in capsys.readouterr().out


def test_bigfont_subshape_cycles_are_bounded():
    from pdf2dxf_stable.engine.text.shx_font import Bigfont, SIGNATURE

    records = [(0, b"Cycle\0" + bytes([128, 0, 2, 0])), (1, b"\0" + bytes([7, 1, 0]))]
    header = SIGNATURE + struct.pack("<HHHHH", 8, len(records), 1, 0xA1, 0xF7)
    offset = len(header) + 8 * len(records)
    index = bytearray()
    body = bytearray()
    for code, record in records:
        index.extend(struct.pack("<HHI", code, len(record), offset))
        body.extend(record)
        offset += len(record)
    font = Bigfont(header + index + body)
    with pytest.raises(ValueError, match="cyclic"):
        font.expand(1)


@pytest.mark.parametrize(
    "field,value", [("source_encoding", "utf-8"), ("max_source_paths", 0)]
)
def test_stroke_resource_contract_rejects_mislabelled_inputs(tmp_path, field, value):
    import zipfile
    from pdf2dxf_stable.engine.text.shx_font import build_shx_vector_catalog
    from pdf2dxf_stable.engine.text.vector_catalog import load_vector_font_catalog
    from pdf2dxf_stable.engine.text.font_catalog import FontCatalogError

    out = tmp_path / "contract.p2dvec"
    build_shx_vector_catalog(font_file(tmp_path / "contract.shx"), out, encoding="gbk")
    with zipfile.ZipFile(out) as z:
        payloads = {n: z.read(n) for n in z.namelist()}
    manifest = json.loads(payloads["manifest.json"])
    manifest["font"][field] = value
    payloads["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(out, "w") as z:
        for name, data in payloads.items():
            z.writestr(name, data)
    with pytest.raises(FontCatalogError):
        load_vector_font_catalog(out)


def test_short_stroke_grid_requires_independent_two_axis_vertices():
    import numpy as np
    from pdf2dxf_stable.engine.text.vector_text import _printer_grid

    pitch = 25.4 / 600
    points = (
        np.array([(0, 0), (1, 2), (3, 5), (4, 7), (7, 8), (8, 9), (9, 10), (11, 12)])
        * pitch
    )
    assert _printer_grid(points, paper_mm=True) == 0
    assert _printer_grid(points, paper_mm=True, minimum_vertices=8) == pitch
    repeated = np.repeat(points[:4], 3, axis=0)
    assert _printer_grid(repeated, paper_mm=True, minimum_vertices=8) == 0
    points[-1, 0] += 0.05 * pitch
    assert _printer_grid(points, paper_mm=True, minimum_vertices=8) == 0
