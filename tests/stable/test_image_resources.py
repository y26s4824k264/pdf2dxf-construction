"""Attachment bytes survive saving, temp cleanup and ordinary CAD zip export."""

import hashlib
from io import BytesIO
from zipfile import ZipFile

import ezdxf
from PIL import Image
import pytest

from pdf2dxf_stable.image_resources import (
    copy_embedded_image,
    dxf_image_bundle,
    embedded_images,
    embed_image_files,
    materialize_images,
)


def image_document(root):
    root.mkdir(parents=True, exist_ok=True)
    path = root / "original.png"
    Image.new("RGBA", (8, 6), (255, 0, 0, 128)).save(path)
    doc = ezdxf.new("R2018")
    definition = doc.add_image_def("original.png", (8, 6))
    doc.modelspace().add_image(definition, (0, 0), (20, 15))
    return doc, path, definition


def test_lossless_attachment_roundtrip_and_zip(tmp_path):
    doc, original, _ = image_document(tmp_path / "converter")
    content = original.read_bytes()
    name = f"images/{hashlib.sha256(content).hexdigest()}.png"
    embed_image_files(doc, original.parent)
    dxf = tmp_path / "stored.dxf"
    doc.saveas(dxf)
    original.unlink()
    saved = ezdxf.readfile(dxf)
    assert embedded_images(saved) == {name: content}
    materialize_images(saved, tmp_path / "fresh")
    assert (tmp_path / "fresh" / name).read_bytes() == content
    bundle = dxf_image_bundle(saved, dxf.read_bytes())
    assert bundle == dxf_image_bundle(saved, dxf.read_bytes())
    with ZipFile(BytesIO(bundle)) as archive:
        assert archive.namelist() == ["frame.dxf", name]
        assert archive.read(name) == content
    assert not saved.audit().has_errors


@pytest.mark.parametrize(
    "filename", ["../secret.png", "/etc/passwd", "https://example.com/image.png"]
)
def test_attachment_cannot_follow_external_paths(tmp_path, filename):
    doc, original, definition = image_document(tmp_path)
    definition.dxf.filename = filename
    with pytest.raises(ValueError, match="PATH_INVALID"):
        embed_image_files(doc, original.parent)


def test_corrupted_or_missing_payload_is_rejected(tmp_path):
    doc, original, definition = image_document(tmp_path)
    embed_image_files(doc, original.parent)
    definition.dxf.filename = "images/" + "0" * 64 + ".png"
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        embedded_images(doc)


def test_embedded_definition_copy_survives_reopen(tmp_path):
    doc, original, definition = image_document(tmp_path)
    expected = embed_image_files(doc, original.parent)
    target = ezdxf.new("R2018")
    copied = target.add_image_def(definition.dxf.filename, (8, 6))
    copy_embedded_image(definition, copied)
    target.modelspace().add_image(copied, (0, 0), (20, 15))
    path = tmp_path / "child.dxf"
    target.saveas(path)
    assert embedded_images(ezdxf.readfile(path)) == expected
