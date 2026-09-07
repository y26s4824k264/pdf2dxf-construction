from __future__ import annotations
from dataclasses import dataclass, asdict, field
from pathlib import Path
from collections import Counter, defaultdict
from typing import Any
import math, time
import ezdxf, fitz
from shapely.geometry import LineString, box
import pdf2dxf_stable.engine.geometry.base as v14


@dataclass(slots=True)
class ConstructionKernelConfigV15(v14.KernelConfig):
    compact_dense_patterns: bool = True
    dense_pattern_min_records: int = 5000
    dense_pattern_tokens: tuple[str, ...] = (
        "PATT-WALL",
        "WALL-PATT",
        "DETL-PATT",
        "DETAIL-PATT",
        "ELEV-HACH",
        "HATCH",
        "PATT",
        "FILL-PAT",
        "填充",
    )
    dense_pattern_angle_quantum_deg: float = 0.20
    dense_pattern_offset_quantum: float = 0.015
    dense_pattern_gap_tolerance: float = 0.025
    dense_pattern_min_length: float = 0.004


@dataclass(slots=True)
class ConstructionKernelStatsV15(v14.KernelStats):
    dense_pattern_layer_count: int = 0
    dense_pattern_layers: list[str] = field(default_factory=list)
    dense_pattern_records: int = 0
    dense_pattern_segments_in: int = 0
    dense_pattern_entities_out: int = 0
    dense_pattern_duplicates_or_joins: int = 0

    def to_dict(self):
        return asdict(self)


@dataclass(slots=True)
class _Bucket:
    attrs: dict[str, Any]
    rgb: tuple[int, int, int] | None
    opacity: float
    segments: list[tuple[tuple[float, float], tuple[float, float]]] = field(
        default_factory=list
    )


