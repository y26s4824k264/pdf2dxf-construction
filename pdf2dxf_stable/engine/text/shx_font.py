"""Compile explicitly encoded basic SHX bigfonts into persisted stroke geometry."""

from pathlib import Path
import struct

import numpy as np
from ezdxf.fonts.shapefile import DataReader, ShapeRenderer, parse_shape_codes
from ezdxf.math import Vec3
from ezdxf.path import Path as DxfPath

from ...paths import protect_inputs
from . import font_catalog as fc
from .vector_catalog import (
    MAX_GLYPH_POINTS,
    MAX_PATHS,
    MAX_POINTS,
    MAX_ROWS,
    _descriptor,
    _join_stroke_paths,
    _normalise,
    _write_vector_arrays,
)

SIGNATURE = b"AutoCAD-86 bigfont 1.0\r\n\x1a"
STROKE_POLICY = "open_stroke_paths_v1"


def _instructions(codes):
    i = 0
    while i < len(codes):
        start = i
        op = codes[i]
        i += 1
        if op == 0:
            return
        if op in (3, 4, 7):
            i += 1
        elif op in (8, 10):
            i += 2
        elif op == 11:
            i += 5
        elif op == 12:
            i += 3
        elif op in (9, 13):
            while True:
                if i + 2 > len(codes):
                    raise ValueError("truncated stroke instruction")
                x, y = codes[i : i + 2]
                i += 2
                if not x and not y:
                    break
                if op == 13:
                    i += 1
        elif op not in (1, 2, 5, 6, 14) and op < 16:
            raise ValueError("unsupported stroke instruction")
        if i > len(codes):
            raise ValueError("truncated stroke instruction")
        yield op, codes[start + 1 : i]
    raise ValueError("unterminated stroke program")


class Bigfont:
    def __init__(self, data):
        if not data.startswith(SIGNATURE) or len(data) > 16 * 1024 * 1024:
            raise ValueError("only bounded basic AutoCAD-86 bigfont 1.0 is supported")
        pos = len(SIGNATURE)
        try:
            size, count, ranges = struct.unpack_from("<HHH", data, pos)
            pos += 6
            if size != 8 or not 1 <= count <= 65535 or not 1 <= ranges <= 64:
                raise ValueError("invalid bigfont index")
            intervals = [
                struct.unpack_from("<HH", data, pos + 4 * i) for i in range(ranges)
            ]
            if any(not 0 <= a <= b <= 255 for a, b in intervals):
                raise ValueError("invalid bigfont lead-byte range")
            pos += 4 * ranges
            end = pos + count * 8
            if end > len(data):
                raise ValueError("truncated bigfont index")
            self.ranges = intervals
            records = {}
            for j in range(count):
                code, length, offset = struct.unpack_from("<HHI", data, pos + 8 * j)
                if not length:
                    continue
                if code in records or offset < end or offset + length > len(data):
                    raise ValueError("invalid bigfont record")
                name, program = data[offset : offset + length].split(b"\0", 1)
                records[code] = (name, program)
            self.name, definition = records.pop(0)
            if (
                len(definition) != 4
                or definition[-1] != 0
                or definition[2] not in (0, 2)
                or definition[0] < 16
            ):
                raise ValueError("unsupported bigfont definition")
            self.height, self.below, self.mode = definition[:3]
            self.codes = tuple(records)
            self.programs = {}
            self.errors = {}
            for code, (_, program) in records.items():
                try:
                    self.programs[code] = tuple(
                        _instructions(parse_shape_codes(DataReader(program)))
                    )
                except (IndexError, ValueError) as exc:
                    self.errors[code] = str(exc)
            self._expanded = {}
        except (struct.error, KeyError, IndexError) as exc:
            raise ValueError("truncated bigfont records") from exc

    def expand(self, code, active=()):
        if code in active or len(active) >= 16:
            raise ValueError("cyclic or deep bigfont subshape")
        if code in self._expanded:
            return self._expanded[code]
        result = []
        skip = False
        for op, args in self.programs[code]:
            if skip:
                skip = False
                continue
            if op == 14:
                skip = self.mode == 2
                continue
            if op == 7:
                if args[0] == 0:
                    raise ValueError("extended bigfont subshapes are unsupported")
                result.extend(self.expand(args[0], (*active, code)))
            else:
                result.extend((op, *args))
            if len(result) > 65536:
                raise ValueError("expanded bigfont exceeds limits")
        self._expanded[code] = tuple(result)
        return self._expanded[code]

    def glyph(self, code):
        codes = (*self.expand(code), 0)
        path = DxfPath(Vec3())
        renderer = ShapeRenderer(path, lambda _: codes)
        renderer.render(code)
        paths = tuple(
            np.asarray(
                [(v.x, v.y) for v in p.flattening(self.height / 4096)], dtype=float
            )
            for p in path.sub_paths()
            if len(p)
        )
        paths = tuple(p for p in paths if len(p) >= 2 and np.any(p != p[0]))
        if renderer._location_stack:
            raise ValueError("unbalanced bigfont location stack")
        if abs(renderer.current_location.y) > self.height / 4096:
            raise ValueError("nonhorizontal bigfont advance")
        return paths, renderer.current_location.x


