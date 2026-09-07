"""Numeric serialization is bounded; it must never select an ambiguous label."""

from dataclasses import replace

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
    "displacement,expected", [(0.002, "国文中图"), (0.1, "国文中")]
)
@pytest.mark.parametrize("fill", [False, True])
def test_saved_dxf_numeric_boundary_is_bounded(
    tmp_path, monkeypatch, displacement, expected, fill
):
    # This vertex is exactly x=18.5 on the normalized raster. FontTools stores
    # integer source coordinates; only the saved DXF receives serialization noise.
    monkeypatch.setitem(
        SHAPES, "图", (((0, 0), (980, 0), (980, 980), (310, 500), (0, 980)),)
    )
    font = _write_font(tmp_path / "font.ttf")
    catalog = tmp_path / "font.p2dfont"
    build_font_catalog(font, catalog)
    glyphs = {ch: extract_font_glyph_paths(font, ch) for ch in SHAPES}
    glyphs["图"][0][3, 0] += displacement
    dxf = _write_outline_dxf(tmp_path / "input.dxf", glyphs, text="国文中图")
    if fill:
        doc = ezdxf.readfile(dxf)
        for entity in list(doc.modelspace()):
            hatch = doc.modelspace().add_hatch(dxfattribs={"layer": entity.dxf.layer})
            hatch.paths.add_polyline_path(list(entity.get_points("xy")), is_closed=True)
            hatch.set_xdata("PDF2DXF15", list(entity.get_xdata("PDF2DXF15")))
            doc.modelspace().delete_entity(entity)
        doc.saveas(dxf)
    font.unlink()
    before = ezdxf.readfile(dxf)
    original = {
        e.dxf.handle: [p.tolist() for p in o._entity_paths(e, include_fill=True)]
        for e in before.modelspace()
    }
    report = o.recover_outline_text(dxf, mode="required", font_catalog_paths=[catalog])
    after = ezdxf.readfile(dxf)
    assert (
        "".join(
            e.dxf.text
            for e in after.modelspace().query(f'TEXT[layer=="{o.TEXT_LAYER}"]')
        )
        == expected
    )
    assert report["font_numeric_stabilized_matches"] == (
        1 if displacement == 0.002 else 0
    )
    for handle, paths in original.items():
        assert [
            p.tolist()
            for p in o._entity_paths(after.entitydb[handle], include_fill=True)
        ] == paths
    if displacement == 0.002:
        assert report["accepted"][0]["font_raster_round_decimals"][-1] == 3
    again = o.recover_outline_text(dxf, mode="required", font_catalog_paths=[catalog])
    assert again["emitted_text_entities"] == 0


@pytest.mark.parametrize("across_catalogs", [False, True])
def test_all_numeric_variants_participate_in_ambiguity_rejection(
    tmp_path, across_catalogs
):
    font = _write_font(tmp_path / "font.ttf")
    path = tmp_path / "font.p2dfont"
    build_font_catalog(font, path)
    catalog = load_font_catalog(path)
    glyphs = {ch: extract_font_glyph_paths(font, ch) for ch in SHAPES}
    glyphs["图"] = (
        np.array([(0, 0), (980, 0), (980, 980), (310.002, 500), (0, 980), (0, 0)]),
    )
    dxf = _write_outline_dxf(tmp_path / "conflict.dxf", glyphs, text="图")
    doc = ezdxf.readfile(dxf)
    atoms, _, _ = o._collect_atoms(doc, 0)
    paths = [p for atom in atoms for p in atom.paths]
    variants = o._font_fingerprint_variants(paths, o._font_fingerprint_paths(paths))
    assert {dec for _, dec in variants} == {3, 4}
    catalogs = []
    # Two exact, persisted-mask-style labels compete at the numeric boundary.
    # Even a primary four-decimal hit may not hide the other label.
    template = catalog.by_char["图"]
    labels = {}
    lookup = {}
    for (signature, _), char in zip(variants, "图回"):
        key = o._font_signature_key(signature)
        labels[char] = (
            replace(
                template,
                char=char,
                codepoint=ord(char),
                entity_count=key[0],
                closed_count=key[1],
                aspect_ratio=signature.aspect_ratio,
                match_digests=(key[2],),
            ),
        )
        lookup[key] = (char,)
        if across_catalogs:
            catalogs.append(
                replace(
                    catalog,
                    catalog_id=char,
                    lookup={key: (char,)},
                    templates_by_label={char: labels[char]},
                    lengths=frozenset({1}),
                    structures={(1, 1): (1, 1)},
                )
            )
    if not across_catalogs:
        catalogs = [
            replace(
                catalog,
                lookup=lookup,
                templates_by_label=labels,
                lengths=frozenset({1}),
                structures={(1, 1): (1, 1)},
            )
        ]
    matches, metrics = o._scan_font_catalog_matches(
        atoms,
        [o.FontCatalogLock(c, 4, tuple("国文中图"), "candidate") for c in catalogs],
        set(),
    )
    assert matches == []
    assert metrics["font_ambiguous_geometry_matches"] == 1


@pytest.mark.parametrize("locked_id", ["a", "b"])
def test_published_numeric_evidence_comes_from_a_locked_catalog(tmp_path, locked_id):
    font = _write_font(tmp_path / "font.ttf")
    path = tmp_path / "font.p2dfont"
    build_font_catalog(font, path)
    catalog = replace(load_font_catalog(path), catalog_id=locked_id)
    glyphs = {ch: extract_font_glyph_paths(font, ch) for ch in SHAPES}
    dxf = _write_outline_dxf(tmp_path / "glyph.dxf", glyphs, text="图")
    atoms, _, _ = o._collect_atoms(ezdxf.readfile(dxf), 0)
    matches, _ = o._scan_font_catalog_matches(
        atoms, [o.FontCatalogLock(catalog, 0, (), "candidate")], set()
    )
    (match,) = matches
    evidence = (("a", "11" * 16, 4), ("b", "22" * 16, 3))
    candidate = replace(
        match, font_catalog_ids=("a", "b"), font_match_evidence=evidence
    )
    (finalized,) = o._finalize_font_matches(
        [candidate],
        [o.FontCatalogLock(catalog, 3, tuple("国文中"), "audited_han_anchors")],
    )
    (expected,) = [item for item in evidence if item[0] == locked_id]
    assert finalized.font_catalog_ids == (locked_id,)
    assert finalized.template.id == f"font-{locked_id}-u56fe"
    assert finalized.template.fingerprint == expected[1]
    assert finalized.font_raster_round_decimals == expected[2]
    assert finalized.font_match_evidence == (expected,)
