"""Exact raw and fill glyph representations preserve stroke and fill PDF behavior."""

import ezdxf
import numpy as np
import pytest

from pdf2dxf_stable.engine.text import outline_text as o
from pdf2dxf_stable.engine.text.font_catalog import (
    build_font_catalog,
    extract_font_glyph_paths,
    load_font_catalog,
)
from test_font_catalog import SHAPES, _write_font, _write_outline_dxf


@pytest.mark.parametrize(
    "contour",
    [
        ((350, 78), (350, 77)),
        ((350, 78), (351, 78)),
        ((350, 78), (351, 79), (352, 80)),
        ((2000, 2000), (2100, 2100), (2200, 2200)),
    ],
)
def test_catalog_retains_raw_and_adds_closed_collinear_fill_variant(
    tmp_path, monkeypatch, contour
):
    font = _write_font(tmp_path / "clean.ttf")
    clean = tmp_path / "clean.p2dfont"
    build_font_catalog(font, clean)
    expected = load_font_catalog(clean).by_char["图"]
    monkeypatch.setitem(SHAPES, "图", (*SHAPES["图"], contour))
    font = _write_font(tmp_path / "degenerate.ttf")
    catalog = tmp_path / "degenerate.p2dfont"
    build_font_catalog(font, catalog)
    loaded = load_font_catalog(catalog)
    raw, filled = loaded.templates_by_label["图"]
    assert loaded.by_char["图"] == raw
    assert raw.entity_count == 4
    assert filled == expected
    # Source extraction remains an audit of the original font, including the line.
    assert len(extract_font_glyph_paths(font, "图")) == 4


@pytest.mark.parametrize(
    "contour",
    [
        # Non-collinear bow tie: zero signed area is not zero filled area.
        ((0, 0), (200, 200), (0, 200), (200, 0)),
        # Very small, but still a real triangle.
        ((350, 78), (351, 78), (350, 79)),
    ],
)
def test_catalog_preserves_noncollinear_contours(tmp_path, monkeypatch, contour):
    monkeypatch.setitem(SHAPES, "图", (*SHAPES["图"], contour))
    font = _write_font(tmp_path / "font.ttf")
    catalog = tmp_path / "font.p2dfont"
    build_font_catalog(font, catalog)
    actual = load_font_catalog(catalog).by_char["图"]
    assert actual.entity_count == actual.closed_count == 4
    signature = o._font_fingerprint_paths(extract_font_glyph_paths(font, "图"))
    assert o._font_signature_key(signature) in actual.match_keys


def test_collinear_only_mapping_does_not_become_a_dot_template(tmp_path, monkeypatch):
    monkeypatch.setitem(SHAPES, "图", (((0, 0), (1, 1), (2, 2)),))
    font = _write_font(tmp_path / "font.ttf")
    catalog = tmp_path / "font.p2dfont"
    report = build_font_catalog(font, catalog)
    loaded = load_font_catalog(catalog)
    assert len(loaded.templates_by_label["图"]) == 1
    assert loaded.by_char["图"].entity_count == 1
    assert any(row["codepoint"] == ord("图") for row in report["skipped_fill_variants"])
    assert report["skipped_mappings"] == []


@pytest.mark.parametrize("fill", [False, True])
def test_degenerate_font_contour_does_not_block_saved_dxf_text(
    tmp_path, monkeypatch, fill
):
    monkeypatch.setitem(SHAPES, "图", (*SHAPES["图"], ((350, 78), (350, 77))))
    font = _write_font(tmp_path / "font.ttf")
    catalog = tmp_path / "font.p2dfont"
    build_font_catalog(font, catalog)
    glyphs = {ch: extract_font_glyph_paths(font, ch) for ch in SHAPES}
    path = _write_outline_dxf(tmp_path / "input.dxf", glyphs, text="国文中图")
    if fill:
        doc = ezdxf.readfile(path)
        for entity in list(doc.modelspace()):
            points = list(entity.get_points("xy"))
            if np.ptp(np.array(points)[:, 0]) > 0:
                hatch = doc.modelspace().add_hatch(
                    dxfattribs={"layer": entity.dxf.layer}
                )
                hatch.paths.add_polyline_path(points, is_closed=True)
                hatch.set_xdata("PDF2DXF15", list(entity.get_xdata("PDF2DXF15")))
            doc.modelspace().delete_entity(entity)
        doc.saveas(path)
    font.unlink()
    original = {
        e.dxf.handle: [p.tolist() for p in o._entity_paths(e, include_fill=True)]
        for e in ezdxf.readfile(path).modelspace()
    }
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    after = ezdxf.readfile(path)
    assert (
        "".join(
            e.dxf.text
            for e in after.modelspace().query(f'TEXT[layer=="{o.TEXT_LAYER}"]')
        )
        == "国文中图"
    )
    assert report["font_catalogs"]["locked"] == 1
    for handle, paths in original.items():
        assert [
            p.tolist()
            for p in o._entity_paths(after.entitydb[handle], include_fill=True)
        ] == paths
    assert (
        o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])[
            "emitted_text_entities"
        ]
        == 0
    )


