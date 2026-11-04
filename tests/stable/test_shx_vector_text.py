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


def font_file(path, *, above=128, below=0, divisor=1, family=b"Test stroke"):
    records = {0: family + b"\0" + bytes([above, below, 2, 0])}
    for char, paths in SHAPES.items():
        program = bytearray(b"\0")
        if divisor != 1:
            program.extend([3, divisor])
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
        if divisor != 1:
            program.extend([4, divisor])
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


@pytest.mark.parametrize("below", [0, 128])
def test_zero_above_bigfont_keeps_geometry_and_derives_numeric_scale(tmp_path, below):
    from pdf2dxf_stable.engine.text.shx_font import build_shx_vector_catalog, SIGNATURE
    from pdf2dxf_stable.engine.text.vector_catalog import load_vector_font_catalog

    font = font_file(tmp_path / "zero-above.shx")
    data = bytearray(font.read_bytes())
    index = len(SIGNATURE) + 10
    code, length, offset = struct.unpack_from("<HHI", data, index)
    assert code == 0
    start = data.index(0, offset) + 1
    data[start : start + 2] = bytes([0, below])
    font.write_bytes(data)
    catalog = tmp_path / "zero-above.p2dvec"
    if not below:
        with pytest.raises(ValueError, match="definition"):
            build_shx_vector_catalog(font, catalog, encoding="gbk")
        assert not catalog.exists()
        return
    build_shx_vector_catalog(font, catalog, encoding="gbk")
    numeric = load_vector_font_catalog(catalog)
    assert numeric.font["source_above"] == 0
    assert numeric.font["source_below"] == below
    assert numeric.font["height_policy"] == "full_han_median_ink_height_v1"
    assert numeric.font["units_per_em"] == 100
    partial = tmp_path / "partial.p2dvec"
    build_shx_vector_catalog(font, partial, encoding="gbk", codepoints=[ord("工")])
    assert load_vector_font_catalog(partial).font["units_per_em"] == 100
    font.unlink()
    report = recover_outline_text(stroke_dxf(tmp_path / "zero-above.dxf"), mode="required", font_catalog_paths=[catalog])
    assert [r["text"] for r in report["accepted"]] == [CHARS, CHARS]


@pytest.mark.parametrize("case", ["valid", "small_grid", "three", "duplicate", "spacing", "missing_branch", "no_grid", "alias", "simple"])
def test_complex_repeated_labels_need_four_independent_complete_locations(tmp_path, monkeypatch, case):
    import numpy as np
    from pdf2dxf_stable.engine.text.shx_font import build_shx_vector_catalog

    monkeypatch.setitem(SHAPES, "器", [
        [(10,100),(30,95)],[(40,90),(60,85)],[(70,80),(90,75)],
        [(10,65),(30,60)],[(40,55),(60,50)],[(70,45),(90,40)],
        [(10,30),(30,25)],[(40,20),(60,15)],[(70,10),(90,5)],
    ])
    monkeypatch.setitem(SHAPES, "玉", [*SHAPES["王"], [(60,40),(65,35)]])
    if case == "alias":
        monkeypatch.setitem(SHAPES, "品", SHAPES["器"])
    catalog = tmp_path / "labels.p2dvec"
    build_shx_vector_catalog(font_file(tmp_path / "labels.shx"), catalog, encoding="gbk")
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    doc.appids.new("PDF2DXF15")
    word = "玉本" if case == "simple" else "器本"
    pitch = 25.4 / 600
    expected = []
    for row in range(3 if case == "three" else 4):
        seq = row * 200
        for col, char in enumerate(word):
            points_all = []
            paths = SHAPES[char][:-1] if row == 3 and char == "器" and case == "missing_branch" else SHAPES[char]
            for path in paths:
                small = case == "small_grid"
                points = np.array(path) * ([0.0105,0.021] if small else [0.035,0.07]) + [col * (1.22 if small else 4.05) + (row * .013 if small else 0) + (0.8 if row == 3 and col and case == "spacing" else 0), 0 if case == "duplicate" and row == 3 else row * 12]
                if case != "no_grid":
                    points = np.rint(points / pitch) * pitch
                points_all.extend(points)
                e = doc.modelspace().add_lwpolyline(points)
                e.set_xdata("PDF2DXF15", [(1000,"stroke"),(1070,0),(1070,seq),(1000,"s")])
                seq += 1
            expected.append((char,tuple(np.min(points_all,axis=0))))
    path = tmp_path / "labels.dxf"
    doc.saveas(path)
    report = recover_outline_text(path, mode="required", policy="off_layer", font_catalog_paths=[catalog])
    assert report["font_vector_locked_catalogs"] == 0
    texts = [r["text"] for r in report["accepted"]]
    success = case in {"valid", "small_grid"}
    assert texts == (list(word) * 4 if success else [])
    assert report.get("font_stroke_repeated_label_glyph_matches",0) == (8 if success else 0)
    if success:
        evidence = report["font_stroke_repeated_label_evidence"]
        assert len(evidence) == 4 and all(len(r["supports"]) == 3 for r in evidence)
        assert all(limit <= .02 for row in report["accepted"] for limit in row["font_vector_boundary_error_limits"])
        actual = list(ezdxf.readfile(path).modelspace().query("TEXT"))
        assert len(actual) == len(expected)
        for entity,(char,xy) in zip(actual,expected):
            assert entity.dxf.text == char
            assert tuple(entity.dxf.insert)[:2] == pytest.approx(xy)


