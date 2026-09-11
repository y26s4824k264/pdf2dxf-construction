"""PDF producers may supply a stencil's opacity channel as an SMask."""

import ezdxf
import fitz
import pytest

from pdf2dxf_stable.engine.pipeline import ConstructionPDF2DXFV15, PipelineConfigV15


@pytest.mark.parametrize("decode", ["[0 1]", "[1 0]"])
@pytest.mark.parametrize("factor", [1, 2])
@pytest.mark.parametrize("clipped", [False, True])
def test_stencil_soft_mask_preserves_rendered_pixels(tmp_path, decode, factor, clipped):
    source, output = tmp_path / "source.pdf", tmp_path / "out.dxf"
    rect = fitz.Rect(10, 10, 18, 12)
    width, height = 8 * factor, 2 * factor
    with fitz.open() as pdf:
        page = pdf.new_page(width=30, height=30)
        color = fitz.Pixmap(fitz.csRGB, 8, 2, bytes([200, 30, 60]) * 16, False)
        image = page.insert_image(rect, pixmap=color)
        mask = pdf.get_new_xref()
        pdf.update_object(
            mask,
            f"<</Type/XObject/Subtype/Image/Width {width}/Height {height}/"
            f"ImageMask true/ColorSpace/DeviceGray/BitsPerComponent 1/Decode {decode}>>",
        )
        pdf.update_stream(mask, bytes([0xA5, 0x3C]) * factor * factor)
        pdf.xref_set_key(image, "SMask", f"{mask} 0 R")
        pdf.save(source)

    with fitz.open(source) as pdf:
        opacity = fitz.Pixmap(pdf, mask)
        assert opacity.colorspace is None and opacity.alpha == opacity.n == 1
        assert set(opacity.samples) == {0, 255}
        expected = pdf[0].get_pixmap(
            clip=rect, matrix=fitz.Matrix(factor, factor), alpha=True
        )
        if clipped:
            content = pdf.get_new_xref()
            pdf.update_object(content, "<<>>")
            pdf.update_stream(
                content,
                b"q 10 18 4 2 re W n\n" + pdf[0].read_contents() + b"\nQ",
            )
            pdf[0].set_contents(content)
            source = tmp_path / "clipped.pdf"
            pdf.save(source)
    with fitz.open(source) as pdf:
        result = ConstructionPDF2DXFV15(
            PipelineConfigV15(include_native_dimensions=False)
        ).convert_page(pdf, 0, output)

    assert result.kernel_stats["image_entities"] == 1
    assert not any("failed" in warning for warning in result.warnings)
    doc = ezdxf.readfile(output)
    entity, = doc.modelspace().query("IMAGE")
    definition = doc.entitydb[entity.dxf.image_def_handle]
    actual = fitz.Pixmap(str(tmp_path / definition.dxf.filename))
    assert (actual.width, actual.height) == (width, height)
    assert actual.alpha == 1
    assert actual.samples == expected.samples
    assert tuple(definition.dxf.image_size)[:2] == (width, height)
    assert tuple(entity.dxf.image_size)[:2] == (width, height)
    assert entity.dxf.u_pixel.magnitude * actual.width == pytest.approx(
        rect.width * 25.4 / 72
    )
    assert entity.dxf.v_pixel.magnitude * actual.height == pytest.approx(
        rect.height * 25.4 / 72
    )
    if clipped:
        assert result.kernel_stats["clipped_image_entities"] == 1
        assert max(p.x for p in entity.pixel_boundary_path()) == pytest.approx(
            width / 2 - 0.5
        )
    assert not doc.audit().has_errors


