import json
import math
import shutil
import sys
import time
from pathlib import Path

import ezdxf
import fitz
import pytest
from PIL import Image
from pydantic import ValidationError

from pdf2dxf_stable.batch import _collect, _destination
from pdf2dxf_stable.core import Converter, _sheet_like
from pdf2dxf_stable.determinism import canonicalize_ascii_dxf, sha256
from pdf2dxf_stable.drawings import DrawingSpool
from pdf2dxf_stable.profiles import emit_legacy_r12, emit_universal
from pdf2dxf_stable.request import ConversionRequest
from pdf2dxf_stable.supervision import run_supervised
from pdf2dxf_stable.validation import validate_dxf


def pdf_file(path):
    with fitz.open() as doc:
        page = doc.new_page()
        page.draw_line((10, 10), (110, 10))
        page.insert_text((20, 50), "2026-09-03 -0")
        doc.save(path)
    return path


@pytest.mark.parametrize(
    "name", ("建筑构造统一做法表（一）.pdf", "门窗表.pdf", "建筑设计说明.pdf")
)
def test_non_scaled_sheet_names_are_detected(name):
    assert _sheet_like(name, "auto")


def test_drawing_name_is_not_mistaken_for_non_scaled_sheet():
    assert not _sheet_like("二层平面图.pdf", "auto")


def test_batch_cli_passes_outline_text_and_declared_scale_options(
    tmp_path, monkeypatch, capsys
):
    import pdf2dxf_stable.batch as batch_module
    from pdf2dxf_stable.cli import main

    captured = {}

    def fake_batch(source, output, request):
        captured.update(source=source, output=output, request=request)
        return {"failed": 0}

    monkeypatch.setattr(batch_module, "run_batch", fake_batch)
    assert (
        main(
            [
                "batch",
                str(tmp_path / "source"),
                "-o",
                str(tmp_path / "output"),
                "--workers",
                "1",
                "--outline-chinese",
                "required",
                "--outline-font-catalog",
                str(tmp_path / "font-a.p2dfont"),
                "--outline-font-catalog",
                str(tmp_path / "font-b.p2dfont"),
                "--scale-mode",
                "declared",
            ]
        )
        == 0
    )
    assert captured["request"].workers == 1
    assert captured["request"].outline_chinese == "required"
    assert captured["request"].outline_font_catalogs == [
        str(tmp_path / "font-a.p2dfont"),
        str(tmp_path / "font-b.p2dfont"),
    ]
    assert captured["request"].scale_mode == "declared"
    capsys.readouterr()


def test_backend_worker_passes_persisted_font_catalog_paths(tmp_path, monkeypatch):
    from pdf2dxf_stable import backend_worker

    captured = {}

    class FakeModule:
        __name__ = "fake_backend"

    def fake_convert(**kwargs):
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(
        backend_worker, "_find_backend", lambda: (FakeModule, fake_convert)
    )
    request_path = tmp_path / "request.json"
    request_path.write_text(
        ConversionRequest(
            outline_chinese="required",
            outline_font_catalogs=["catalogs/a.p2dfont", "~/b.p2dfont"],
            recover_pure_path_text=False,
        ).model_dump_json(),
        encoding="utf-8",
    )
    result_path = tmp_path / "result.json"

    assert (
        backend_worker.main(
            [
                str(tmp_path / "source.pdf"),
                "--page",
                "0",
                "--output",
                str(tmp_path / "output.dxf"),
                "--result-json",
                str(result_path),
                "--request-json",
                str(request_path),
            ]
        )
        == 0
    )
    assert captured["outline_font_catalogs"] == [
        str((Path.cwd() / "catalogs/a.p2dfont").resolve()),
        str(Path("~/b.p2dfont").expanduser().resolve()),
    ]


def test_removed_native_dimension_engine_is_rejected():
    from pdf2dxf_stable.engine.pipeline import (
        ConstructionPDF2DXFV15,
        PipelineConfigV15,
    )

    with pytest.raises(ValueError, match="include_native_dimensions was removed"):
        ConstructionPDF2DXFV15(PipelineConfigV15(include_native_dimensions=True))


