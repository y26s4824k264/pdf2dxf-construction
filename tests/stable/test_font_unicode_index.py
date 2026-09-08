"""Unicode indexing retains every range, alias and raw/fill representation."""

import json
import zipfile

import pytest

from pdf2dxf_stable.engine.text.font_catalog import (
    HAN_RANGES,
    FontCatalogError,
    build_font_catalog,
    is_han_character,
    load_font_catalog,
)
from test_font_catalog import SHAPES, _write_font


def test_han_membership_matches_every_unicode_codepoint():
    # Independent dense membership oracle, including gaps, touching ranges,
    # surrogates, compatibility ideographs and the final Extension J endpoint.
    expected = bytearray(0x110000)
    previous_end = -1
    for start, end in HAN_RANGES:
        assert previous_end < start <= end < len(expected)
        expected[start : end + 1] = b"\x01" * (end - start + 1)
        previous_end = end
    actual = bytes(is_han_character(chr(cp)) for cp in range(len(expected)))
    assert actual == expected
    assert not is_han_character("")
    assert not is_han_character("汉字")
    assert not is_han_character("A")


@pytest.mark.parametrize("actual_present", [False, True])
def test_alias_before_canonical_codepoint_keeps_actual_raw_glyph_priority(
    tmp_path, monkeypatch, actual_present
):
    # Kangxi radical 2F00 sorts before its NFKC label 4E00. Both raw/fill
    # representations of the alias must survive; neither may replace the
    # real cmap glyph when that glyph is present later in the catalog.
    monkeypatch.setitem(SHAPES, "⼀", (*SHAPES["图"], ((1, 1), (2, 2))))
    if actual_present:
        monkeypatch.setitem(SHAPES, "一", SHAPES["中"])
    font = _write_font(tmp_path / "aliases.ttf")
    path = tmp_path / "aliases.p2dfont"
    build_font_catalog(font, path, charset="all")
    catalog = load_font_catalog(path)
    variants = catalog.templates_by_label["一"]
    assert [t.char for t in variants] == ["⼀", "⼀"] + (
        ["一"] if actual_present else []
    )
    assert variants[0].entity_count == variants[1].entity_count + 1
    assert catalog.by_char["⼀"] is variants[0]
    assert catalog.by_char["一"] is (variants[2] if actual_present else variants[0])
    for template in variants:
        for key in template.match_keys:
            assert "一" in catalog.matching_characters(key, template.aspect_ratio)


@pytest.mark.parametrize("delta", [-1, 1])
def test_vectorized_coverage_validation_still_rejects_wrong_han_count(tmp_path, delta):
    font = _write_font(tmp_path / "font.ttf")
    path = tmp_path / "font.p2dfont"
    build_font_catalog(font, path)
    with zipfile.ZipFile(path) as archive:
        payloads = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(payloads["manifest.json"])
    manifest["han_template_count"] += delta
    payloads["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in payloads.items():
            archive.writestr(name, data)
    with pytest.raises(FontCatalogError, match="coverage counts are invalid"):
        load_font_catalog(path)