@pytest.mark.parametrize("rotation", [0, 90])
def test_media_clips_follow_each_paint_and_restore_scope(tmp_path, rotation):
    source, output = tmp_path / "scopes.pdf", tmp_path / "scopes.dxf"
    with fitz.open() as pdf:
        page = pdf.new_page(width=32, height=30)
        pixels = fitz.Pixmap(fitz.csRGB, 8, 2, bytes([20, 60, 180]) * 16, False)
        image = page.insert_image((2, 10, 10, 12), pixmap=pixels)
        content = pdf.get_new_xref()
        pdf.update_object(content, "<<>>")
        pdf.update_stream(content, (
            b"q 2 18 4 2 re W n 8 0 0 2 2 18 cm /I Do Q\n"
            b"q 8 0 0 2 12 18 cm /I Do Q\n"
            b"q 26 18 4 2 re W n 8 0 0 2 22 18 cm /I Do Q"
        ))
        pdf.xref_set_key(page.xref, "Resources", f"<</XObject<</I {image} 0 R>>>>")
        page.set_contents(content)
        page.set_rotation(rotation)
        pdf.save(source)
    with fitz.open(source) as pdf:
        result = ConstructionPDF2DXFV15(
            PipelineConfigV15(include_native_dimensions=False)
        ).convert_page(pdf, 0, output)
    assert not any("failed" in warning for warning in result.warnings)
    assert result.kernel_stats["image_entities"] == 3
    assert result.kernel_stats["clipped_image_entities"] == 2
    images = list(ezdxf.readfile(output).modelspace().query("IMAGE"))
    spans = [(min(p.x for p in e.pixel_boundary_path()),
              max(p.x for p in e.pixel_boundary_path())) for e in images]
    assert spans == [(-0.5, 3.5), (-0.5, 7.5), (3.5, 7.5)]


def test_completely_clipped_image_is_not_painted(tmp_path):
    source, output = tmp_path / "empty.pdf", tmp_path / "empty.dxf"
    with fitz.open() as pdf:
        page = pdf.new_page(width=32, height=30)
        pixels = fitz.Pixmap(fitz.csRGB, 8, 2, bytes([20, 60, 180]) * 16, False)
        image = page.insert_image((2, 10, 10, 12), pixmap=pixels)
        content = pdf.get_new_xref()
        pdf.update_object(content, "<<>>")
        pdf.update_stream(content,
            b"q 2 18 4 2 re W n 20 18 4 2 re W n 8 0 0 2 2 18 cm /I Do Q")
        pdf.xref_set_key(page.xref, "Resources", f"<</XObject<</I {image} 0 R>>>>")
        page.set_contents(content)
        pdf.save(source)
    with fitz.open(source) as pdf:
        assert not any(pdf[0].get_pixmap(alpha=True).samples)
        result = ConstructionPDF2DXFV15(
            PipelineConfigV15(include_native_dimensions=False)
        ).convert_page(pdf, 0, output)
    assert result.kernel_stats["image_entities"] == 0
    assert not any("failed" in warning for warning in result.warnings)


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit])
def test_media_clip_callback_preserves_cancellation(monkeypatch, error_type):
    from pdf2dxf_stable.engine.geometry import base
    from pdf2dxf_stable.engine.geometry.media_clipping import collect_media_clips

    def interrupt(*args):
        raise error_type("cancel media extraction")

    monkeypatch.setattr(base, "clip_state_from_record", interrupt)
    with fitz.open() as pdf:
        page = pdf.new_page(width=32, height=30)
        pixels = fitz.Pixmap(fitz.csRGB, 8, 2, bytes([20, 60, 180]) * 16, False)
        page.insert_image((2, 10, 10, 12), pixmap=pixels)
        content = pdf.get_new_xref()
        pdf.update_object(content, "<<>>")
        pdf.update_stream(content,
            b"q 2 18 4 2 re W n\n" + page.read_contents() + b"\nQ")
        page.set_contents(content)
        drawings = page.get_cdrawings(extended=True)
        with pytest.raises(error_type, match="cancel media extraction"):
            collect_media_clips(page, drawings, base.KernelConfig(), base.KernelStats())