@pytest.mark.parametrize("rotation", [0, 90, 270])
def test_callback_preserves_records_clips_forms_and_rotation(tmp_path, rotation):
    with fitz.open() as form, fitz.open() as doc:
        page = form.new_page()
        page.draw_rect((10, 10, 100, 100), color=(1, 0, 0), fill=(0, 1, 0))
        page.draw_circle((50, 50), 20)
        page.insert_text((20, 50), "visible")
        page = doc.new_page()
        page.show_pdf_page(
            fitz.Rect(40, 50, 300, 400), form, 0, clip=(20, 20, 200, 250)
        )
        page.set_cropbox(fitz.Rect(10, 10, 500, 700))
        page.set_rotation(rotation)
        expected = page.get_cdrawings(extended=True)
        spool = DrawingSpool(page, tmp_path)
        try:
            assert any(r["type"] == "clip" for r in expected)
            assert list(spool) == expected
            assert list(spool) == expected
            assert len(spool) == len(expected)
            assert page.rotation == rotation
        finally:
            spool.close()
        assert not list(tmp_path.glob("*.spool"))


def test_canonicalizer_preserves_user_dates_identifiers_and_negative_zero(tmp_path):
    source = tmp_path / "source.dxf"
    doc = ezdxf.new("R2007")
    strings = ["施工日期 2026-09-03", "-0", "{AAAAAAAA-1111-2222-3333-123456789012}"]
    for text in strings:
        doc.modelspace().add_text(text)
    doc.appids.add("USER_DATA")
    doc.modelspace()[0].set_xdata("USER_DATA", [(1000, "/2026-09-03/source.pdf")])
    doc.saveas(source)
    canonicalize_ascii_dxf(source, seed="test")
    result = ezdxf.readfile(source)
    assert [e.dxf.text for e in result.modelspace()] == strings
    assert (
        result.modelspace()[0].get_xdata("USER_DATA")[0].value
        == "/2026-09-03/source.pdf"
    )
    before = source.read_bytes()
    canonicalize_ascii_dxf(source, seed="test")
    assert source.read_bytes() == before


def test_cold_profiles_are_deterministic_and_never_reuse_stale_geometry(tmp_path):
    source = tmp_path / "source.dxf"
    outputs = []
    for i, length in enumerate([10, 10, 100]):
        doc = ezdxf.new("R2007")
        doc.modelspace().add_line((0, 0), (length, 0))
        doc.saveas(source)
        output = tmp_path / f"{i}.dxf"
        emit_universal(source, output, seed="same")
        outputs.append(output)
        assert ezdxf.readfile(output).modelspace()[0].dxf.end.x == length
    assert sha256(outputs[0]) == sha256(outputs[1])
    assert sha256(outputs[1]) != sha256(outputs[2])


def test_external_images_survive_relocation(tmp_path):
    raw = tmp_path / "backend" / "input.dxf"
    nested = raw.parent / "assets" / "images"
    nested.mkdir(parents=True)
    Image.new("RGB", (10, 10), "red").save(nested / "a.png")
    doc = ezdxf.new("R2007")
    definition = doc.add_image_def("images/a.png", (10, 10))
    doc.modelspace().add_image(definition, (1, 2), (10, 10))
    doc.saveas(raw)
    output = tmp_path / "published" / "drawing.dxf"
    emit_universal(raw, output, seed="image", resource_root=raw.parent)
    moved = tmp_path / "moved"
    shutil.copytree(output.parent, moved)
    shutil.rmtree(output.parent)
    result = ezdxf.readfile(moved / output.name)
    for definition in result.objects.query("IMAGEDEF"):
        assert (moved / definition.dxf.filename).is_file()
        assert not Path(definition.dxf.filename).is_absolute()