@pytest.mark.parametrize("policy", [None, "unknown-policy"])
def test_v2_catalog_requires_explicit_supported_policy(tmp_path, policy):
    import json
    import zipfile
    from pdf2dxf_stable.engine.text.font_catalog import FontCatalogError

    font = _write_font(tmp_path / "font.ttf")
    path = tmp_path / "font.p2dfont"
    build_font_catalog(font, path)
    assert load_font_catalog(path).outline_policy == "raw_and_noncollinear_fill_v1"
    with zipfile.ZipFile(path) as archive:
        payloads = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(payloads["manifest.json"])
    if policy is None:
        manifest.pop("outline_policy")
    else:
        manifest["outline_policy"] = policy
    payloads["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in payloads.items():
            archive.writestr(name, data)
    with pytest.raises(FontCatalogError, match="runtime contract"):
        load_font_catalog(path)


def test_removing_empty_contour_cannot_choose_between_two_labels(tmp_path, monkeypatch):
    main = SHAPES["中"]
    monkeypatch.setitem(SHAPES, "图", (*main, ((350, 78), (350, 77))))
    font = _write_font(tmp_path / "ambiguous.ttf")
    path = tmp_path / "ambiguous.p2dfont"
    build_font_catalog(font, path)
    catalog = load_font_catalog(path)
    signature = o._font_fingerprint_paths(extract_font_glyph_paths(font, "中"))
    assert set(
        catalog.matching_characters(
            o._font_signature_key(signature), signature.aspect_ratio
        )
    ) == {"中", "图"}
    glyphs = {ch: extract_font_glyph_paths(font, ch) for ch in SHAPES}
    drawing = _write_outline_dxf(tmp_path / "ambiguous.dxf", glyphs, text="国文中图")
    font.unlink()
    report = o.recover_outline_text(drawing, mode="required", font_catalog_paths=[path])
    assert report["font_ambiguous_geometry_matches"] >= 2
    assert (
        not ezdxf.readfile(drawing).modelspace().query(f'TEXT[layer=="{o.TEXT_LAYER}"]')
    )


@pytest.mark.parametrize("position", [0, 1, 3])
@pytest.mark.parametrize("fill", [False, True])
def test_large_empty_contour_preserves_both_exact_representations(
    tmp_path, monkeypatch, position, fill
):
    contours = list(SHAPES["图"])
    contours.insert(position, ((350, 78), (350, 278)))
    monkeypatch.setitem(SHAPES, "图", tuple(contours))
    font = _write_font(tmp_path / "font.ttf")
    catalog = tmp_path / "font.p2dfont"
    build_font_catalog(font, catalog)
    glyphs = {ch: extract_font_glyph_paths(font, ch) for ch in SHAPES}
    if fill:
        # A filled PDF does not paint this collinear path. Its DXF contains only
        # the three original noncollinear paths, with all their exact points.
        glyphs["图"] = tuple(p for i, p in enumerate(glyphs["图"]) if i != position)
    path = _write_outline_dxf(tmp_path / "drawing.dxf", glyphs, text="国文中图")
    original = {
        e.dxf.handle: list(e.get_points("xy"))
        for e in ezdxf.readfile(path).modelspace()
    }
    font.unlink()
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    doc = ezdxf.readfile(path)
    assert (
        "".join(
            e.dxf.text for e in doc.modelspace().query(f'TEXT[layer=="{o.TEXT_LAYER}"]')
        )
        == "国文中图"
    ), report
    for handle, points in original.items():
        assert list(doc.entitydb[handle].get_points("xy")) == points


def test_legacy_wire_catalog_keeps_original_identity_and_exact_templates(tmp_path):
    from test_font_catalog import _rewrite_legacy_catalog

    font = _write_font(tmp_path / "font.ttf")
    modern = tmp_path / "modern.p2dfont"
    legacy = tmp_path / "legacy.p2dfont"
    build_font_catalog(font, modern)
    _rewrite_legacy_catalog(modern, legacy)
    old, new = load_font_catalog(legacy), load_font_catalog(modern)
    assert old.schema == "pdf2dxf.font_glyph_catalog.v1"
    assert old.outline_policy == "raw_contours_v1"
    assert old.catalog_id != new.catalog_id
    assert old.templates == new.templates
    assert old.lookup == new.lookup


@pytest.mark.parametrize(
    "field,value",
    [
        ("mapped_codepoint_count", 99),
        ("mapped_codepoint_count", True),
        ("fill_variant_count", 0),
        ("fill_variant_count", True),
        ("representation_order", "fill_then_raw"),
    ],
)
def test_v2_loader_rejects_inconsistent_representation_metadata(
    tmp_path, monkeypatch, field, value
):
    import json
    import zipfile
    from pdf2dxf_stable.engine.text.font_catalog import FontCatalogError

    monkeypatch.setitem(SHAPES, "图", (*SHAPES["图"], ((350, 78), (350, 278))))
    font = _write_font(tmp_path / "font.ttf")
    path = tmp_path / "font.p2dfont"
    build_font_catalog(font, path)
    with zipfile.ZipFile(path) as archive:
        payloads = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(payloads["manifest.json"])
    manifest[field] = value
    payloads["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in payloads.items():
            archive.writestr(name, data)
    with pytest.raises(FontCatalogError, match="runtime contract|representations"):
        load_font_catalog(path)


@pytest.mark.parametrize("mutation", ["reverse", "third", "legacy_duplicates"])
def test_v2_loader_rejects_invalid_rows_even_with_valid_hashes(
    tmp_path, monkeypatch, mutation
):
    import hashlib
    import io
    import json
    import zipfile
    from pdf2dxf_stable.engine.text.font_catalog import (
        FontCatalogError,
        _dataset_digest,
    )

    monkeypatch.setitem(SHAPES, "图", (*SHAPES["图"], ((350, 78), (350, 278))))
    font = _write_font(tmp_path / "font.ttf")
    path = tmp_path / "font.p2dfont"
    build_font_catalog(font, path)
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        arrays = {
            name: np.load(io.BytesIO(archive.read(name)), allow_pickle=False)
            for name in manifest["arrays"]
        }
    cps = arrays["codepoints.npy"]
    first = int(np.flatnonzero(cps == ord("图"))[0])
    order = list(range(len(cps)))
    if mutation == "reverse":
        order[first], order[first + 1] = order[first + 1], order[first]
    elif mutation == "third":
        order.insert(first, first)
        manifest["template_count"] += 1
        manifest["fill_variant_count"] += 1
    else:
        manifest["schema"] = "pdf2dxf.font_glyph_catalog.v1"
        manifest["catalog_version"] = "1"
        manifest["outline_policy"] = "raw_contours_v1"
    arrays = {name: array[order] for name, array in arrays.items()}
    manifest["template_set_sha256"] = _dataset_digest(arrays)
    payloads = {}
    for name, array in arrays.items():
        stream = io.BytesIO()
        np.save(stream, array, allow_pickle=False)
        payloads[name] = stream.getvalue()
        manifest["arrays"][name] = {
            "sha256": hashlib.sha256(payloads[name]).hexdigest(),
            "size_bytes": len(payloads[name]),
        }
    payloads["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in payloads.items():
            archive.writestr(name, data)
    with pytest.raises(FontCatalogError, match="representations"):
        load_font_catalog(path)
