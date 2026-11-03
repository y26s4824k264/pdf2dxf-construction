from __future__ import annotations
import hashlib
import mmap
import os
import re
import tempfile
import uuid
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
    # Only HEADER and OBJECTS contain the metadata we change. Avoid parsing
    # millions of ENTITIES/BLOCKS group pairs twice on large construction sheets.
    section_pattern = re.compile(
        rb"(?m)^[ \t]*0\r?\nSECTION\r?\n[ \t]*2\r?\n(HEADER|OBJECTS)\r?\n"
    )
    end_pattern = re.compile(rb"(?m)^[ \t]*0\r?\nENDSEC(?:\r?\n|$)")
    edits = []
    with path.open("rb") as source:
        if path.stat().st_size:
            with mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as data:
                sections = []
                for match in section_pattern.finditer(data):
                    end = end_pattern.search(data, match.end())
                    sections.append((match[1], match.end(), end.start() if end else len(data)))

                def pairs(start, end):
                    source.seek(start)
                    while source.tell() < end:
                        code = source.readline().rstrip(b"\r\n").strip()
                        value_start = source.tell()
                        raw = source.readline()
                        if not raw:
                            raise ValueError("Truncated ASCII DXF group pair")
                        value = raw.rstrip(b"\r\n")
                        yield code, value, value_start, value_start + len(value)

                handles = set()
                for section, start, end in sections:
                    if section != b"OBJECTS":
                        continue
                    pending = False
                    for code, value, _, _ in pairs(start, end):
                        if pending and code in (b"350", b"360"):
                            handles.add(value)
                        pending = code == b"3" and value in (
                            b"CREATED_BY_EZDXF", b"WRITTEN_BY_EZDXF"
                        )
                for section, start, end in sections:
                    variable = handle = None
                    for code, value, low, high in pairs(start, end):
                        if section == b"HEADER":
                            if code == b"9":
                                variable = value
                            elif variable in replacements:
                                edits.append((low, high, replacements[variable]))
                                variable = None
                        else:
                            if code == b"0":
                                handle = None
                            if code == b"5":
                                handle = value
                            if handle in handles and code == b"1":
                                edits.append((low, high, b"PDF2DXF deterministic serialization"))
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix="." + path.name)
    try:
        with os.fdopen(fd, "wb") as stream, path.open("rb") as source:
            line_count = 0
            size = path.stat().st_size
            source.seek(max(0, size - 1))
            last = source.read(1)
            source.seek(0)

            def copy_until(end):
                nonlocal line_count
                carry = b""
                while source.tell() < end:
                    chunk = source.read(min(1024 * 1024, end - source.tell()))
                    line_count += chunk.count(b"\n")
                    chunk = carry + chunk
                    carry = b""
                    if chunk.endswith(b"\r") and source.tell() < end:
                        chunk, carry = chunk[:-1], b"\r"
                    if end == size and source.tell() == size and last != b"\n":
                        chunk = chunk.rstrip(b"\r")
                    stream.write(chunk.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
                if carry:
                    stream.write(carry)

            for low, high, value in sorted(edits):
                copy_until(low)
                source.seek(high)
                stream.write(value)
            copy_until(size)
            if (line_count + int(bool(last) and last != b"\n")) % 2:
                raise ValueError("Truncated ASCII DXF group pair")
            if last and last != b"\n":
                stream.write(b"\r\n")
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
