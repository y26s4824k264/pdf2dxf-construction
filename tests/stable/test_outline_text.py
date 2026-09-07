from __future__ import annotations

import hashlib
import json
from pathlib import Path

import ezdxf
import numpy as np
import pytest

from pdf2dxf_stable.engine.text import outline_text

GLYPHS = {
    "中": [
        np.asarray([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)], dtype=float),
        np.asarray([(0.5, 0), (0.5, 1)], dtype=float),
    ],
    "文": [
        np.asarray([(0, 1), (1, 1)], dtype=float),
        np.asarray([(0.5, 1), (0.5, 0.7)], dtype=float),
        np.asarray([(0.1, 0), (0.5, 0.7), (0.9, 0)], dtype=float),
    ],
}


def _write_catalog(path: Path, chars=("中", "文")) -> Path:
    templates = []
    for char in chars:
        signature = outline_text.fingerprint_paths(GLYPHS[char])
        assert signature is not None
        templates.append(
            {
                "id": f"test-{ord(char):04x}",
                "char": char,
                "fingerprint": signature.fingerprint,
                "entity_count": signature.entity_count,
                "closed_count": signature.closed_count,
                "point_counts": list(signature.point_counts),
                "aspect_ratio": signature.aspect_ratio,
                "mask_hex": signature.mask_hex,
                "support_locations": 2,
                "support_documents": 2,
                "support_phrases": 2,
                "label_evidence": [
                    {"source_sha256": "a" * 64, "label": char, "char_index": 0},
                    {"source_sha256": "b" * 64, "label": char, "char_index": 0},
                ],
                "admission": "repeated_document_consensus",
            }
        )
    templates.sort(key=lambda row: row["id"])
    canonical = json.dumps(
        templates, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    payload = {
        "schema": outline_text.CATALOG_SCHEMA,
        "catalog_version": "test",
        "runtime_input": "persisted_dxf_only",
        "runtime_ocr": False,
        "template_set_sha256": hashlib.sha256(canonical).hexdigest(),
        "templates": templates,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _add_source_path(doc, path, offset, seqno, *, hatch=False):
    points = [(float(x + offset[0]), float(y + offset[1])) for x, y in path]
    entity = doc.modelspace().add_lwpolyline(
        points[:-1] if np.allclose(path[0], path[-1]) else points,
        close=np.allclose(path[0], path[-1]),
        dxfattribs={"layer": "OUTLINE_TEXT"},
    )
    entity.set_xdata(
        "PDF2DXF15",
        [(1000, "line_or_polyline"), (1070, 0), (1070, seqno), (1000, "s")],
    )
    fill = None
    if hatch and np.allclose(path[0], path[-1]):
        fill = doc.modelspace().add_hatch(dxfattribs={"layer": "OUTLINE_TEXT"})
        fill.paths.add_polyline_path(points[:-1], is_closed=True)
        fill.set_xdata(
            "PDF2DXF15",
            [(1000, "hatch"), (1070, 0), (1070, seqno), (1000, "f")],
        )
    return entity, fill


def _source_dxf(
    path: Path, *, phrases=2, interleaved_non_outline_entities=0
) -> tuple[Path, list[str], str]:
    doc = ezdxf.new("R2007")
    doc.layers.new("OUTLINE_TEXT")
    doc.appids.add("PDF2DXF15")
    source_handles = []
    seqno = 10
    for phrase_index in range(phrases):
        y = phrase_index * 3.0
        for char_index, char in enumerate("中文"):
            x = char_index * 1.35
            for path_index, glyph_path in enumerate(GLYPHS[char]):
                entity, _ = _add_source_path(
                    doc,
                    glyph_path,
                    (x, y),
                    seqno,
                    hatch=char == "中" and path_index == 0,
                )
                source_handles.append(str(entity.dxf.handle))
                for filler_index in range(interleaved_non_outline_entities):
                    doc.modelspace().add_point(
                        (50 + filler_index, 50 + phrase_index)
                    )
                seqno += 1
    unrelated = doc.modelspace().add_lwpolyline(
        [(20, 20), (22, 20), (21, 22)],
        close=True,
        dxfattribs={"layer": "OUTLINE_TEXT"},
    )
    unrelated.set_xdata(
        "PDF2DXF15",
        [(1000, "line_or_polyline"), (1070, 0), (1070, seqno), (1000, "s")],
    )
    unrelated_handle = str(unrelated.dxf.handle)
    doc.saveas(path)
    return path, source_handles, unrelated_handle


def test_persisted_dxf_templates_write_text_and_hide_only_matched_geometry(tmp_path):
    catalog = _write_catalog(tmp_path / "catalog.json")
    dxf_path, source_handles, unrelated_handle = _source_dxf(tmp_path / "source.dxf")

    report = outline_text.recover_outline_text(
        dxf_path,
        mode="required",
        policy="off_layer",
        catalog_path=catalog,
    )

    result = ezdxf.readfile(dxf_path)
    recovered = list(
        result.modelspace().query("TEXT[layer=='PDF_TEXT_RECOVERED_NOOCR']")
    )
    assert report["status"] == "ok"
    assert report["engine"]["runtime_input"] == "persisted_dxf_only"
    assert report["engine"]["runtime_pdf_access"] is False
    assert report["engine"]["ocr_enabled"] is False
    assert report["emitted_text_entities"] == 2
    assert [entity.dxf.text for entity in recovered] == ["中文", "中文"]
    assert all(entity.has_xdata("PDF2DXF_GLYPH") for entity in recovered)
    assert all(
        result.entitydb[handle].dxf.layer == "PDF_OUTLINE_BACKUP"
        for handle in source_handles
    )
    assert result.entitydb[unrelated_handle].dxf.layer == "OUTLINE_TEXT"
    assert result.layers.get("PDF_OUTLINE_BACKUP").is_off()
    assert report["suppressed_fill_entities"] == 2
    assert result.styles.get("PDF2DXF_CJK_VECTOR").dxf.font == "simsun.ttc"


def test_recovery_is_idempotent(tmp_path):
    catalog = _write_catalog(tmp_path / "catalog.json")
    dxf_path, _, _ = _source_dxf(tmp_path / "source.dxf")
    first = outline_text.recover_outline_text(
        dxf_path, mode="required", catalog_path=catalog
    )
    second = outline_text.recover_outline_text(
        dxf_path, mode="required", catalog_path=catalog
    )
    result = ezdxf.readfile(dxf_path)
    recovered = list(
        result.modelspace().query("TEXT[layer=='PDF_TEXT_RECOVERED_NOOCR']")
    )
    assert first["emitted_text_entities"] == 2
    assert second["emitted_text_entities"] == 0
    assert second["existing_recovered_text_entities"] == 2
    assert len(recovered) == 2


def test_recovery_is_idempotent_when_source_outlines_stay_visible(tmp_path):
    catalog = _write_catalog(tmp_path / "catalog.json")
    dxf_path, _, _ = _source_dxf(tmp_path / "source.dxf")
    first = outline_text.recover_outline_text(
        dxf_path, mode="required", policy="keep", catalog_path=catalog
    )
    saved = dxf_path.read_bytes()
    second = outline_text.recover_outline_text(
        dxf_path, mode="required", policy="keep", catalog_path=catalog
    )
    result = ezdxf.readfile(dxf_path)
    recovered = list(
        result.modelspace().query("TEXT[layer=='PDF_TEXT_RECOVERED_NOOCR']")
    )
    assert first["emitted_text_entities"] == 2
    assert second["emitted_text_entities"] == 0
    assert second["already_recovered_runs"] == 2
    assert dxf_path.read_bytes() == saved
    assert len(recovered) == 2


def test_rerun_preserves_user_edits_to_recovered_text(tmp_path):
    catalog = _write_catalog(tmp_path / "catalog.json")
    dxf_path, _, _ = _source_dxf(tmp_path / "source.dxf")
    outline_text.recover_outline_text(
        dxf_path, mode="required", policy="keep", catalog_path=catalog
    )
    edited = ezdxf.readfile(dxf_path)
    recovered = list(
        edited.modelspace().query("TEXT[layer=='PDF_TEXT_RECOVERED_NOOCR']")
    )
    recovered[0].dxf.text = "人工修订"
    edited.saveas(dxf_path)

    report = outline_text.recover_outline_text(
        dxf_path, mode="required", policy="keep", catalog_path=catalog
    )

    result = ezdxf.readfile(dxf_path)
    values = [
        entity.dxf.text
        for entity in result.modelspace().query(
            "TEXT[layer=='PDF_TEXT_RECOVERED_NOOCR']"
        )
    ]
    assert report["emitted_text_entities"] == 0
    assert report["already_recovered_runs"] == 2
    assert values == ["人工修订", "中文"]


def test_source_sequence_keeps_glyph_together_across_interleaved_fillers(tmp_path):
    catalog = _write_catalog(tmp_path / "catalog.json")
    dxf_path, _, _ = _source_dxf(
        tmp_path / "source.dxf", interleaved_non_outline_entities=6
    )

    report = outline_text.recover_outline_text(
        dxf_path, mode="required", catalog_path=catalog
    )

    assert report["emitted_text_entities"] == 2
    assert [row["text"] for row in report["accepted"]] == ["中文", "中文"]


def test_single_han_match_stays_as_outline(tmp_path):
    catalog = _write_catalog(tmp_path / "catalog.json", chars=("中",))
    dxf_path, source_handles, unrelated_handle = _source_dxf(
        tmp_path / "source.dxf", phrases=1
    )
    before = dxf_path.read_bytes()
    report = outline_text.recover_outline_text(
        dxf_path, mode="required", catalog_path=catalog
    )
    assert report["emitted_text_entities"] == 0
    assert report["unpublished_glyph_matches"] == 1
    assert dxf_path.read_bytes() == before
    result = ezdxf.readfile(dxf_path)
    assert result.entitydb[source_handles[0]].dxf.layer == "OUTLINE_TEXT"
    assert result.entitydb[unrelated_handle].dxf.layer == "OUTLINE_TEXT"


def test_missing_catalog_is_non_destructive_in_auto_and_fails_in_required(tmp_path):
    dxf_path, _, _ = _source_dxf(tmp_path / "source.dxf")
    before = dxf_path.read_bytes()
    missing = tmp_path / "missing.json"
    report = outline_text.recover_outline_text(
        dxf_path, mode="auto", catalog_path=missing
    )
    assert report["status"] == "unavailable"
    assert report["original_geometry_preserved"]
    assert dxf_path.read_bytes() == before
    with pytest.raises(
        outline_text.GlyphCatalogUnavailable,
        match="OUTLINE_TEXT_GLYPH_CATALOG_UNAVAILABLE",
    ):
        outline_text.recover_outline_text(
            dxf_path, mode="required", catalog_path=missing
        )


def test_optional_missing_font_catalog_does_not_disable_audited_matches(tmp_path):
    catalog_path = _write_catalog(tmp_path / "catalog.json")
    dxf_path, _, _ = _source_dxf(tmp_path / "source.dxf")

    report = outline_text.recover_outline_text(
        dxf_path,
        mode="auto",
        policy="keep",
        catalog_path=catalog_path,
        font_catalog_paths=[tmp_path / "missing.p2dfont"],
    )

    assert report["status"] == "ok"
    assert report["emitted_text_entities"] == 2
    assert report["font_catalogs"]["loaded"] == 0
    assert report["font_catalogs"]["entries"][0]["status"] == "unavailable"


def test_required_missing_font_catalog_fails_before_editing_dxf(tmp_path):
    catalog_path = _write_catalog(tmp_path / "catalog.json")
    dxf_path, _, _ = _source_dxf(tmp_path / "source.dxf")
    before = dxf_path.read_bytes()

    with pytest.raises(
        outline_text.GlyphCatalogUnavailable,
        match="OUTLINE_TEXT_FONT_CATALOG_UNAVAILABLE",
    ):
        outline_text.recover_outline_text(
            dxf_path,
            mode="required",
            catalog_path=catalog_path,
            font_catalog_paths=[tmp_path / "missing.p2dfont"],
        )
    assert dxf_path.read_bytes() == before


def test_malformed_catalog_row_is_non_destructive_in_auto_mode(tmp_path):
    catalog_path = _write_catalog(tmp_path / "catalog.json")
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    payload["templates"] = [None]
    canonical = json.dumps(
        payload["templates"],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    payload["template_set_sha256"] = hashlib.sha256(canonical).hexdigest()
    catalog_path.write_text(json.dumps(payload), encoding="utf-8")
    dxf_path, _, _ = _source_dxf(tmp_path / "source.dxf")
    before = dxf_path.read_bytes()

    report = outline_text.recover_outline_text(
        dxf_path, mode="auto", catalog_path=catalog_path
    )

    assert report["status"] == "unavailable"
    assert "invalid glyph template row" in report["error"]
    assert dxf_path.read_bytes() == before


def test_catalog_rejects_label_evidence_for_a_different_character(tmp_path):
    catalog_path = _write_catalog(tmp_path / "catalog.json")
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    payload["templates"][0]["label_evidence"][0]["label"] = "错"
    canonical = json.dumps(
        payload["templates"],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    payload["template_set_sha256"] = hashlib.sha256(canonical).hexdigest()
    catalog_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="does not identify"):
        outline_text.load_catalog(catalog_path)


@pytest.mark.parametrize(
    ("text", "accepted"),
    [("中文", True), ("1:90", True), ("中", False), ("90", False), ("一", False)],
)
def test_only_multi_han_runs_or_complete_scales_are_publishable(text, accepted):
    assert outline_text._publishable_text(text)[0] is accepted
