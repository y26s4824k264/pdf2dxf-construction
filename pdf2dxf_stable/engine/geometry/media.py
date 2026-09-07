from __future__ import annotations

"""Raster media, shading fallback, and DXF IMAGE clipping helpers."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import fitz
import numpy as np
from PIL import Image, ImageDraw
from shapely.geometry import Polygon, MultiPolygon, box
from shapely.validation import make_valid


@dataclass(slots=True)
class MediaOccurrence:
    index: int
    seqno: int
    kind: str
    bbox: tuple[float, float, float, float]
    layer: str


@dataclass(slots=True)
class ImageMaskPaint:
    index: int
    bbox: tuple[float, float, float, float]
    path: Path
    width: int
    height: int


@dataclass(slots=True)
class MediaConfig:
    include_shadings: bool = True
    shading_subdir: str = "shadings"
    clip_images: bool = True
    max_image_clip_vertices: int = 192
    shading_render_scale: float = 2.0
    skip_unclipped_full_page_shading: bool = True


def extract_image_pixmap(
    pdf: fitz.Document, xref: int, soft_mask_xref: int = 0
) -> fitz.Pixmap:
    """Load an image as PNG-compatible pixels and apply its PDF soft mask."""
    pix = fitz.Pixmap(pdf, xref)
    if pix.colorspace is None:
        raise RuntimeError("unsupported image colorspace")
    if soft_mask_xref and pix.alpha:
        pix = fitz.Pixmap(pix, 0)
    if pix.colorspace.n not in (1, 3) or (soft_mask_xref and pix.colorspace.n != 3):
        pix = fitz.Pixmap(fitz.csRGB, pix)
    if soft_mask_xref:
        mask = fitz.Pixmap(pdf, soft_mask_xref)
        if mask.alpha:
            mask = fitz.Pixmap(mask, 0)
        if mask.colorspace is None:
            raise RuntimeError("unsupported soft mask colorspace")
        if mask.colorspace.n != 1:
            mask = fitz.Pixmap(fitz.csGRAY, mask)
        if (mask.width, mask.height) != (pix.width, pix.height):
            # Image and soft-mask samples share normalized image space. Some
            # producers put the detail in a larger mask over a tiny base image.
            width = max(mask.width, pix.width)
            height = max(mask.height, pix.height)
            pix = fitz.Pixmap(pix, width, height)
            mask = fitz.Pixmap(mask, width, height)
        pix = fitz.Pixmap(pix, mask)
    return pix


def _bbox_distance(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(abs(float(a[i]) - float(b[i])) for i in range(4))


def enumerate_media_occurrences(
    page: fitz.Page, infos: list[dict[str, Any]]
) -> list[MediaOccurrence | None]:
    try:
        bboxlog = list(page.get_bboxlog(layers=True))
    except Exception:
        bboxlog = []
    entries: list[MediaOccurrence] = []
    for seqno, row in enumerate(bboxlog):
        if len(row) < 2 or str(row[0]) not in {
            "fill-image",
            "fill-imgmask",
            "fill-shade",
        }:
            continue
        try:
            bbox = tuple(map(float, row[1]))
        except Exception:
            continue
        entries.append(
            MediaOccurrence(
                len(entries),
                seqno,
                "fill-image" if str(row[0]) == "fill-imgmask" else str(row[0]),
                bbox,
                str(row[2] if len(row) > 2 else "" or ""),
            )
        )
    out: list[MediaOccurrence | None] = []
    unused = set(range(len(entries)))
    for i, info in enumerate(infos):
        bbox = tuple(map(float, info.get("bbox", (0, 0, 0, 0))))
        chosen: int | None = None
        if i < len(entries) and i in unused:
            e = entries[i]
            span = max(abs(bbox[2] - bbox[0]), abs(bbox[3] - bbox[1]), 1.0)
            if _bbox_distance(bbox, e.bbox) <= span * 0.08 + 2.0:
                chosen = i
        if chosen is None and unused:
            j = min(unused, key=lambda k: _bbox_distance(bbox, entries[k].bbox))
            span = max(abs(bbox[2] - bbox[0]), abs(bbox[3] - bbox[1]), 1.0)
            if _bbox_distance(bbox, entries[j].bbox) <= span * 0.25 + 8.0:
                chosen = j
        if chosen is None:
            out.append(None)
        else:
            unused.discard(chosen)
            out.append(entries[chosen])
    return out


def render_image_mask_paints(
    page: fitz.Page,
    infos: list[dict[str, Any]],
    output_dir: str | Path,
    prefix: str,
) -> list[ImageMaskPaint]:
    """Render PDF stencil masks with their actual paint color and opacity."""
    mask_infos = [info for info in infos if int(info.get("colorspace", -1)) == 0]
    if not mask_infos:
        return []

    from fitz import mupdf

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    class Device(mupdf.FzDevice2):
        def __init__(self):
            super().__init__()
            self.use_virtual_fill_image_mask()
            self.rows: list[ImageMaskPaint] = []
            self.failure: Exception | None = None

        def fill_image_mask(
            self, ctx, image, ctm, colorspace, color, alpha, color_params
        ):
            if self.failure is not None:
                return
            path = None
            try:
                index = len(self.rows)
                info = mask_infos[index]
                width, height = int(info["width"]), int(info["height"])
                pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, width, height), True)
                pix.clear_with()
                draw = mupdf.fz_new_draw_device(mupdf.FzMatrix(), pix.this)
                try:
                    matrix = mupdf.FzMatrix(width, 0, 0, height, 0, 0)
                    mupdf.ll_fz_fill_image_mask(
                        draw.m_internal,
                        image,
                        matrix.internal(),
                        colorspace,
                        color,
                        alpha,
                        color_params,
                    )
                finally:
                    mupdf.fz_close_device(draw)
                path = output_dir / f"{prefix}_mask_{index:03d}.png"
                pix.save(str(path))
                rect = mupdf.ll_fz_transform_rect(mupdf.fz_unit_rect, ctm)
                bbox = tuple(map(float, (rect.x0, rect.y0, rect.x1, rect.y1)))
                self.rows.append(ImageMaskPaint(index, bbox, path, width, height))
            except Exception as exc:
                if path is not None:
                    path.unlink(missing_ok=True)
                self.failure = exc

    old_rotation = page.rotation
    if old_rotation:
        page.set_rotation(0)
    device = Device()
    try:
        mupdf.fz_run_page(page.this, device, mupdf.FzMatrix(), mupdf.FzCookie())
    finally:
        try:
            mupdf.fz_close_device(device)
        finally:
            if old_rotation:
                page.set_rotation(old_rotation)
    if device.failure is not None:
        for row in device.rows:
            row.path.unlink(missing_ok=True)
        raise device.failure
    if len(device.rows) != len(mask_infos):
        raise RuntimeError(
            f"image mask occurrence mismatch: {len(device.rows)} paints for "
            f"{len(mask_infos)} image records"
        )
    for paint, info in zip(device.rows, mask_infos, strict=True):
        expected = tuple(map(float, info.get("bbox", (0, 0, 0, 0))))
        span = max(expected[2] - expected[0], expected[3] - expected[1], 1.0)
        if _bbox_distance(paint.bbox, expected) > span * 0.01 + 1.0:
            raise RuntimeError("image mask paint order does not match image records")
    return device.rows


def image_footprint_pdf(info: dict[str, Any]) -> Polygon | None:
    matrix = info.get("transform")
    if not matrix or len(matrix) != 6:
        return None
    try:
        a, b, c, d, e, f = map(float, matrix)
        p = Polygon([(e, f), (e + a, f + b), (e + a + c, f + b + d), (e + c, f + d)])
        if not p.is_valid:
            p = make_valid(p)
        return p if isinstance(p, Polygon) and not p.is_empty else None
    except Exception:
        return None


def _largest_polygon(geom: Any) -> Polygon | None:
    if geom is None or geom.is_empty:
        return None
    if isinstance(geom, Polygon):
        return geom
    if isinstance(geom, MultiPolygon):
        return max(geom.geoms, key=lambda p: p.area, default=None)
    try:
        return max(
            (g for g in geom.geoms if isinstance(g, Polygon)),
            key=lambda p: p.area,
            default=None,
        )
    except Exception:
        return None


def _simplify_ring(
    coords: list[tuple[float, float]], max_vertices: int
) -> list[tuple[float, float]]:
    if len(coords) <= max_vertices:
        return coords
    idx = np.linspace(0, len(coords) - 1, max_vertices, dtype=int)
    out = [coords[int(i)] for i in idx]
    if out[0] != out[-1]:
        out.append(out[0])
    return out


def clip_polygon_to_image_pixels(
    info: dict[str, Any], clip_geometry: Polygon | MultiPolygon, max_vertices: int = 192
) -> list[tuple[float, float]] | None:
    footprint = image_footprint_pdf(info)
    if footprint is None:
        return None
    try:
        poly = _largest_polygon(footprint.intersection(clip_geometry))
    except Exception:
        return None
    if poly is None or poly.area <= 1e-9:
        return None
    a, b, c, d, e, f = map(float, info["transform"])
    A = np.array([[a, c], [b, d]], dtype=float)
    try:
        inv = np.linalg.inv(A)
    except np.linalg.LinAlgError:
        return None
    width = float(info.get("width", 1) or 1)
    height = float(info.get("height", 1) or 1)
    pixels = []
    for x, y in poly.exterior.coords:
        u, v = inv @ np.array([float(x) - e, float(y) - f], dtype=float)
        pixels.append(
            (
                max(-0.5, min(width - 0.5, float(u) * width - 0.5)),
                max(-0.5, min(height - 0.5, float(v) * height - 0.5)),
            )
        )
    pixels = _simplify_ring(pixels, max_vertices)
    return pixels if len(pixels) >= 4 else None


def render_shading_fallback(
    page: fitz.Page,
    bbox: Sequence[float],
    output_path: str | Path,
    *,
    clip_geometry: Polygon | MultiPolygon | None = None,
    scale: float = 2.0,
) -> tuple[int, int]:
    r = fitz.Rect(*map(float, bbox))
    if r.is_empty or r.width <= 0 or r.height <= 0:
        raise ValueError("empty shading bbox")
    scale = max(0.25, float(scale))
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=r, alpha=True)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pix.save(str(path))
    if clip_geometry is not None:
        im = Image.open(path).convert("RGBA")
        mask = Image.new("L", im.size, 0)
        draw = ImageDraw.Draw(mask)
        poly = _largest_polygon(clip_geometry.intersection(box(r.x0, r.y0, r.x1, r.y1)))
        if poly is not None:
            draw.polygon(
                [
                    ((x - r.x0) * scale, (y - r.y0) * scale)
                    for x, y in poly.exterior.coords
                ],
                fill=255,
            )
            for hole in poly.interiors:
                draw.polygon(
                    [((x - r.x0) * scale, (y - r.y0) * scale) for x, y in hole.coords],
                    fill=0,
                )
            alpha = np.asarray(im.getchannel("A"), dtype=np.uint8)
            m = np.asarray(mask, dtype=np.uint8)
            im.putalpha(Image.fromarray(np.minimum(alpha, m), mode="L"))
            im.save(path)
    return pix.width, pix.height


__all__ = [
    "MediaConfig",
    "MediaOccurrence",
    "clip_polygon_to_image_pixels",
    "enumerate_media_occurrences",
    "extract_image_pixmap",
    "render_image_mask_paints",
    "render_shading_fallback",
]
