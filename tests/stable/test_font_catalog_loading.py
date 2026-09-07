"""Catalog loading preserves the binary wire contract and Unicode conflicts."""

import hashlib
import io
import json
import unicodedata
import zipfile

import numpy as np
import pytest

from pdf2dxf_stable.engine.text.font_catalog import (
    ARRAY_NAMES,
    FontCatalogError,
    _catalog_identifier,
    _dataset_digest,
    build_font_catalog,
    load_font_catalog,
)
from test_font_catalog import SHAPES, _rewrite_legacy_catalog, _write_font


def _binary_catalog(tmp_path, variant_count, *, valid_canonical=True):
    font = _write_font(tmp_path / "font.ttf")
    path = tmp_path / "font.p2dfont"
    build_font_catalog(font, path)
    original = load_font_catalog(path)
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        arrays = {
            name: np.load(io.BytesIO(archive.read(name)), allow_pickle=False)
            for name in ARRAY_NAMES
        }
    expected = []
    rows = []
    for index, template in enumerate(original.templates):
        # Opaque 16-byte digests may contain leading, internal and trailing NULs.
        canonical = hashlib.blake2b(
            template.canonical_mask
            + template.entity_count.to_bytes(2, "little")
            + template.closed_count.to_bytes(2, "little"),
            digest_size=16,
        ).digest()
        distinct = [
            canonical if valid_canonical else bytes([index + 30]) * 16,
            b"\0" + bytes([index + 1]) * 14 + b"\0",
            bytes([index + 10]) + b"\0" * 15,
        ][:variant_count]
        variants = [distinct[i % len(distinct)] for i in range(variant_count)]
        expected.append(tuple(distinct))
        rows.append([list(value) for value in variants])
    arrays["variant_digests.npy"] = np.asarray(rows, dtype="u1")
    manifest["tolerance_divisors"] = list(range(8, 8 + variant_count))
    manifest["ambiguous_geometry_keys"] = 0
    manifest["fully_ambiguous_characters"] = 0
    manifest["template_set_sha256"] = _dataset_digest(arrays)
    manifest["catalog_id"] = _catalog_identifier(
        manifest["font"]["sha256"],
        manifest["font"]["face_index"],
        manifest["template_set_sha256"],
    )
    with zipfile.ZipFile(path, "w") as archive:
        for name, array in arrays.items():
            stream = io.BytesIO()
            np.save(stream, array, allow_pickle=False)
            payload = stream.getvalue()
            manifest["arrays"][name] = {
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            archive.writestr(name, payload)
        archive.writestr("manifest.json", json.dumps(manifest))
    return path, original, expected


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("variant_count", [1, 3, 32])
def test_binary_variants_preserve_nuls_order_and_topology(
    tmp_path, legacy, variant_count
):
    path, original, expected = _binary_catalog(tmp_path, variant_count)
    if legacy:
        legacy_path = tmp_path / "legacy.p2dfont"
        _rewrite_legacy_catalog(path, legacy_path)
        path = legacy_path
    actual = load_font_catalog(path)
    assert len(actual.templates) == len(original.templates)
    for previous, template, digests in zip(original.templates, actual.templates, expected):
        assert template.char == previous.char
        assert template.canonical_mask == previous.canonical_mask
        assert template.entity_count == previous.entity_count
        assert template.closed_count == previous.closed_count
        assert template.match_digests == digests
        for digest in digests:
            key = (template.entity_count, template.closed_count, digest)
            assert actual.lookup[key] == (template.char,)
            assert actual.matching_characters(key, template.aspect_ratio) == (template.char,)
    assert len(actual.lookup) == len(actual.templates) * min(variant_count, 3)


def test_binary_variants_still_require_the_canonical_mask(tmp_path):
    path, _, _ = _binary_catalog(tmp_path, 32, valid_canonical=False)
    with pytest.raises(FontCatalogError, match="canonical mask is not a match variant"):
        load_font_catalog(path)


def test_many_collisions_keep_all_labels_and_normalize_aliases(tmp_path, monkeypatch):
    aliases = ["Ａ", "ａ", "a", *(chr(cp) for cp in range(0x4E10, 0x4E50))]
    for char in aliases:
        monkeypatch.setitem(SHAPES, char, SHAPES["图"])
    font = _write_font(tmp_path / "aliases.ttf")
    path = tmp_path / "aliases.p2dfont"
    build_font_catalog(font, path, charset="all")
    expected = tuple(sorted({"图", "A", "a", *aliases[3:]}, key=ord))
    catalog = load_font_catalog(path)
    assert catalog.by_char["A"].char == "Ａ"
    assert catalog.by_char["a"].char == "a"
    assert len(catalog.templates_by_label["a"]) == 2
    template = catalog.by_char["图"]
    for key in template.match_keys:
        assert catalog.lookup[key] == expected
        assert catalog.matching_characters(key, template.aspect_ratio) == expected
    assert catalog.fully_ambiguous_characters == len(aliases) + 1
    assert catalog.recognition_characters == frozenset(
        unicodedata.normalize("NFKC", char) for char in SHAPES
    )