def test_manual_scale_changes_geometry_and_units_without_changing_text(tmp_path):
    raw, output = tmp_path / "raw.dxf", tmp_path / "out.dxf"
    doc = ezdxf.new("R2007")
    doc.modelspace().add_line((0, 0), (10, 0))
    doc.modelspace().add_text("2026-09-03", dxfattribs={"height": 2})
    doc.saveas(raw)
    emit_universal(
        raw,
        output,
        seed="scale",
        request=ConversionRequest(scale_mode="manual", manual_scale=100, units="m"),
    )
    result = ezdxf.readfile(output)
    assert result.header["$INSUNITS"] == 6
    assert math.isclose(result.modelspace()[0].dxf.end.x, 1)
    assert result.modelspace()[1].dxf.text == "2026-09-03"
    assert math.isclose(result.modelspace()[1].dxf.height, 0.2)


def test_r12_preserves_hidden_frozen_layers_and_text_style(tmp_path):
    raw, output = tmp_path / "raw.dxf", tmp_path / "out.dxf"
    doc = ezdxf.new("R2007")
    layer = doc.layers.new("HIDDEN", dxfattribs={"color": -3})
    layer.freeze()
    doc.styles.new("CN", dxfattribs={"font": "simsun.ttf"})
    doc.modelspace().add_text(
        "2026-09-03", dxfattribs={"layer": "HIDDEN", "style": "CN"}
    )
    doc.saveas(raw)
    emit_legacy_r12(raw, output, seed="r12")
    result = ezdxf.readfile(output)
    assert result.dxfversion == "AC1009"
    assert result.layers.get("HIDDEN").is_off()
    assert result.layers.get("HIDDEN").is_frozen()
    assert result.modelspace()[0].dxf.style == "CN"
    assert result.styles.get("CN").dxf.font == "simsun.ttf"


def test_unknown_scale_and_missing_text_cannot_pass_quality_gate(tmp_path):
    raw = tmp_path / "raw.dxf"
    doc = ezdxf.new("R2007")
    doc.modelspace().add_line((0, 0), (1, 0))
    doc.saveas(raw)
    payload = {
        "result": {
            "schema": "pdf2dxf.v20.paper_fallback",
            "paper_mm_preserved": True,
            "coverage_gate": {"model_output": False},
            "viewports": [],
            "path_text": {"error": "assets missing"},
        }
    }
    value = validate_dxf(raw, profile="universal", backend_payload=payload)
    assert value["geometry_valid"]
    assert not value["valid"] and not value["model_ready"]
    assert value["dimension_validation_status"] == "unavailable"
    assert value["dimension_relative_error_p95"] is None
    assert any(r["code"] == "PATH_TEXT_UNAVAILABLE" for r in value["warnings"])
    relaxed = validate_dxf(
        raw,
        profile="universal",
        backend_payload=payload,
        request=ConversionRequest(strict_validation=False),
    )
    assert relaxed["valid"] and not relaxed["model_ready"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"pages": []},
        {"pages": [0]},
        {"scale_mode": "manual"},
        {"scale_mode": "manual", "manual_scale": float("inf")},
        {"manual_scale": 100},
        {"outline_chinese": "guess"},
        {"text_mode": "outline"},
        {"curve_mode": "native"},
        {"fill_mode": "solid"},
        {"mode": "split"},
        {"typo": True},
    ],
)
def test_unsupported_or_invalid_requests_are_rejected(kwargs):
    with pytest.raises(ValidationError):
        ConversionRequest(**kwargs)


def test_invalid_page_writes_failed_report_and_no_dxf(tmp_path):
    source = pdf_file(tmp_path / "in.pdf")
    target = tmp_path / "out.dxf"
    result = Converter().convert(source, target, ConversionRequest(pages=[999]))
    assert result.status == "failed"
    assert not target.exists()
    assert "INVALID_PAGE_SELECTION" in json.dumps(result.to_dict())
    saved = json.loads(Path(result.report_path).read_text())
    assert saved["status"] == "failed"
    assert any(a["kind"] == "report" for a in saved["artifacts"])