def test_zero_above_small_font_preserves_normalized_geometry(tmp_path):
    import numpy as np
    from pdf2dxf_stable.engine.text.shx_font import build_shx_vector_catalog
    from pdf2dxf_stable.engine.text.vector_catalog import load_vector_font_catalog

    normal = tmp_path / "normal.p2dvec"
    small = tmp_path / "small.p2dvec"
    build_shx_vector_catalog(font_file(tmp_path / "normal.shx"), normal, encoding="gbk")
    font = font_file(tmp_path / "small.shx", above=0, below=128, divisor=16, family="测试字库".encode("gbk"))
    build_shx_vector_catalog(font, small, encoding="gbk")
    actual = load_vector_font_catalog(small)
    assert actual.font["units_per_em"] == 7
    assert actual.font["family"] == "测试字库"
    np.testing.assert_array_equal(actual.arrays["points.npy"], load_vector_font_catalog(normal).arrays["points.npy"])


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


@pytest.mark.parametrize("partition", ["rerouted", "split"])
def test_crossing_strokes_recover_with_different_pdf_partitions(
    tmp_path, monkeypatch, partition
):
    from pdf2dxf_stable.engine.text.shx_font import build_shx_vector_catalog

    catalog = tmp_path / "font.p2dvec"
    build_shx_vector_catalog(font_file(tmp_path / "font.shx"), catalog, encoding="gbk")
    original = SHAPES["木"]
    if partition == "rerouted":
        paths = [
            [(10, 70), (50, 70), (50, 0)],
            [(50, 100), (50, 70), (90, 70)],
            *original[2:],
        ]
    else:
        paths = [[(10, 70), (50, 70)], original[1], [(50, 70), (90, 70)], *original[2:]]
    monkeypatch.setitem(SHAPES, "木", paths)
    dxf = stroke_dxf(tmp_path / "partitioned.dxf")
    report = recover_outline_text(dxf, mode="required", font_catalog_paths=[catalog])
    assert [row["text"] for row in report["accepted"]] == [CHARS, CHARS]
    doc = ezdxf.readfile(dxf)
    assert doc.layers.get("PDF_OUTLINE_BACKUP").is_off()
    assert not doc.audit().errors


def test_different_path_counts_cannot_hide_an_alias_unicode(tmp_path, monkeypatch):
    from pdf2dxf_stable.engine.text.shx_font import build_shx_vector_catalog

    paths = SHAPES["王"]
    monkeypatch.setitem(
        SHAPES,
        "玉",
        [paths[0], [(20, 55), (50, 55)], paths[2], [(50, 55), (80, 55)], paths[3]],
    )
    catalog = tmp_path / "alias.p2dvec"
    build_shx_vector_catalog(font_file(tmp_path / "alias.shx"), catalog, encoding="gbk")
    report = recover_outline_text(
        stroke_dxf(tmp_path / "alias.dxf"),
        mode="required",
        font_catalog_paths=[catalog],
    )
    assert report["font_vector_ambiguous_glyphs"] >= 2
    assert report["emitted_text_entities"] == 0


def test_shx_requires_explicit_encoding(tmp_path):
    from pdf2dxf_stable.engine.text.shx_font import build_shx_vector_catalog

    with pytest.raises(ValueError, match="encoding"):
        build_shx_vector_catalog(
            font_file(tmp_path / "font.shx"), tmp_path / "font.p2dvec", encoding=None
        )


