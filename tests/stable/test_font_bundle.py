"""Offline bundles, reproducible builds and protected caller-owned inputs."""

import hashlib
import io
import json
from pathlib import Path
import zipfile

import pytest

from pdf2dxf_stable.cli import main as cli_main
from pdf2dxf_stable.engine.text.font_bundle import (
    FontCatalogError,
    file_record,
    inspect_font_bundle,
    load_font_bundle,
)
from pdf2dxf_stable.engine.text.font_catalog import build_font_catalog
from test_font_catalog import _write_font
from test_multilingual_outline import _baseline_pdf, _saved_text
from test_release_snapshot import exporter


@pytest.fixture
def sources(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    font = _write_font(cache / "font.ttf")
    notice = cache / "license.txt"
    notice.write_text("CC0 test fixture: programmatically generated glyphs.\n")
    downloads = {
        name: {"url": "https://example.invalid/" + name, **file_record(cache / name)}
        for name in (font.name, notice.name)
    }
    lock = {
        "schema": "pdf2dxf.open_font_sources.v1",
        "version": "test",
        "charset": "chinese",
        "downloads": downloads,
        "fonts": [
            {
                "id": "test-font",
                "group": "core",
                "family": "Test",
                "version": "1",
                "license": "CC0-1.0",
                "source": {"download": font.name, **file_record(font)},
                "notices": [
                    {
                        "download": notice.name,
                        "path": "licenses/CC0.txt",
                        **file_record(notice),
                    }
                ],
            }
        ],
    }
    path = tmp_path / "lock.json"
    path.write_text(json.dumps(lock))
    return path, cache, font


@pytest.fixture
def bundle(tmp_path, sources):
    lock, cache, font = sources
    result = exporter("build_open_font_bundle").build_bundle(
        lock, cache, tmp_path / "pack", "core", offline=True
    )
    return Path(result["directory"]) / "font-bundle.json"


def test_offline_bundle_reaches_saved_text_without_source_font(
    tmp_path, sources, bundle, capsys
):
    font = sources[2]
    pdf = _baseline_pdf(font, tmp_path / "input.pdf", "中文国图")
    font.unlink()
    result = load_font_bundle(bundle)
    assert len(result["catalog_paths"]) == 1
    assert len(inspect_font_bundle(bundle)["catalogs"]) == 1
    assert cli_main(["font-catalog", "inspect-bundle", str(bundle)]) == 0
    capsys.readouterr()
    output = tmp_path / "output.dxf"
    assert (
        cli_main(
            [
                "convert",
                str(pdf),
                "-o",
                str(output),
                "--outline-chinese",
                "required",
                "--outline-font-bundle",
                str(bundle),
                "--no-path-text",
                "--no-strict-validation",
                "--allow-quality-degradation",
            ]
        )
        == 2
    )
    assert _saved_text(output) == ["中文国图"]
    report = json.loads(capsys.readouterr().out)
    recognition = report["pages"][0]["backend"]["result"]["outline_chinese"]
    assert recognition["font_catalogs"]["locked"] == 1
    assert recognition["engine"]["ocr_enabled"] is False
    with zipfile.ZipFile(bundle.parent.with_suffix(".zip")) as archive:
        assert not any(
            name.endswith((".ttf", ".otf", ".pdf", ".dxf"))
            for name in archive.namelist()
        )
        assert (
            archive.read("pack/licenses/CC0.txt")
            == (sources[1] / "license.txt").read_bytes()
        )


@pytest.mark.parametrize(
    "relative", ["catalogs/test-font.p2dfont", "licenses/CC0.txt", "SOURCE_LOCK.json"]
)
def test_bundle_rejects_corrupt_or_missing_payload(bundle, relative):
    target = bundle.parent / relative
    before = target.read_bytes()
    target.write_bytes(before[:-1] + bytes([before[-1] ^ 1]))
    with pytest.raises(FontCatalogError, match="hash/size mismatch"):
        load_font_bundle(bundle)
    target.unlink()
    with pytest.raises(FontCatalogError, match="missing"):
        load_font_bundle(bundle)


@pytest.mark.parametrize(
    "unsafe",
    ["../outside", "/absolute", "C:/outside", "x\\file", "x/../file", "./file"],
)
def test_bundle_rejects_unsafe_manifest_paths(bundle, unsafe):
    manifest = json.loads(bundle.read_text())
    manifest["files"][unsafe] = manifest["files"].pop("SOURCE_LOCK.json")
    bundle.write_text(json.dumps(manifest))
    with pytest.raises(FontCatalogError, match="unsafe"):
        load_font_bundle(bundle)


def test_bundle_rejects_symlinked_license(bundle, tmp_path):
    notice = bundle.parent / "licenses/CC0.txt"
    outside = tmp_path / "outside.txt"
    outside.write_bytes(notice.read_bytes())
    notice.unlink()
    try:
        notice.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable on this host")
    with pytest.raises(FontCatalogError, match="symlinks"):
        load_font_bundle(bundle)


@pytest.mark.parametrize("name", ["drawing_p002.dxf", "licenses/output.report.json"])
def test_bundle_cannot_declare_dxf_or_output_report_as_a_resource(bundle, name):
    target = bundle.parent / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("caller-owned drawing/report")
    manifest = json.loads(bundle.read_text())
    manifest["files"][name] = file_record(target)
    bundle.write_text(json.dumps(manifest))
    with pytest.raises(FontCatalogError, match="unsupported file type"):
        load_font_bundle(bundle)


@pytest.mark.parametrize("mutation", ["license", "duplicate", "source"])
def test_bundle_rejects_inconsistent_catalog_metadata(bundle, mutation):
    manifest = json.loads(bundle.read_text())
    if mutation == "license":
        manifest["catalogs"][0]["license_files"] = []
    elif mutation == "duplicate":
        manifest["catalogs"].append(manifest["catalogs"][0])
    else:
        manifest["catalogs"][0]["source_sha256"] = "0" * 64
    bundle.write_text(json.dumps(manifest))
    with pytest.raises(FontCatalogError):
        inspect_font_bundle(bundle)


@pytest.mark.parametrize(
    "relative", ["font-bundle.json", "licenses/CC0.txt", "catalogs/test-font.p2dfont"]
)
def test_cli_json_cannot_overwrite_bundle_inputs(bundle, relative):
    target = bundle.parent / relative
    before = target.read_bytes()
    with pytest.raises(SystemExit) as exc:
        cli_main(["font-catalog", "inspect-bundle", str(bundle), "--json", str(target)])
    assert exc.value.code == 2
    assert target.read_bytes() == before


def test_bundle_archive_rebuild_has_identical_catalog_data(tmp_path, sources, bundle):
    lock, cache, _ = sources
    tool = exporter("build_open_font_bundle")
    other = tmp_path / "other"
    tool.build_bundle(
        lock,
        cache,
        other,
        "core",
        offline=True,
        catalog_cache=bundle.parent / "catalogs",
    )
    first = load_font_bundle(bundle)["manifest"]
    second = load_font_bundle(other / "font-bundle.json")["manifest"]
    assert first == second
    with pytest.raises(ValueError, match="already exist"):
        tool.build_bundle(lock, cache, other, "core", offline=True)


def test_wrong_font_catalog_cache_is_not_accepted(tmp_path, sources, bundle):
    lock, cache, font = sources
    wrong = tmp_path / "wrong"
    wrong.mkdir()
    build_font_catalog(font, wrong / "test-font.p2dfont", codepoints=[ord("中")])
    with pytest.raises(ValueError, match="build contract"):
        exporter("build_open_font_bundle").build_bundle(
            lock,
            cache,
            tmp_path / "rejected",
            "core",
            offline=True,
            catalog_cache=wrong,
        )


@pytest.mark.parametrize("corrupt", [False, True])
def test_download_is_bounded_and_verified_before_caching(
    tmp_path, monkeypatch, corrupt
):
    tool = exporter("build_open_font_bundle")
    data = b"verified font bytes"
    expected = {
        "url": "https://example.invalid/font",
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    response = io.BytesIO(data[:-1] + b"!" if corrupt else data)
    response.url = expected["url"]
    monkeypatch.setattr(
        tool.urllib.request, "urlopen", lambda *args, **kwargs: response
    )
    if corrupt:
        with pytest.raises(ValueError, match="hash/size mismatch"):
            tool.fetch_download(tmp_path, "font.ttf", expected)
        assert not (tmp_path / "font.ttf").exists()
    else:
        assert tool.fetch_download(tmp_path, "font.ttf", expected).read_bytes() == data
        assert (
            tool.fetch_download(
                tmp_path, "font.ttf", expected, offline=True
            ).read_bytes()
            == data
        )
    assert not list(tmp_path.glob(".download-*"))


def test_archive_member_size_and_hash_are_checked(tmp_path):
    tool = exporter("build_open_font_bundle")
    archive_path = tmp_path / "font.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("font.ttf", b"not-the-declared-font")
        archive.writestr("../outside", b"never extracted")
    downloads = {
        "font.zip": {
            "url": "https://example.invalid/font.zip",
            **file_record(archive_path),
        }
    }
    with pytest.raises(ValueError, match="archive member"):
        tool.source_payload(
            tmp_path,
            downloads,
            {
                "download": "font.zip",
                "member": "font.ttf",
                "bytes": 5,
                "sha256": "0" * 64,
            },
            offline=True,
        )
    assert not (tmp_path.parent / "outside").exists()


def test_font_build_reports_progress_and_actual_skipped_codepoints(tmp_path):
    from fontTools.ttLib import TTFont
    from test_font_catalog import _glyph

    font = _write_font(tmp_path / "empty.ttf")
    with TTFont(font) as sfnt:
        sfnt["glyf"][sfnt.getBestCmap()[ord("图")]] = _glyph(())
        sfnt.save(font)
    seen = []
    result = build_font_catalog(
        font, tmp_path / "subset.p2dfont", progress=lambda a, b: seen.append((a, b))
    )
    assert seen == [(1, 4), (2, 4), (3, 4), (4, 4)]
    assert result["skipped_non_outline_mappings"] == 1
    assert [item["codepoint"] for item in result["skipped_mappings"]] == [ord("图")]


@pytest.mark.parametrize("child", ["\ufe32", "I", "丨"])
@pytest.mark.parametrize("pipeline", ["stroke", "fill"])
def test_complete_glyph_owns_contained_punctuation_but_not_competing_letters(
    tmp_path, monkeypatch, child, pipeline
):
    from test_font_catalog import SHAPES
    import ezdxf
    from test_font_catalog import _write_outline_dxf
    from pdf2dxf_stable.engine.text.font_catalog import extract_font_glyph_paths
    from pdf2dxf_stable.engine.text.outline_text import recover_outline_text

    # Vertical en dash is a real NFKC punctuation alias and also resembles a
    # vertical stroke inside Han/Latin letters. A competing I/丨 stays ambiguous.
    monkeypatch.setitem(SHAPES, child, (SHAPES["中"][1],))
    font = _write_font(tmp_path / "contains.ttf")
    catalog = tmp_path / "contains.p2dfont"
    build_font_catalog(font, catalog)
    output = tmp_path / "output.dxf"
    glyphs = {ch: extract_font_glyph_paths(font, ch) for ch in "国图文中"}
    _write_outline_dxf(output, glyphs, text="国图文中")
    if pipeline == "fill":
        doc = ezdxf.readfile(output)
        for outline in list(doc.modelspace().query("LWPOLYLINE")):
            hatch = doc.modelspace().add_hatch()
            hatch.paths.add_polyline_path(
                list(outline.get_points("xy")), is_closed=True
            )
            hatch.set_xdata("PDF2DXF15", outline.get_xdata("PDF2DXF15"))
            doc.modelspace().delete_entity(outline)
        doc.saveas(output)
    font.unlink()
    report = recover_outline_text(output, mode="required", font_catalog_paths=[catalog])
    actual = "".join(_saved_text(output))
    if child == "\ufe32":
        assert actual == "国图文中", report
        assert report["font_contained_punctuation_suppressed"] >= 1
    else:
        assert "中" not in actual, report
        assert report["font_overlapping_matches_rejected"] >= 2