def test_same_filename_batch_inputs_have_distinct_destinations(tmp_path):
    a, b = tmp_path / "a" / "施工图.pdf", tmp_path / "b" / "施工图.pdf"
    a.parent.mkdir()
    b.parent.mkdir()
    pdf_file(a)
    pdf_file(b)
    assert _destination(a, tmp_path / "out") != _destination(b, tmp_path / "out")
    manifest = tmp_path / "files.json"
    manifest.write_text(json.dumps([str(a), str(b)]))
    assert _collect(manifest) == [a, b]


def test_timeout_terminates_nested_worker_and_reports_reason(tmp_path):
    import psutil

    pid = tmp_path / "child.pid"
    program = (
        "import subprocess,sys,time; from pathlib import Path; "
        'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"]); '
        f"Path({str(pid)!r}).write_text(str(child.pid)); time.sleep(60)"
    )
    outcome = run_supervised(
        [sys.executable, "-c", program],
        log=tmp_path / "log",
        workdir=tmp_path,
        timeout=0.5,
        memory_mb=1024,
        disk_mb=100,
    )
    assert outcome.reason == "PAGE_TIMEOUT"
    assert outcome.elapsed_seconds < 5
    child_pid = int(pid.read_text())
    for _ in range(20):
        if not psutil.pid_exists(child_pid):
            break
        if psutil.Process(child_pid).status() == psutil.STATUS_ZOMBIE:
            break
        time.sleep(0.1)
    else:
        pytest.fail("nested conversion worker survived timeout")


def test_image_extraction_uses_native_document_after_spooling(tmp_path):
    from pdf2dxf_stable.engine.pipeline import ConstructionPDF2DXFV15, PipelineConfigV15

    picture = tmp_path / "picture.png"
    Image.new("RGB", (12, 12), "blue").save(picture)
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.draw_line((10, 10), (40, 50))
        page.insert_image((20, 20, 100, 100), filename=str(picture))
        result = ConstructionPDF2DXFV15(
            PipelineConfigV15(include_native_dimensions=False)
        ).convert_page(pdf, 0, tmp_path / "out.dxf")
        assert result.kernel_stats["image_entities"] == 1
        assert not any("failed" in w for w in result.warnings)


@pytest.mark.parametrize(
    ("mode", "color", "suffix"),
    [("CMYK", (0, 255, 255, 0), "jpg"), ("RGBA", (255, 0, 0, 80), "png")],
)
def test_image_extraction_converts_cmyk_and_preserves_soft_mask(
    tmp_path, mode, color, suffix
):
    from pdf2dxf_stable.engine.pipeline import ConstructionPDF2DXFV15, PipelineConfigV15

    picture = tmp_path / f"picture.{suffix}"
    Image.new(mode, (8, 6), color).save(picture)
    with fitz.open() as source:
        page = source.new_page(width=100, height=100)
        page.insert_image((10, 10, 90, 70), filename=str(picture))
        output = tmp_path / "out.dxf"
        result = ConstructionPDF2DXFV15(
            PipelineConfigV15(include_native_dimensions=False)
        ).convert_page(source, 0, output)
    assert result.kernel_stats["image_entities"] == 1
    assert not any("image extract failed" in warning for warning in result.warnings)

    doc = ezdxf.readfile(output)
    entity = next(iter(doc.modelspace().query("IMAGE")))
    definition = doc.entitydb[entity.dxf.image_def_handle]
    resource = Image.open(tmp_path / definition.dxf.filename).convert("RGBA")
    red, green, blue, alpha = resource.getpixel((0, 0))
    assert red > max(green, blue)
    if mode == "RGBA":
        assert 70 <= alpha <= 90
    else:
        assert alpha == 255


