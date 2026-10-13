"""Verified PNG attachments carried by IMAGEDEF extension XRECORDs.

IMAGE remains a standard external-image DXF entity. An application storing only
DXF bytes can retain its lossless PNG payload here, then restore sidecars or
export an ordinary DXF+PNG zip for CAD programs. No network paths are followed.
"""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
import re
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from PIL import Image

RECORD_KEY = "PDF2DXF_PNG"
MAX_IMAGE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
_NAME = re.compile(r"images/([0-9a-f]{64})\.png\Z")


def _verify_png(content, image_size=None):
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise ValueError("DXF_IMAGE_ATTACHMENT_SIZE_INVALID")
    try:
        with Image.open(BytesIO(content)) as image:
            if image.format != "PNG" or image.width * image.height > MAX_IMAGE_PIXELS:
                raise ValueError("DXF_IMAGE_ATTACHMENT_FORMAT_INVALID")
            if image_size and tuple(image.size) != tuple(image_size)[:2]:
                raise ValueError("DXF_IMAGE_ATTACHMENT_DIMENSIONS_MISMATCH")
            image.verify()
    except (OSError, Image.DecompressionBombError) as error:
        raise ValueError("DXF_IMAGE_ATTACHMENT_FORMAT_INVALID") from error


def _definitions(document):
    return [
        e
        for e in document.entitydb.values()
        if e.is_alive and e.dxftype() == "IMAGEDEF"
    ]


def embedded_image(definition):
    if not definition.has_extension_dict:
        return None
    dictionary = definition.get_extension_dict()
    if RECORD_KEY not in dictionary:
        return None
    record = dictionary[RECORD_KEY]
    if record.dxftype() != "XRECORD":
        raise ValueError("DXF_IMAGE_ATTACHMENT_RECORD_INVALID")
    tags = list(record.tags)
    if (
        len(tags) < 4
        or [t.code for t in tags[:3]] != [1, 2, 90]
        or tags[0].value != "png-v1"
    ):
        raise ValueError("DXF_IMAGE_ATTACHMENT_RECORD_INVALID")
    name, size = tags[1].value, tags[2].value
    match = _NAME.fullmatch(name)
    if not match or not isinstance(size, int) or not 0 < size <= MAX_IMAGE_BYTES:
        raise ValueError("DXF_IMAGE_ATTACHMENT_RECORD_INVALID")
    chunks = tags[3:]
    if any(t.code != 310 or not isinstance(t.value, bytes) for t in chunks):
        raise ValueError("DXF_IMAGE_ATTACHMENT_RECORD_INVALID")
    if sum(len(t.value) for t in chunks) != size:
        raise ValueError("DXF_IMAGE_ATTACHMENT_SIZE_INVALID")
    content = b"".join(t.value for t in chunks)
    if (
        hashlib.sha256(content).hexdigest() != match[1]
        or definition.dxf.filename != name
    ):
        raise ValueError("DXF_IMAGE_ATTACHMENT_HASH_MISMATCH")
    _verify_png(content, definition.dxf.image_size)
    return name, content


def embed_image_files(document, root):
    root = Path(root).resolve()
    total = 0
    for definition in _definitions(document):
        existing = embedded_image(definition)
        if existing:
            total += len(existing[1])
            continue
        filename = str(definition.dxf.filename)
        # Converter sidecars must stay in its reviewed output directory. Refuse
        # symlinks as well as absolute paths, URLs and parent traversal.
        relative = Path(filename.replace("\\", "/"))
        if relative.is_absolute() or ".." in relative.parts or ":" in filename:
            raise ValueError("DXF_IMAGE_ATTACHMENT_PATH_INVALID")
        path = root / relative
        if any(p.is_symlink() for p in (path, *path.parents) if p != root.parent):
            raise ValueError("DXF_IMAGE_ATTACHMENT_PATH_INVALID")
        if not path.is_file() or not path.resolve().is_relative_to(root):
            raise ValueError("DXF_IMAGE_ATTACHMENT_MISSING")
        if path.stat().st_size > MAX_IMAGE_BYTES:
            raise ValueError("DXF_IMAGE_ATTACHMENT_SIZE_INVALID")
        content = path.read_bytes()
        _verify_png(content, definition.dxf.image_size)
        total += len(content)
        if total > MAX_TOTAL_BYTES:
            raise ValueError("DXF_IMAGE_ATTACHMENT_TOTAL_LIMIT")
        name = f"images/{hashlib.sha256(content).hexdigest()}.png"
        record = definition.new_extension_dict().add_xrecord(RECORD_KEY)
        record.reset(
            [
                (1, "png-v1"),
                (2, name),
                (90, len(content)),
                *[(310, content[i : i + 127]) for i in range(0, len(content), 127)],
            ]
        )
        definition.dxf.filename = name
    return embedded_images(document)


def copy_embedded_image(source, target):
    value = embedded_image(source)
    if value is not None:
        target.new_extension_dict().add_xrecord(RECORD_KEY).reset(
            source.get_extension_dict()[RECORD_KEY].tags
        )


def embedded_images(document):
    result, total = {}, 0
    for definition in _definitions(document):
        value = embedded_image(definition)
        if value is None:
            continue
        name, content = value
        if name not in result:
            total += len(content)
            if total > MAX_TOTAL_BYTES:
                raise ValueError("DXF_IMAGE_ATTACHMENT_TOTAL_LIMIT")
            result[name] = content
    return result


def materialize_images(document, root):
    root = Path(root).resolve()
    images = embedded_images(document)
    for name, content in images.items():
        destination = root / name
        if destination.is_symlink() or (root / "images").is_symlink():
            raise ValueError("DXF_IMAGE_ATTACHMENT_PATH_INVALID")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    return images


def dxf_image_bundle(document, content, filename="frame.dxf"):
    """Deterministic, interoperable archive with normal relative IMAGEDEF paths."""
    if Path(filename).name != filename or not filename.endswith(".dxf"):
        raise ValueError("DXF_BUNDLE_NAME_INVALID")
    stream = BytesIO()
    with ZipFile(stream, "w", compression=ZIP_STORED) as archive:
        for name, data in [
            (filename, content),
            *sorted(embedded_images(document).items()),
        ]:
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    return stream.getvalue()
