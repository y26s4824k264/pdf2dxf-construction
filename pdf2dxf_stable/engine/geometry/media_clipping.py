"""Bind vector clipping paths to media at their actual MuPDF paint events."""

from __future__ import annotations

import fitz
from shapely.geometry import Polygon, MultiPolygon, box


def collect_media_clips(page, drawings, config, stats):
    from fitz import mupdf
    from .base import ClipState, clip_state_from_record

    infos = page.get_image_info(xrefs=True)
    if not infos:
        return {}
    masked_xrefs = {row[0] for row in page.get_images(full=True) if row[1]}
    records = iter(r for r in drawings if r.get("type") == "clip")
    unknown = object()
    paint_names = (
        "fill_path", "stroke_path", "fill_text", "stroke_text", "ignore_text",
        "fill_shade", "fill_image", "fill_image_mask",
    )
    callback_names = (*paint_names, "clip_path", "clip_stroke_path", "clip_text",
                      "clip_stroke_text", "clip_image_mask", "pop_clip",
                      "begin_mask", "end_mask")

    class Device(mupdf.FzDevice2):
        def __init__(self):
            super().__init__()
            for name in callback_names:
                getattr(self, "use_virtual_" + name)()
            self.stack = []
            self.seqno = 0
            self.image_index = 0
            self.result = {}
            self.failure = None
            self.cookie = mupdf.FzCookie()
            self.unsupported = set()

        def clip_path(self, *args):
            if self.failure is not None:
                return
            try:
                record = next(records)
                if record.get("scissor") is not None and fitz.Rect(record["scissor"]).is_empty:
                    self.stack.append(ClipState(Polygon(), (0, 0, 0, 0), True))
                    return
                state = clip_state_from_record(record, config, stats)
                parent = self.stack[-1] if self.stack else None
                if state is None or parent is unknown or isinstance(parent, tuple):
                    self.stack.append(unknown)
                    return
                geometry = state.geometry
                if parent is not None:
                    geometry = geometry.intersection(parent.geometry)
                if geometry.is_empty:
                    self.stack.append(ClipState(Polygon(), (0, 0, 0, 0), True))
                elif isinstance(geometry, (Polygon, MultiPolygon)):
                    bounds = tuple(map(float, geometry.bounds))
                    rectangle = box(*bounds)
                    self.stack.append(ClipState(
                        geometry, bounds,
                        abs(geometry.area - rectangle.area)
                        <= max(1e-6, rectangle.area * 1e-8),
                    ))
                else:
                    self.stack.append(unknown)
            except BaseException as exc:
                self.failure = exc
                self.cookie.m_internal.abort = 1

        def clip_stroke_path(self, *args):
            self.stack.append(unknown)

        clip_text = clip_stroke_path
        clip_stroke_text = clip_stroke_path
        def clip_image_mask(self, *args):
            # MuPDF paints an image's SMask through this clip callback. Its
            # opacity is already retained in the extracted PNG; vector clips
            # outside that temporary alpha scope still apply.
            self.stack.append(("image_alpha", self.stack[-1] if self.stack else None))

        def begin_mask(self, *args):
            pass

        def end_mask(self, *args):
            self.stack.append(unknown)

        def pop_clip(self, *args):
            if self.stack:
                self.stack.pop()

        def paint(self, media=False, image_info=None):
            if media and self.stack:
                current = self.stack[-1]
                if isinstance(current, tuple):
                    if image_info is not None and (
                        image_info.get("has-mask")
                        or image_info.get("xref") in masked_xrefs
                    ):
                        current = current[1]
                    else:
                        current = unknown
                if current is unknown:
                    self.unsupported.add(self.seqno)
                elif current is not None:
                    self.result[self.seqno] = current
            self.seqno += 1

        def fill_path(self, *args):
            self.paint()

        stroke_path = fill_path
        fill_text = fill_path
        stroke_text = fill_path
        ignore_text = fill_path

        def fill_image(self, *args):
            info = infos[self.image_index] if self.image_index < len(infos) else None
            self.image_index += 1
            self.paint(media=True, image_info=info)

        fill_image_mask = fill_image

        def fill_shade(self, *args):
            self.paint(media=True)

    def guard(callback):
        def invoke(self, *args):
            if self.failure is not None:
                return
            try:
                return callback(self, *args)
            except BaseException as exc:
                self.failure = exc
                self.cookie.m_internal.abort = 1
        return invoke

    for name in callback_names:
        setattr(Device, name, guard(getattr(Device, name)))

    old_rotation = page.rotation
    if old_rotation:
        page.set_rotation(0)
    device = Device()
    try:
        mupdf.fz_run_page(page.this, device, mupdf.FzMatrix(), device.cookie)
    except Exception:
        if device.failure is None:
            raise
    finally:
        try:
            mupdf.fz_close_device(device)
        finally:
            if old_rotation:
                page.set_rotation(old_rotation)
    if device.failure is not None:
        if not isinstance(device.failure, Exception):
            raise device.failure
        raise RuntimeError("media clipping event mismatch") from device.failure
    if (next(records, None) is not None or device.seqno != len(page.get_bboxlog())
            or device.image_index != len(infos)):
        raise RuntimeError("media clipping event count does not match page records")
    if device.unsupported:
        stats.warnings.append(
            f"image clipping failed: unsupported text/mask clip at {len(device.unsupported)} paints"
        )
    return device.result