def test_soft_mask_replaces_opaque_pixmap_alpha(tmp_path):
    from pdf2dxf_stable.engine.pipeline import ConstructionPDF2DXFV15, PipelineConfigV15

    picture = tmp_path / "picture.jpg"
    Image.new("RGB", (8, 6), "red").save(picture)
    source, output = tmp_path / "source.pdf", tmp_path / "out.dxf"
    with fitz.open() as pdf:
        page = pdf.new_page(width=100, height=100)
        image_xref = page.insert_image((10, 10, 90, 70), filename=str(picture))
        mask_xref = pdf.get_new_xref()
        pdf.update_object(
            mask_xref,
            "<</Type/XObject/Subtype/Image/Width 8/Height 6/"
            "ColorSpace/DeviceGray/BitsPerComponent 8>>",
        )
        pdf.update_stream(mask_xref, bytes([80]) * 48, compress=True)
        pdf.xref_set_key(mask_xref, "Matte", "[0 0 0]")
        pdf.xref_set_key(image_xref, "SMask", f"{mask_xref} 0 R")
        pdf.save(source)

    with fitz.open(source) as pdf:
        info = pdf[0].get_image_info(xrefs=True)[0]
        base = fitz.Pixmap(pdf, info["xref"])
        assert base.alpha and base.samples[base.n - 1] == 255
        result = ConstructionPDF2DXFV15(
            PipelineConfigV15(include_native_dimensions=False)
        ).convert_page(pdf, 0, output)
    assert result.kernel_stats["image_entities"] == 1
    assert not any("image extract failed" in warning for warning in result.warnings)
    doc = ezdxf.readfile(output)
    entity = next(iter(doc.modelspace().query("IMAGE")))
    definition = doc.entitydb[entity.dxf.image_def_handle]
    resource = Image.open(tmp_path / definition.dxf.filename).convert("RGBA")
    assert 75 <= resource.getpixel((0, 0))[3] <= 85


def test_soft_mask_with_different_sample_dimensions_is_preserved(tmp_path):
    from pdf2dxf_stable.engine.pipeline import ConstructionPDF2DXFV15, PipelineConfigV15

    picture = tmp_path / "picture.png"
    Image.new("RGB", (2, 2), "red").save(picture)
    source, output = tmp_path / "source.pdf", tmp_path / "out.dxf"
    mask_width, mask_height = 118, 59
    mask_samples = bytes(
        0 if x < mask_width // 2 else 255
        for _y in range(mask_height)
        for x in range(mask_width)
    )
    with fitz.open() as pdf:
        page = pdf.new_page(width=100, height=100)
        image_xref = page.insert_image((10, 10, 90, 70), filename=str(picture))
        mask_xref = pdf.get_new_xref()
        pdf.update_object(
            mask_xref,
            f"<</Type/XObject/Subtype/Image/Width {mask_width}/Height {mask_height}/"
            "ColorSpace/DeviceGray/BitsPerComponent 8>>",
        )
        pdf.update_stream(mask_xref, mask_samples, compress=True)
        pdf.xref_set_key(image_xref, "SMask", f"{mask_xref} 0 R")
        pdf.save(source)

    with fitz.open(source) as pdf:
        result = ConstructionPDF2DXFV15(
            PipelineConfigV15(include_native_dimensions=False)
        ).convert_page(pdf, 0, output)
    assert result.kernel_stats["image_entities"] == 1
    assert not any("image extract failed" in warning for warning in result.warnings)
    doc = ezdxf.readfile(output)
    entity = next(iter(doc.modelspace().query("IMAGE")))
    definition = doc.entitydb[entity.dxf.image_def_handle]
    resource = Image.open(tmp_path / definition.dxf.filename).convert("RGBA")
    assert resource.size == (mask_width, mask_height)
    assert resource.getchannel("A").getextrema() == (0, 255)


def test_media_entirely_outside_page_is_skipped_without_failure(tmp_path):
    from pdf2dxf_stable.engine.pipeline import ConstructionPDF2DXFV15, PipelineConfigV15

    source, output = tmp_path / "outside.pdf", tmp_path / "out.dxf"
    with fitz.open() as pdf:
        page = pdf.new_page(width=100, height=100)
        content = pdf.get_new_xref()
        pdf.update_object(content, "<<>>")
        pdf.update_stream(
            content,
            b"q 20 0 0 20 200 200 cm BI /W 1 /H 1 /CS /RGB /BPC 8 "
            b"ID \xff\x00\x00 EI Q",
            compress=True,
        )
        pdf.xref_set_key(page.xref, "Contents", f"{content} 0 R")
        pdf.save(source)

    with fitz.open(source) as pdf:
        assert pdf[0].get_image_info(xrefs=True)[0]["xref"] == 0
        result = ConstructionPDF2DXFV15(
            PipelineConfigV15(include_native_dimensions=False)
        ).convert_page(pdf, 0, output)
    assert result.kernel_stats["outside_page_media_skipped"] == 1
    assert result.kernel_stats["image_entities"] == 0
    assert not any("failed" in warning for warning in result.warnings)


