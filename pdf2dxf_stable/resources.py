"""Publish DXF external resources alongside each output using content names."""

from pathlib import Path
import os
import shutil
import tempfile
from .determinism import sha256


def atomic_copy(source, target):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=target.parent, prefix="." + target.name + ".")
    os.close(fd)
    try:
        shutil.copyfile(source, name)
        os.replace(name, target)
    finally:
        Path(name).unlink(missing_ok=True)


def relocate_images(doc, input_dxf, output_dxf, resource_root=None):
    source, target = Path(input_dxf), Path(output_dxf)
    roots = [source.parent]
    if resource_root is not None:
        roots.append(Path(resource_root))
    copied, missing = [], []
    for definition in doc.objects.query("IMAGEDEF"):
        name = str(definition.dxf.filename)
        path = Path(name.replace("\\", "/"))
        candidates = [path] if path.is_absolute() else [r / path for r in roots]
        matches = [c for c in candidates if c.is_file()]
        if not matches and not path.is_absolute():
            # Backend/finalizer moves DXFs but may leave their assets nested.
            matches = sorted(
                {
                    c
                    for root in roots
                    for c in root.rglob(path.name)
                    if c.is_file() and c.parts[-len(path.parts) :] == path.parts
                }
            )
        hashes = {sha256(c): c for c in matches}
        if len(hashes) != 1:
            missing.append(
                {
                    "code": "IMAGE_RESOURCE_MISSING"
                    if not hashes
                    else "IMAGE_RESOURCE_AMBIGUOUS",
                    "filename": name,
                    "handle": definition.dxf.handle,
                }
            )
            continue
        digest, image = next(iter(hashes.items()))
        relative = Path("images") / (digest + image.suffix.lower())
        destination = target.parent / relative
        if image.resolve() != destination.resolve():
            atomic_copy(image, destination)
        definition.dxf.filename = relative.as_posix()
        copied.append(str(destination))
    return sorted(set(copied)), missing