def test_network_match_cannot_recover_a_missing_branch(tmp_path):
    import numpy as np
    from pdf2dxf_stable.engine.text.shx_font import build_shx_vector_catalog
    from pdf2dxf_stable.engine.text.vector_catalog import load_vector_font_catalog

    catalog = tmp_path / "font.p2dvec"
    build_shx_vector_catalog(font_file(tmp_path / "font.shx"), catalog, encoding="gbk")
    paths = [np.array(p, dtype=float) for p in SHAPES["木"][:-1]]
    result = load_vector_font_catalog(catalog).candidates(paths)
    assert result is not None and all(row[0] != "木" for row in result)


@pytest.mark.parametrize(
    "case", ["two", "one", "none", "duplicate", "missing_branch", "unseeded_pair"]
)
def test_repeat_proof_requires_independent_preconfirmed_glyphs(
    tmp_path, monkeypatch, case
):
    import numpy as np
    from pdf2dxf_stable.engine.text.shx_font import build_shx_vector_catalog

    wood = SHAPES["木"]
    loop = [(10, 105), (10, 125), (90, 125), (90, 105), (14, 105)]
    monkeypatch.setitem(SHAPES, "木", [loop, *wood])
    monkeypatch.setitem(
        SHAPES, "土", [[(20, 55), (80, 55)], [(50, 100), (50, 5)], [(10, 5), (90, 5)]]
    )
    catalog = tmp_path / "repeat.p2dvec"
    build_shx_vector_catalog(
        font_file(tmp_path / "repeat.shx"), catalog, encoding="gbk"
    )
    full, short = "工木本大王土", "工本大王土"
    words = [
        short if case in ("none", "unseeded_pair") else full,
        full if case in ("two", "duplicate", "missing_branch") else short,
        full,
    ]
    if case == "unseeded_pair":
        words.append(full)
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    doc.appids.new("PDF2DXF15")
    pitch = 25.4 / 600
    for row, word in enumerate(words):
        seq = row * 200
        y = 0 if case == "duplicate" and row == 1 else row * 12
        for col, char in enumerate(word):
            paths = SHAPES[char]
            if char == "木":
                paths = [
                    loop,
                    [(10, 70), (50, 70), (50, 0)],
                    [(50, 100), (50, 70), (90, 70)],
                    *wood[2:],
                ]
                if row >= 2 and case == "missing_branch":
                    paths = paths[:-1]
            for path in paths:
                points = np.array(path) * [0.035, 0.07] + [
                    col * 4.2 + (0.01 if row >= 2 and char == "木" else 0),
                    y,
                ]
                if char == "木":
                    points = np.rint(points / pitch) * pitch
                entity = doc.modelspace().add_lwpolyline(points)
                entity.set_xdata(
                    "PDF2DXF15", [(1000, "stroke"), (1070, 0), (1070, seq), (1000, "s")]
                )
                seq += 1
    path = tmp_path / "repeat.dxf"
    doc.saveas(path)
    report = recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    target = [r["text"] for r in report["accepted"] if r["bbox_dxf"][1] >= 23]
    assert (full in target) is (case == "two")
    assert report.get("font_stroke_repeat_glyph_matches", 0) == (
        1 if case == "two" else 0
    )