def test_image_masks_keep_each_paint_color_and_transparency(tmp_path):
    from pdf2dxf_stable.engine.pipeline import ConstructionPDF2DXFV15, PipelineConfigV15

    source, output = tmp_path / "masks.pdf", tmp_path / "out.dxf"
    with fitz.open() as pdf:
        page = pdf.new_page(width=120, height=60)
        image = pdf.get_new_xref()
        pdf.update_object(
            image,
            "<</Type/XObject/Subtype/Image/Width 2/Height 2/ImageMask true/"
            "BitsPerComponent 1/Decode [0 1]>>",
        )
        pdf.update_stream(image, bytes([0x80, 0x40]), compress=True)
        content = pdf.get_new_xref()
        pdf.update_object(content, "<<>>")
        pdf.update_stream(
            content,
            (
                b"q 1 0 0 rg 40 0 0 40 10 10 cm /M Do Q "
                b"q 0 0 1 rg 40 0 0 40 70 10 cm /M Do Q"
            ),
        )
        pdf.xref_set_key(page.xref, "Resources", f"<</XObject<</M {image} 0 R>>>>")
        pdf.xref_set_key(page.xref, "Contents", f"{content} 0 R")
        pdf.save(source)

    with fitz.open(source) as pdf:
        result = ConstructionPDF2DXFV15(
            PipelineConfigV15(include_native_dimensions=False)
        ).convert_page(pdf, 0, output)
    assert result.kernel_stats["image_entities"] == 2
    assert result.kernel_stats["image_files"] == 2
    assert not any("image extract failed" in warning for warning in result.warnings)

    doc = ezdxf.readfile(output)
    images = list(doc.modelspace().query("IMAGE"))
    definitions = [doc.entitydb[image.dxf.image_def_handle] for image in images]
    resources = [
        Image.open(tmp_path / definition.dxf.filename).convert("RGBA")
        for definition in definitions
    ]
    assert [resource.size for resource in resources] == [(2, 2), (2, 2)]
    colors = [
        {color for _, color in resource.getcolors() if color[3] > 0}
        for resource in resources
    ]
    assert all(0 in resource.getchannel("A").getextrema() for resource in resources)
    assert any(red > max(green, blue) for red, green, blue, _ in colors[0])
    assert any(blue > max(red, green) for red, green, blue, _ in colors[1])


def test_visible_raster_fallback_failure_fails_graphics_gate(tmp_path):
    path = tmp_path / "raw.dxf"
    doc = ezdxf.new("R2007")
    doc.modelspace().add_line((0, 0), (1, 0))
    doc.saveas(path)
    result = validate_dxf(
        path,
        profile="universal",
        backend_payload={
            "first": {"warnings": ["raster fallback failed seqno=1: example"]},
            "second": {"warnings": ["raster fallback failed seqno=1: example"]},
        },
    )
    assert not result["geometry_valid"]
    assert sum(
        error["code"] == "SOURCE_GRAPHICS_INCOMPLETE" for error in result["errors"]
    ) == 1
    assert sum(warning["code"] == "BACKEND_WARNINGS" for warning in result["warnings"]) == 1