class ConstructionGraphicsKernelV15(v14.GenericGraphicsKernelV14):
    def __init__(self, config: ConstructionKernelConfigV15 | None = None):
        super().__init__(config or ConstructionKernelConfigV15())
        self.config: ConstructionKernelConfigV15

    def _dense_layers(self, drawings):
        if not self.config.compact_dense_patterns:
            return set()
        c = Counter(
            str(d.get("layer", "") or "")
            for d in drawings
            if str(d.get("type", "")) in {"s", "fs"}
        )
        return {
            l
            for l, n in c.items()
            if n >= self.config.dense_pattern_min_records
            and any(t.upper() in l.upper() for t in self.config.dense_pattern_tokens)
        }

    def _append(self, buckets, attrs, d, p0, p1):
        a = (float(p0[0]), float(p0[1]))
        b = (float(p1[0]), float(p1[1]))
        if math.dist(a, b) <= self.config.dense_pattern_min_length:
            return
        key = (
            attrs.get("layer", "0"),
            attrs.get("linetype", "BYLAYER"),
            attrs.get("lineweight", -1),
            v14.color_to_rgb(d.get("color")),
            round(float(d.get("stroke_opacity", 1) or 1), 4),
        )
        if key not in buckets:
            buckets[key] = _Bucket(dict(attrs), key[3], key[4])
        buckets[key].segments.append((a, b))

    def _collect_chain(self, buckets, chain, transform, attrs, d):
        n = 0
        for s in chain.segments:
            if isinstance(s, v14.LineSeg):
                p0, p1 = transform.points([s.p0, s.p1])
                self._append(buckets, attrs, d, p0, p1)
                n += 1
            else:
                pts = transform.points(
                    v14.flatten_cubic(
                        s,
                        self.config.curve_flatten_tolerance_pt,
                        self.config.max_curve_samples,
                    )
                )
                for a, b in zip(pts, pts[1:]):
                    self._append(buckets, attrs, d, a, b)
                    n += 1
        return n

    def _collect_clipped(self, buckets, chains, clip, transform, attrs, d):
        n = 0
        for chain in chains:
            pts = v14.flatten_chain(
                chain,
                self.config.curve_flatten_tolerance_pt,
                self.config.max_curve_samples,
            )
            if len(pts) < 2:
                continue
            try:
                inter = LineString(pts).intersection(clip.geometry)
            except Exception:
                continue
            for part in v14.geometry_parts(inter):
                if not isinstance(part, LineString):
                    continue
                out = transform.points(part.coords)
                for a, b in zip(out, out[1:]):
                    self._append(buckets, attrs, d, a, b)
                    n += 1
        return n

    def _emit_buckets(self, msp, buckets, stats, page_index):
        aq = max(self.config.dense_pattern_angle_quantum_deg, 1e-6)
        oq = max(self.config.dense_pattern_offset_quantum, 1e-9)
        gap = max(self.config.dense_pattern_gap_tolerance, 0)
        for bucket in buckets.values():
            grouped = defaultdict(list)
            basis = {}
            for p0, p1 in bucket.segments:
                dx, dy = p1[0] - p0[0], p1[1] - p0[1]
                L = math.hypot(dx, dy)
                if L <= self.config.dense_pattern_min_length:
                    continue
                ang = math.degrees(math.atan2(dy, dx)) % 180
                ak = int(round(ang / aq))
                th = math.radians(ak * aq)
                ux, uy = math.cos(th), math.sin(th)
                vx, vy = -uy, ux
                off = 0.5 * ((p0[0] * vx + p0[1] * vy) + (p1[0] * vx + p1[1] * vy))
                ok = int(round(off / oq))
                q0 = p0[0] * ux + p0[1] * uy
                q1 = p1[0] * ux + p1[1] * uy
                grouped[(ak, ok)].append((min(q0, q1), max(q0, q1)))
                basis[(ak, ok)] = (ux, uy, vx, vy)
            for key, ints in grouped.items():
                ints.sort()
                merged = []
                for a, b in ints:
                    if not merged or a > merged[-1][1] + gap:
                        merged.append([a, b])
                    else:
                        merged[-1][1] = max(merged[-1][1], b)
                stats.dense_pattern_duplicates_or_joins += len(ints) - len(merged)
                ak, ok = key
                ux, uy, vx, vy = basis[key]
                off = ok * oq
                for a, b in merged:
                    if b - a <= self.config.dense_pattern_min_length:
                        continue
                    e = msp.add_line(
                        (ux * a + vx * off, uy * a + vy * off),
                        (ux * b + vx * off, uy * b + vy * off),
                        dxfattribs=bucket.attrs,
                    )
                    if bucket.rgb is not None:
                        try:
                            e.rgb = bucket.rgb
                        except:
                            pass
                    if self.config.add_xdata:
                        try:
                            e.set_xdata(
                                self.config.appid,
                                [
                                    (1000, "dense_pattern_merged"),
                                    (1070, page_index),
                                    (1070, -1),
                                    (1000, "s"),
                                ],
                            )
                        except:
                            pass
                    stats.line_entities += 1
                    stats.dense_pattern_entities_out += 1

    def convert_page(self, pdf, page_index, output_path):
        started = time.perf_counter()
        page = pdf[page_index]
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        stats = ConstructionKernelStatsV15(
            source_pdf=str(getattr(pdf, "name", "")),
            page_index=page_index,
            page_rotation=int(page.rotation),
            unit_mode=self.config.units,
        )
        transform = v14.PageTransform(page, self.config)
        stats.geometry_scale = transform.scale
        doc = ezdxf.new(self.config.dxf_version, setup=True)
        doc.header["$INSUNITS"] = 4 if self.config.units == "paper_mm" else 0
        if self.config.add_xdata and self.config.appid not in doc.appids:
            doc.appids.add(self.config.appid)
        msp = doc.modelspace()
        layers = v14.LayerManager(doc, self.config)
        ltypes = v14.LinetypeManager(doc, transform.scale)
        if self.config.include_page_boundary:
            layer = layers.sanitize("PDF_PAGE")
            e = msp.add_lwpolyline(
                [
                    (0, 0),
                    (transform.width, 0),
                    (transform.width, transform.height),
                    (0, transform.height),
                ],
                close=True,
                dxfattribs={"layer": layer},
            )
            e.set_xdata(
                self.config.appid, [(1000, "page_boundary"), (1070, page_index)]
            )
        try:
            drawings = page.get_cdrawings(extended=True)
        except TypeError:
            drawings = page.get_cdrawings()
        stats.input_draw_records = len(drawings)
        dense = self._dense_layers(drawings)
        stats.dense_pattern_layers = sorted(dense)
        stats.dense_pattern_layer_count = len(dense)
        text_diag = v14.TextRecoveryDiagnostics()
        text_runs = []
        matches = {}
        matched = set()
        if self.config.include_native_text:
            text_runs = v14.extract_text_runs(page, text_diag)
            stats.text_runs = len(text_runs)
            stats.hidden_text_runs = text_diag.hidden_runs
            stats.hidden_search_chars = text_diag.hidden_chars
            stats.warnings.extend(text_diag.warnings)
            if self.config.recover_outline_text:
                rc = v14.TextRecoveryConfig(
                    recover_hidden_search_text=True,
                    unmatched_text_visible=self.config.unmatched_recovered_text_visible,
                    recovered_text_layer=self.config.recovered_text_layer,
                    unmatched_text_layer=self.config.unmatched_recovered_text_layer,
                    outline_original_layer=self.config.outline_original_layer,
                    outline_policy=self.config.outline_text_policy,
                    min_match_confidence=self.config.outline_min_match_confidence,
                )
                matches, matched = v14.match_outline_records(
                    text_runs, drawings, rc, text_diag
                )
                stats.outline_matched_runs = text_diag.matched_runs
                stats.outline_unmatched_runs = text_diag.unmatched_runs
                stats.matched_outline_records = len(matched)
        media_clips = (
            self._build_media_clip_map(drawings, stats)
            if self.config.clip_images
            else {}
        )
        outline_layer = ""
        if matched and self.config.outline_text_policy == "off_layer":
            outline_layer = layers.sanitize(
                self.config.outline_original_layer, self.config.outline_original_layer
            )
            layers.off(outline_layer)
        active = {}
        versions = {}
        cache = {}
        vc = 0
        buckets = {}
        for idx, src in enumerate(drawings):
            rec = src
            is_outline = idx in matched
            if is_outline:
                if self.config.outline_text_policy == "drop":
                    stats.outline_records_dropped += 1
                    continue
                if self.config.outline_text_policy == "off_layer":
                    rec = dict(src)
                    rec["_v14_outline_original"] = True
                    stats.outline_records_relayered += 1
            typ = str(rec.get("type", ""))
            level = int(rec.get("level", 0) or 0)
            if typ == "group":
                stats.input_group_records += 1
                continue
            if typ == "clip":
                stats.input_clip_records += 1
                for k in [k for k in active if k >= level]:
                    active.pop(k, None)
                    versions.pop(k, None)
                st = v14.clip_state_from_record(rec, self.config, stats)
                if st is not None:
                    active[level] = st
                    vc += 1
                    versions[level] = vc
                    cache.clear()
                continue
            if typ == "s":
                stats.input_stroke_records += 1
            elif typ == "f":
                stats.input_fill_records += 1
            elif typ == "fs":
                stats.input_fill_stroke_records += 1
            else:
                continue
            seq = int(rec.get("seqno", -1) or -1)
            clip = (
                self._effective_clip(active, level, cache, versions)
                if self.config.clip_paths
                else None
            )
            if (
                clip is not None
                and clip.is_rectangle
                and self._record_inside_rect_clip(rec, clip)
            ):
                clip = None
            elif clip is not None:
                stats.clipped_records += 1
            forced = (
                outline_layer
                if is_outline and self.config.outline_text_policy == "off_layer"
                else None
            )
            if "f" in typ and self.config.emit_hatches:
                self._emit_fill(
                    msp,
                    rec,
                    clip,
                    transform,
                    forced or layers.style_layer(rec, "FILL"),
                    stats,
                    page_index,
                    seq,
                )
            if "s" in typ and (
                typ == "s" or self.config.preserve_stroke_for_fill_stroke
            ):
                chains = v14.parse_drawing_chains(rec, stats)
                sl = forced or layers.style_layer(rec, "STROKE")
                attrs = self._entity_attrs(sl, rec, ltypes, stroke=True)
                if str(src.get("layer", "") or "") in dense and not is_outline:
                    stats.dense_pattern_records += 1
                    if clip is None:
                        for ch in chains:
                            stats.dense_pattern_segments_in += self._collect_chain(
                                buckets, ch, transform, attrs, rec
                            )
                    else:
                        inside = False
                        try:
                            r = rec.get("rect")
                            inside = bool(
                                r and clip.geometry.covers(box(*map(float, r)))
                            )
                        except:
                            pass
                        if inside:
                            for ch in chains:
                                stats.dense_pattern_segments_in += self._collect_chain(
                                    buckets, ch, transform, attrs, rec
                                )
                        else:
                            stats.dense_pattern_segments_in += self._collect_clipped(
                                buckets, chains, clip, transform, attrs, rec
                            )
                    continue
                if clip is None:
                    for ch in chains:
                        self._emit_native_chain(
                            msp, ch, transform, attrs, rec, stats, page_index, seq
                        )
                else:
                    inside = False
                    try:
                        r = rec.get("rect")
                        inside = bool(r and clip.geometry.covers(box(*map(float, r))))
                    except:
                        pass
                    if inside:
                        for ch in chains:
                            self._emit_native_chain(
                                msp, ch, transform, attrs, rec, stats, page_index, seq
                            )
                    elif (
                        self._emit_clipped_stroke(
                            msp,
                            chains,
                            clip,
                            transform,
                            attrs,
                            rec,
                            stats,
                            page_index,
                            seq,
                        )
                        == 0
                    ):
                        stats.clip_rejected_records += 1
        self._emit_buckets(msp, buckets, stats, page_index)
        self._add_text_runs(
            page, doc, msp, transform, layers, stats, page_index, text_runs, matches
        )
        self._add_images(
            getattr(pdf, "_pdf", pdf),
            getattr(page, "_page", page),
            doc,
            msp,
            transform,
            layers,
            stats,
            page_index,
            output_path,
            media_clips,
        )
        try:
            doc.header["$EXTMIN"] = (0, 0, 0)
            doc.header["$EXTMAX"] = (transform.width, transform.height, 0)
        except:
            pass
        doc.saveas(output_path)
        stats.layers = len(doc.layers)
        stats.output_entities = len(msp)
        stats.output_bytes = output_path.stat().st_size
        stats.elapsed_seconds = time.perf_counter() - started
        return stats