@pytest.mark.parametrize(
    "paths,signature",
    [
        ([[(0, 0), (1, 0)], [(0, 1), (1, 1)]], (0, 0)),
        ([[(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]], (1,)),
        ([[(0, 0.5), (1, 0.5)], [(0.5, 0), (0.5, 1)]], (0,)),
    ],
)
def test_network_envelope_retains_components_and_holes(paths, signature):
    from shapely.geometry import MultiLineString
    from pdf2dxf_stable.engine.text.vector_catalog import _stroke_network_topology

    assert (
        _stroke_network_topology(MultiLineString(paths).buffer(0.01, quad_segs=8))
        == signature
    )


@pytest.mark.parametrize("case", ["uniform", "uneven", "baseline", "short", "unlocked"])
def test_measured_character_spacing_needs_a_locked_font_and_four_labels(tmp_path, case):
    import numpy as np
    from pdf2dxf_stable.engine.text.shx_font import build_shx_vector_catalog

    catalog = tmp_path / "spacing.p2dvec"
    build_shx_vector_catalog(
        font_file(tmp_path / "spacing.shx"), catalog, encoding="gbk"
    )
    path = stroke_dxf(tmp_path / "spacing.dxf", rows=1 if case == "unlocked" else 2)
    doc = ezdxf.readfile(path)
    word = CHARS[:3] if case == "short" else CHARS[:4]
    seq = 200
    for col, char in enumerate(word):
        for stroke in SHAPES[char]:
            points = np.array(stroke) * [0.035, 0.07] + [
                col * 6.2 + (0.7 if case == "uneven" and col >= 2 else 0),
                24 + (0.8 if case == "baseline" and col == 1 else 0),
            ]
            entity = doc.modelspace().add_lwpolyline(points)
            entity.set_xdata(
                "PDF2DXF15", [(1000, "stroke"), (1070, 0), (1070, seq), (1000, "s")]
            )
            seq += 1
    doc.saveas(path)
    report = recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    rows = [r for r in report["accepted"] if r["bbox_dxf"][1] >= 23]
    assert [r["text"] for r in rows] == (list(word) if case == "uniform" else [])
    if case == "uniform":
        assert report["font_stroke_spaced_row_evidence"][0]["text"] == word
        assert report["font_stroke_spaced_row_evidence"][0][
            "tracking_dxf_units"
        ] == pytest.approx(2)
        assert all(
            r["font_vector_admissions"] == ["shx_stroke_spaced_row_consensus"]
            for r in rows
        )
        saved = ezdxf.readfile(path)
        for row in rows:
            texts = [
                e for e in saved.modelspace().query("TEXT") if e.dxf.text == row["text"]
            ]
            assert any(
                np.allclose(tuple(e.dxf.insert)[:2], row["bbox_dxf"][:2]) for e in texts
            )


@pytest.mark.parametrize("repartition", [False, True])
def test_shx_source_pdf_runs_through_public_converter(tmp_path, repartition):
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
                paths = SHAPES[char]
                if repartition and char == "木":
                    paths = [
                        [(10, 70), (50, 70), (50, 0)],
                        [(50, 100), (50, 70), (90, 70)],
                        *paths[2:],
                    ]
                for path in paths:
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


@pytest.mark.parametrize(
    "case",
    ["valid", "late_matching_refs", "one_reference", "unseeded_pair", "duplicate_location", "missing_branch", "no_grid", "mixed_layers", "other_page", "no_font_lock", "unicode_alias"],
)
def test_isolated_han_requires_two_independent_preconfirmed_glyphs(
    tmp_path, monkeypatch, case
):
    import numpy as np
    from pdf2dxf_stable.engine.text.shx_font import build_shx_vector_catalog

    monkeypatch.setitem(
        SHAPES, "土", [[(20, 55), (80, 55)], [(50, 100), (50, 5)], [(10, 5), (90, 5)]]
    )
    if case == "unicode_alias":
        monkeypatch.setitem(SHAPES, "玉", SHAPES["本"])
    catalog = tmp_path / "isolated.p2dvec"
    font = font_file(tmp_path / "isolated.shx")
    build_shx_vector_catalog(font, catalog, encoding="gbk")
    font.unlink()
    full, short = CHARS + "土", "工木大王土"
    words = [full, short if case == "one_reference" else full]
    if case == "unseeded_pair":
        words = [short, short]
    elif case == "no_font_lock":
        words = [full + "本"]
    elif case == "unicode_alias":
        words = [short, short, full, full]
    elif case == "late_matching_refs":
        words = [full] * 10
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    doc.appids.new("PDF2DXF15")
    doc.layers.new("LABELS")
    doc.layers.new("OTHER")
    pitch = 25.4 / 600

    def draw(char, origin, scale, seq, layer="0", page=0, target=False, repartition=False):
        paths = SHAPES[char][:-1] if target and case == "missing_branch" else SHAPES[char]
        if char == "本" and repartition:
            paths = [
                [(10, 70), (50, 70), (50, 0)],
                [(50, 100), (50, 70), (90, 70)],
                *SHAPES[char][2:],
            ]
        bounds = []
        for i, path in enumerate(paths):
            points = np.array(path) * scale + origin
            if char == "本" and not (target and case == "no_grid"):
                points = np.rint(points / pitch) * pitch
            bounds.extend(points)
            entity = doc.modelspace().add_lwpolyline(
                points, dxfattribs={"layer": "OTHER" if target and case == "mixed_layers" and i == 1 else layer}
            )
            entity.set_xdata(
                "PDF2DXF15", [(1000, "stroke"), (1070, page), (1070, seq + i), (1000, "s")]
            )
        return np.min(bounds, axis=0)

    for row, word in enumerate(words):
        seq = row * 200
        y = 0 if case == "duplicate_location" else row * 12
        early = case == "late_matching_refs" and row < 8
        for col, char in enumerate(word):
            draw(char, [col * (5.88 if early else 4.2), y], [0.049, 0.098] if early else [0.035, 0.07], seq, repartition=early)
            seq += len(SHAPES[char])
    expected = draw("本", [35, 160 if case == "late_matching_refs" else 45], [0.0245, 0.049], 10000, "LABELS", int(case == "other_page"), True)
    if case == "unseeded_pair":
        draw("本", [45, 45], [0.0245, 0.049], 11000, "LABELS", target=True)
    path = tmp_path / "isolated.dxf"
    doc.saveas(path)
    report = recover_outline_text(path, mode="required", policy="off_layer", font_catalog_paths=[catalog])
    targets = [r for r in report["accepted"] if r["source_seqnos"][0] >= 10000]
    success = case in {"valid", "late_matching_refs"}
    assert [r["text"] for r in targets] == (["本"] if success else [])
    assert report.get("font_stroke_isolated_glyph_matches", 0) == int(success)
    if success:
        proof = report["font_stroke_isolated_evidence"][0]
        assert len(proof["supports"][0]["reference_source_spans"]) == 2
        assert proof["grid_pitch"] == pytest.approx(pitch)
        assert targets[0]["font_vector_admissions"] == ["shx_stroke_isolated_repeat_consensus"]
        reopened = ezdxf.readfile(path)
        texts = list(reopened.modelspace().query("TEXT"))
        target, = [e for e in texts if e.dxf.text == "本"]
        assert tuple(target.dxf.insert)[:2] == pytest.approx(expected)
        assert target.dxf.layer == "PDF_TEXT_RECOVERED_NOOCR"
        assert reopened.layers.get("PDF_OUTLINE_BACKUP").is_off()
        assert not reopened.audit().errors


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


@pytest.mark.parametrize(
    "case",
    [
        90,
        180,
        270,
        "one_reference",
        "no_lock",
        "no_grid",
        "other_page",
        "missing_branch",
        "mirror",
        "wrong_layer",
        "incomplete_source",
        "unicode_alias",
        "duplicate_location",
        "spacing",
    ],
)
def test_rotated_han_keep_angle_and_require_preconfirmed_geometry(
    tmp_path, monkeypatch, case
):
    import numpy as np
    from pdf2dxf_stable.engine.text.shx_font import build_shx_vector_catalog

    monkeypatch.setitem(SHAPES, "木", [[(10, 70), (30, 70), (90, 70)], *SHAPES["木"][1:]])
    monkeypatch.setitem(
        SHAPES,
        "器",
        [
            [(5, 95), (35, 95)],
            [(5, 95), (5, 70)],
            [(35, 95), (35, 70)],
            [(5, 70), (35, 70)],
            [(65, 95), (95, 95)],
            [(65, 95), (65, 70)],
            [(95, 95), (95, 70)],
            [(65, 70), (95, 70)],
            [(10, 15), (40, 15)],
            [(70, 15), (100, 15)],
            [(10, 40), (40, 40)],
            [(5, 5), (20, 5)],
            [(35, 5), (50, 5)],
            [(65, 5), (80, 5)],
        ],
    )
    if case == "unicode_alias":
        monkeypatch.setitem(SHAPES, "品", SHAPES["器"])
    catalog = tmp_path / "rotation.p2dvec"
    build_shx_vector_catalog(
        font_file(tmp_path / "rotation.shx"), catalog, encoding="gbk"
    )
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    doc.appids.new("PDF2DXF15")
    doc.layers.new("OTHER")
    pitch = 25.4 / 600
    angle = case if isinstance(case, int) else 90
    matrices = {
        90: np.array([[0, -1], [1, 0]]),
        180: -np.eye(2),
        270: np.array([[0, 1], [-1, 0]]),
    }
    target_handles = []
    for row, word in enumerate(
        [CHARS + "器", CHARS + ("" if case == "one_reference" else "器"), "器木本"]
    ):
        if case == "no_lock" and row == 1:
            continue
        seq = row * 1000
        for col, char in enumerate(word):
            for part, stroke in enumerate(SHAPES[char]):
                if row == 2 and char == "器" and case == "missing_branch" and part == 0:
                    seq += 1
                    continue
                y = 0 if row == 1 and case == "duplicate_location" else 12 * row
                points = np.array(stroke) * [0.035, 0.07] + [4.2 * col, y]
                points = np.rint(points / pitch) * pitch
                if row == 2:
                    points = (points - [0, 12 * row]) @ matrices[angle].T + [60, 60]
                    if case == "mirror":
                        points[:, 0] = 120 - points[:, 0]
                    if case == "no_grid":
                        points[:, 0] += np.arange(len(points)) * 0.0011
                    if case == "spacing" and char == "木":
                        points[:, 0] += pitch * 10
                e = doc.modelspace().add_lwpolyline(
                    points,
                    dxfattribs={
                        "layer": "OTHER"
                        if row == 2 and case == "wrong_layer" and char == "木"
                        else "0"
                    },
                )
                e.set_xdata(
                    "PDF2DXF15",
                    [
                        (1000, "stroke"),
                        (1070, int(row == 2 and case == "other_page")),
                        (1070, seq),
                        (1000, "s"),
                    ],
                )
                if row == 2:
                    target_handles.append(e.dxf.handle)
                if (
                    row == 2
                    and case == "incomplete_source"
                    and char == "器"
                    and part == 0
                ):
                    missing = doc.modelspace().add_point((60, 60))
                    missing.set_xdata(
                        "PDF2DXF15",
                        [(1000, "stroke"), (1070, 0), (1070, seq), (1000, "s")],
                    )
                seq += 1
    path = tmp_path / "rotated.dxf"
    doc.saveas(path)
    before = {h: list(doc.entitydb[h].get_points()) for h in target_handles}
    report = recover_outline_text(
        path, mode="required", policy="off_layer", font_catalog_paths=[catalog]
    )
    targets = [r for r in report["accepted"] if min(r["source_seqnos"]) >= 2000]
    success = isinstance(case, int)
    assert [r["text"] for r in targets] == (list("器木本") if success else [])
    assert report.get("font_stroke_rotated_glyph_matches", 0) == (3 if success else 0)
    if success:
        assert all(r["rotation"] == angle for r in targets)
        assert len(report["font_stroke_rotated_row_evidence"]) == 1
        reopened = ezdxf.readfile(path)
        for h, points in before.items():
            assert list(reopened.entitydb[h].get_points()) == points
        texts = [
            e for e in reopened.modelspace().query("TEXT") if e.dxf.rotation == angle
        ]
        assert [e.dxf.text for e in texts] == list("器木本")
        for e in texts:
            delta = np.array(e.dxf.align_point)[:2] - np.array(e.dxf.insert)[:2]
            assert delta @ matrices[angle][:, 0] > 0
            assert abs(delta @ matrices[angle][:, 1]) < 1e-9
        assert not reopened.audit().errors
        assert (
            recover_outline_text(path, mode="required", font_catalog_paths=[catalog])[
                "emitted_text_entities"
            ]
            == 0
        )


@pytest.mark.parametrize(
    "case",
    [
        "valid",
        "reference_scaled",
        "missing_branch",
        "outside_font_budget",
        "one_reference",
        "duplicate_reference",
        "unicode_alias",
    ],
)
def test_independent_print_errors_propagate_without_expanding_font_budget(
    tmp_path, monkeypatch, case
):
    import numpy as np
    from pdf2dxf_stable.engine.text.shx_font import build_shx_vector_catalog

    monkeypatch.setitem(
        SHAPES, "土", [[(20, 55), (80, 55)], [(50, 100), (50, 5)], [(10, 5), (90, 5)]]
    )
    if case == "unicode_alias":
        monkeypatch.setitem(SHAPES, "玉", SHAPES["本"])
    catalog = tmp_path / "independent-errors.p2dvec"
    build_shx_vector_catalog(
        font_file(tmp_path / "independent-errors.shx"), catalog, encoding="gbk"
    )
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    doc.appids.new("PDF2DXF15")
    doc.layers.new("TARGET")
    pitch = 25.4 / 600
    words = [CHARS + "土", "工木大王土" if case == "one_reference" else CHARS + "土"]

    def draw(char, origin, xscale, seq, target=False):
        paths = SHAPES[char]
        if target and case == "missing_branch":
            paths = paths[:-1]
        for part, path in enumerate(paths):
            points = np.array(path) * [xscale, pitch] + origin
            if char == "本" and part == len(SHAPES["本"]) - 1:
                points[:, 1] += pitch * (
                    (-3 if case == "outside_font_budget" else -1) if target else 1
                )
            points = np.rint(points / pitch) * pitch
            entity = doc.modelspace().add_lwpolyline(
                points, dxfattribs={"layer": "TARGET" if target else "0"}
            )
            entity.set_xdata(
                "PDF2DXF15",
                [(1000, "stroke"), (1070, 0), (1070, seq + part), (1000, "s")],
            )

    sx = pitch / (4 if case == "reference_scaled" else 2)
    for row, word in enumerate(words):
        seq = 200 * row
        y = 0 if case == "duplicate_reference" else row * 140 * pitch
        for col, char in enumerate(word):
            draw(char, np.array([col * 120 * sx, y]), sx, seq)
            seq += len(SHAPES[char])
    draw("本", np.array([900 * pitch, 500 * pitch]), pitch / 2, 10000, True)
    path = tmp_path / "independent-errors.dxf"
    doc.saveas(path)
    report = recover_outline_text(
        path, mode="required", policy="off_layer", font_catalog_paths=[catalog]
    )
    targets = [r for r in report["accepted"] if min(r["source_seqnos"]) >= 10000]
    success = case in {"valid", "reference_scaled"}
    assert [r["text"] for r in targets] == (["本"] if success else [])
    if success:
        (evidence,) = report["font_stroke_isolated_evidence"]
        (support,) = evidence["supports"]
        assert len(support["reference_source_spans"]) == 2
        (cap,) = targets[0]["font_vector_boundary_error_limits"]
        assert cap < 0.02
        assert targets[0]["font_vector_boundary_errors"][0] <= cap
        # Two opposite one-pixel internal-stroke errors are 2/100 ink heights;
        # each single-font comparison still uses its original smaller bound.
        assert cap < 2 / 100 < min(support["glyph_pair_error_limits"])
        assert max(support["reference_font_error_limits"]) <= 0.02
        assert not ezdxf.readfile(path).audit().errors


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


@pytest.mark.parametrize(
    'case',
    [90, 180, 270, 'pair', 'one_reference', 'duplicate_reference', 'other_page',
     'missing_branch', 'incomplete_source', 'no_grid', 'unicode_alias', 'rotated_alias',
     'attached_fragment', 'bad_spacing'],
)
def test_rotated_short_labels_need_independent_glyph_and_orientation_proofs(tmp_path, monkeypatch, case):
    import numpy as np
    from pdf2dxf_stable.engine.text.shx_font import build_shx_vector_catalog

    monkeypatch.setitem(SHAPES, "木", [[(10, 70), (30, 70), (90, 70)], *SHAPES["木"][1:]])
    complex_paths = [
        [(5, 95), (35, 95)], [(5, 95), (5, 70)], [(35, 95), (35, 70)],
        [(5, 70), (35, 70)], [(65, 95), (95, 95)], [(65, 95), (65, 70)],
        [(95, 95), (95, 70)], [(65, 70), (95, 70)],
        [(10, 15), (40, 15)], [(70, 15), (100, 15)],
        [(10, 40), (40, 40)], [(5, 5), (20, 5)],
        [(35, 5), (50, 5)], [(65, 5), (80, 5)],
    ]
    monkeypatch.setitem(SHAPES, '器', complex_paths)
    if case == 'unicode_alias':
        monkeypatch.setitem(SHAPES, '品', complex_paths)
    elif case == 'rotated_alias':
        # A competing Unicode label exists only in a different orientation;
        # it need not occur in a reference row to prevent an isolated decision.
        monkeypatch.setitem(SHAPES, '品', [[(y, 105 - x) for x, y in p] for p in complex_paths])
    catalog = tmp_path / 'short-rotation.p2dvec'
    build_shx_vector_catalog(font_file(tmp_path / 'short-rotation.shx'), catalog, encoding='gbk')
    doc = ezdxf.new('R2018')
    doc.header['$INSUNITS'] = 4
    doc.appids.new('PDF2DXF15')
    pitch = 25.4 / 600
    angle = case if isinstance(case, int) else 90
    matrix = {90: np.array([[0, -1], [1, 0]]), 180: -np.eye(2), 270: np.array([[0, 1], [-1, 0]])}[angle]
    target_handles = []
    words = [CHARS + '器', CHARS + ('' if case == 'one_reference' else '器')]
    words.append('器木' if case in {'pair', 'bad_spacing'} else '器')
    for row, word in enumerate(words):
        seq = row * 1000
        for column, char in enumerate(word):
            for part, stroke in enumerate(SHAPES[char]):
                if row == 2 and case == 'missing_branch' and part == 0:
                    seq += 1
                    continue
                y = 0 if row == 1 and case == 'duplicate_reference' else row * 12
                points = np.rint((np.array(stroke) * [0.035, 0.07] + [column * 4.2, y]) / pitch) * pitch
                if row == 2:
                    points = (points - [0, y]) @ matrix.T + [60, 60]
                    if case == 'no_grid':
                        points[:, 0] += np.arange(len(points)) * 0.0011
                    if case == 'bad_spacing' and char == '木':
                        points[:, 0] += 10 * pitch
                entity = doc.modelspace().add_lwpolyline(points)
                entity.set_xdata('PDF2DXF15', [(1000, 'stroke'), (1070, int(row == 2 and case == 'other_page')), (1070, seq), (1000, 's')])
                if row == 2:
                    target_handles.append(entity.dxf.handle)
                    if case == 'incomplete_source' and part == 0:
                        missing = doc.modelspace().add_point((60, 60))
                        missing.set_xdata('PDF2DXF15', [(1000, 'stroke'), (1070, 0), (1070, seq), (1000, 's')])
                seq += 1
        if row == 2 and case == 'attached_fragment':
            fragment = doc.modelspace().add_line((57, 61), (57, 62))
            fragment.set_xdata('PDF2DXF15', [(1000, 'stroke'), (1070, 0), (1070, seq), (1000, 's')])
    path = tmp_path / 'short-rotation.dxf'
    doc.saveas(path)
    before = {h: list(doc.entitydb[h].get_points()) for h in target_handles}
    report = recover_outline_text(path, mode='required', policy='off_layer', font_catalog_paths=[catalog])
    targets = [r for r in report['accepted'] if min(r['source_seqnos']) >= 2000]
    expected = list(words[-1]) if isinstance(case, int) or case == 'pair' else []
    assert [r['text'] for r in targets] == expected
    assert all(r['rotation'] == angle for r in targets)
    if expected:
        reopened = ezdxf.readfile(path)
        assert [e.dxf.text for e in reopened.modelspace().query('TEXT') if e.dxf.rotation == angle] == expected
        for h, points in before.items():
            assert list(reopened.entitydb[h].get_points()) == points
        assert not reopened.audit().errors
        assert reopened.layers.get('PDF_OUTLINE_BACKUP').is_off()
        assert recover_outline_text(path, mode='required', font_catalog_paths=[catalog])['emitted_text_entities'] == 0


def test_short_orientation_rejects_topology_deferred_unicode_rival(tmp_path, monkeypatch):
    import numpy as np
    from pdf2dxf_stable.engine.text.outline_text import _collect_atoms
    from pdf2dxf_stable.engine.text.shx_font import build_shx_vector_catalog
    from pdf2dxf_stable.engine.text.stroke_rotation import _unique_orientation
    from pdf2dxf_stable.engine.text.vector_catalog import load_vector_font_catalog
    from pdf2dxf_stable.engine.text.vector_text import _candidate_group

    wood = SHAPES['木']
    loop = [(10, 105), (10, 125), (90, 125), (90, 105), (14, 105)]
    monkeypatch.setitem(SHAPES, '木', [loop, *wood])
    # Printer rounding closes the narrow loop envelope; crossing strokes were
    # repartitioned. 木 remains a complete, font-bounded deferred rival, while
    # the controlled second label has an exact per-path interpretation.
    target = [np.rint(np.array(p) * [0.78, 1]) for p in [
        loop, [(10, 70), (50, 70), (50, 0)],
        [(50, 100), (50, 70), (90, 70)], *wood[2:],
    ]]
    monkeypatch.setitem(SHAPES, '品', [p.astype(int).tolist() for p in target])
    resource = tmp_path / 'deferred-rival.p2dvec'
    font = font_file(tmp_path / 'deferred-rival.shx')
    build_shx_vector_catalog(font, resource, encoding='gbk')
    font.unlink()
    catalog = load_vector_font_catalog(resource)
    pitch = 25.4 / 600
    paths = [p * pitch for p in target]
    deferred = []
    strict = catalog.candidates(paths, max_error=np.sqrt(2) / 125 + 0.001, deferred=deferred)
    assert [r[0] for r in strict] == ['品']
    assert [r[0] for r in deferred] == ['木']
    doc = ezdxf.new('R2018')
    doc.appids.new('PDF2DXF15')
    for seq, points in enumerate(paths):
        e = doc.modelspace().add_lwpolyline(points)
        e.set_xdata('PDF2DXF15', [(1000, 'stroke'), (1070, 0), (1070, seq), (1000, 's')])
    path = tmp_path / 'deferred-rival.dxf'
    doc.saveas(path)
    atoms, _, _ = _collect_atoms(ezdxf.readfile(path), 0, include_fills=True)
    ordinary = _candidate_group(atoms, [catalog], {'font_vector_ambiguous_glyphs': 0}, paper_mm=True, deferred=[])
    assert ordinary is not None and ordinary[0].char == '品'
    assert not _unique_orientation(ordinary[0], 0, atoms, [catalog])
