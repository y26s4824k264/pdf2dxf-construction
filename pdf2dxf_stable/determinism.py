from __future__ import annotations
import hashlib, os, tempfile, uuid
from pathlib import Path


def deterministic_uuid(seed, suffix):
    return "{" + str(uuid.uuid5(uuid.NAMESPACE_URL, seed + "#" + suffix)).upper() + "}"


def _pairs(path):
    with Path(path).open("rb") as stream:
        while True:
            code = stream.readline()
            if not code:
                return
            value = stream.readline()
            if not value:
                raise ValueError("Truncated ASCII DXF group pair")
            yield code.rstrip(b"\r\n"), value.rstrip(b"\r\n")


def canonicalize_ascii_dxf(path, *, seed):
    """Normalize ONLY header metadata and the two ezdxf metadata dictionary values.

    Work on bytes: R12 codepages, TEXT, MTEXT, XDATA, dates, paths and UUID-shaped
    user content must survive verbatim. No shared output cache is used.
    """
    path = Path(path)
    metadata_handles = set()
    pending = False
    section = b""
    expect_section = False
    for code, value in _pairs(path):
        c = code.strip()
        if expect_section:
            section = value
            expect_section = False
        if c == b"0" and value == b"SECTION":
            expect_section = True
        if section == b"OBJECTS":
            if pending and c in (b"350", b"360"):
                metadata_handles.add(value)
            pending = c == b"3" and value in (b"CREATED_BY_EZDXF", b"WRITTEN_BY_EZDXF")
    replacements = {
        key.encode(): b"2451544.5"
        for key in ("$TDCREATE", "$TDUPDATE", "$TDUCREATE", "$TDUUPDATE")
    }
    replacements.update(
        {
            b"$TDINDWG": b"0.0",
            b"$TDUSRTIMER": b"0.0",
            b"$FINGERPRINTGUID": deterministic_uuid(seed, "fingerprint").encode(),
            b"$VERSIONGUID": deterministic_uuid(seed, "version").encode(),
        }
    )
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix="." + path.name)
    try:
        with os.fdopen(fd, "wb") as stream:
            section, variable, handle = b"", None, None
            expect_section = False
            for code, value in _pairs(path):
                c = code.strip()
                if expect_section:
                    section = value
                    expect_section = False
                if c == b"0":
                    handle = None
                    if value == b"SECTION":
                        expect_section = True
                if section == b"HEADER":
                    if c == b"9":
                        variable = value
                    elif variable in replacements:
                        value = replacements[variable]
                        variable = None
                elif section == b"OBJECTS":
                    if c == b"5":
                        handle = value
                    if handle in metadata_handles and c == b"1":
                        value = b"PDF2DXF deterministic serialization"
                stream.write(code + b"\r\n" + value + b"\r\n")
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