def build_shx_vector_catalog(
    font_path, output, *, encoding=None, codepoints=None, progress=None
):
    if encoding != "gbk":
        raise ValueError(
            "SHX vectors require explicit encoding=gbk; filenames do not identify Unicode"
        )
    source = Path(font_path).expanduser().resolve()
    target = Path(output).expanduser().resolve()
    protect_inputs(target, [source])
    if target.suffix.lower() != ".p2dvec":
        raise ValueError("vector font catalogs must end in .p2dvec")
    if source.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("SHX source exceeds font size limit")
    data = source.read_bytes()
    font = Bigfont(data)
    mapped = {}
    for code in font.codes:
        if code < 256 or not any(a <= code >> 8 <= b for a, b in font.ranges):
            continue
        try:
            char = code.to_bytes(2, "big").decode(encoding)
            if (
                len(char) == 1
                and fc.is_han_character(char)
                and char.encode(encoding) == code.to_bytes(2, "big")
            ):
                mapped[ord(char)] = code
        except (UnicodeError, OverflowError):
            continue
    requested = sorted(
        set(mapped)
        if codepoints is None
        else set(map(int, codepoints)).intersection(mapped)
    )
    coords = []
    po = [0]
    go = [0]
    cps = []
    metrics = []
    aspects = []
    descriptors = []
    skipped = 0
    max_source_paths = 0
    for done, cp in enumerate(requested, 1):
        try:
            paths, advance = font.glyph(mapped[cp])
            max_source_paths = max(max_source_paths, len(paths))
            paths = _join_stroke_paths(paths)
            normal, low, extent = _normalise(paths)
            if (
                not np.isfinite(advance)
                or not 0 < advance
                or len(paths) > fc.MAX_CONTOURS
                or sum(map(len, paths)) > MAX_GLYPH_POINTS
            ):
                raise ValueError("unsupported stroke glyph geometry")
        except (ValueError, IndexError, KeyError, ZeroDivisionError, OverflowError):
            skipped += 1
            continue
        if (
            len(cps) >= MAX_ROWS
            or po[-1] + sum(map(len, paths)) > MAX_POINTS
            or len(po) - 1 + len(paths) > MAX_PATHS
        ):
            raise fc.FontCatalogError("vector font catalog exceeds geometry limits")
        for p in normal:
            coords.append(p)
            po.append(po[-1] + len(p))
        go.append(len(po) - 1)
        cps.append(cp)
        em = font.height
        metrics.append((*low / em, *(low + extent) / em, advance / em))
        aspects.append(float(extent[0] / extent[1]))
        descriptors.append(_descriptor(normal))
        if progress:
            progress(done, len(requested))
    if not cps:
        raise fc.FontCatalogError("font has no supported Han stroke programs")
    arrays = {
        "points.npy": np.vstack(coords).astype("<f4"),
        "path_offsets.npy": np.asarray(po, dtype="<u4"),
        "glyph_offsets.npy": np.asarray(go, dtype="<u4"),
        "codepoints.npy": np.asarray(cps, dtype="<u4"),
        "metrics.npy": np.asarray(metrics, dtype="<f4"),
        "aspects.npy": np.asarray(aspects, dtype="<f4"),
        "descriptors.npy": np.asarray(descriptors, dtype="<f4"),
    }
    metadata = {
        "sha256": fc._sha256_path(source),
        "face_index": 0,
        "face_count": 1,
        "units_per_em": font.height,
        "family": font.name.decode("ascii", errors="replace"),
        "source_file": source.name,
        "source_format": "AutoCAD-86 bigfont 1.0",
        "source_encoding": "gbk",
        "unicode_mapping": "strict_gbk_roundtrip",
        "renderer": "ezdxf_with_bounded_inline_horizontal_subshapes",
        "unsupported_programs": len(font.errors),
        "path_join_policy": "exact_sequential_endpoint_v1",
        "max_source_paths": max_source_paths,
    }
    return _write_vector_arrays(
        target, metadata, arrays, skipped, outline_policy=STROKE_POLICY
    )