def test_full_manual_conversion_keeps_dates_and_declares_user_scale(tmp_path):
    source = pdf_file(tmp_path / "source.pdf")
    result = Converter().convert(
        source,
        tmp_path / "out.dxf",
        ConversionRequest(
            scale_mode="manual",
            manual_scale=100,
            units="m",
            recover_pure_path_text=False,
        ),
    )
    assert result.status in ("ok", "degraded")
    value = result.pages[0]["universal_validation"]
    assert value["scale_status"] == "user_confirmed"
    assert value["model_ready"]
    doc = ezdxf.readfile(tmp_path / "out.dxf")
    assert doc.header["$INSUNITS"] == 6
    assert "2026-09-03" in "".join(e.dxf.text for e in doc.modelspace().query("TEXT"))
    line = next(e for e in doc.modelspace().query("LINE"))
    assert math.isclose(
        (line.dxf.end - line.dxf.start).magnitude,
        100 * 25.4 / 72 * 100 / 1000,
        rel_tol=1e-7,
    )


def test_memory_limit_kills_worker_before_it_sleeps(tmp_path):
    outcome = run_supervised(
        [
            sys.executable,
            "-c",
            "import time;data=bytearray(100*1024*1024);time.sleep(30)",
        ],
        log=tmp_path / "log",
        workdir=tmp_path,
        timeout=5,
        memory_mb=48,
        disk_mb=100,
    )
    assert outcome.reason == "MEMORY_LIMIT"
    assert outcome.elapsed_seconds < 5


def test_batch_isolates_same_names_and_invalid_pdf(tmp_path):
    from pdf2dxf_stable.batch import run_batch

    source = tmp_path / "inputs"
    for parent in ("one", "two", "broken"):
        (source / parent).mkdir(parents=True)
    pdf_file(source / "one" / "drawing.pdf")
    pdf_file(source / "two" / "drawing.pdf")
    (source / "broken" / "drawing.pdf").write_bytes(b"not a PDF")
    result = run_batch(
        source,
        tmp_path / "outputs",
        ConversionRequest(workers=2, recover_pure_path_text=False),
    )
    assert result["count"] == 3 and result["failed"] == 1
    outputs = [
        a["path"]
        for row in result["jobs"]
        for a in row["artifacts"]
        if a["kind"] == "dxf"
    ]
    assert len(outputs) == 2 and len(set(outputs)) == 2
    assert all(Path(p).is_file() for p in outputs)


def test_full_conversions_are_equal_without_shared_cache(tmp_path):
    source = pdf_file(tmp_path / "input.pdf")
    hashes = []
    for run in ("one", "two"):
        result = Converter().convert(
            source,
            tmp_path / run / "out.dxf",
            ConversionRequest(recover_pure_path_text=False),
        )
        assert result.status == "degraded"
        hashes.append(next(a.sha256 for a in result.artifacts if a.kind == "dxf"))
    assert hashes[0] == hashes[1]


def test_backend_success_without_calibration_evidence_is_not_model_ready(tmp_path):
    path = tmp_path / "drawing.dxf"
    doc = ezdxf.new("R2007")
    doc.modelspace().add_line((0, 0), (1, 0))
    doc.saveas(path)
    result = validate_dxf(path, profile="universal", backend_payload={"ok": True})
    assert result["scale_status"] == "unknown"
    assert not result["model_ready"]


def test_native_unicode_repair_preserves_trace_geometry_and_rejects_ambiguity():
    import copy

    from pdf2dxf_stable.engine.geometry.native_text import extract_text_runs

    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((20, 30), "AB")
        trace = page.get_texttrace()
        original = trace[0]["chars"][0]
        chars = list(trace[0]["chars"])
        chars[0] = (0xFFFD, *original[1:])
        trace[0]["chars"] = chars

        class Page:
            cropbox = page.cropbox

            def get_texttrace(self):
                return copy.deepcopy(trace)

            def get_text(self, *args):
                return page.get_text(*args)

        runs = extract_text_runs(Page())
        assert runs[0].text == "AB"
        assert runs[0].chars[0].origin == tuple(original[2])
        assert runs[0].chars[0].bbox == tuple(original[3])

        class Ambiguous(Page):
            def get_text(self, *args):
                raw = page.get_text(*args)
                span = raw["blocks"][0]["lines"][0]["spans"][0]
                span["chars"].append({**span["chars"][0], "c": "C"})
                return raw

        assert extract_text_runs(Ambiguous())[0].chars[0].text == "\ufffd"
