from __future__ import annotations
from dataclasses import dataclass, asdict, field
from collections import Counter, defaultdict
from pathlib import Path
import json
import math
import re
import fitz

_SCALE_RE = re.compile(
    r"(?:^|[^0-9])1\s*[:：]\s*(10|20|25|30|40|50|75|100|125|150|200|250|300|400|500)(?:[^0-9]|$)",
    re.I,
)
DISCIPLINE_TOKENS = {
    "architecture": (
        "A-",
        "ARCH",
        "WALL",
        "DOOR",
        "WIND",
        "GLAZ",
        "CURT",
        "SPAC",
        "ROOM",
        "ELEV",
        "SECT",
        "DETL",
        "STAIR",
        "LIFT",
        "FURN",
        "FIXT",
        "ROOF",
        "FLOOR",
        "ANNO",
        "GRID",
        "LEVL",
        "IDEN",
        "建筑",
        "门窗",
        "平面",
        "立面",
        "剖面",
    ),
    "structure": (
        "S-",
        "STRU",
        "REBAR",
        "BEAM",
        "COLU",
        "SLAB",
        "FOUND",
        "PILE",
        "STEEL",
        "TRUSS",
        "BRACE",
        "S-PATT",
        "结构",
        "配筋",
        "梁",
        "柱",
        "板",
        "基础",
    ),
    "electrical": (
        "E-",
        "EL-",
        "ELEC",
        "POWER",
        "LIGHT",
        "LITE",
        "WIRE",
        "CABLE",
        "SWCH",
        "SOCK",
        "PANEL",
        "TRAY",
        "EARTH",
        "弱电",
        "强电",
        "照明",
        "电气",
        "配电",
    ),
    "plumbing": (
        "P-",
        "PLUMB",
        "PIPE",
        "RISR",
        "WATR",
        "WATER",
        "SAN",
        "SEWR",
        "DRAIN",
        "STORM",
        "给排水",
        "给水",
        "排水",
        "污水",
        "雨水",
        "管道",
    ),
    "fire": (
        "FP-",
        "FIRE",
        "HYDR",
        "SPRK",
        "SPRINK",
        "SMOKE",
        "ALARM",
        "消火栓",
        "喷淋",
        "消防",
        "火灾报警",
    ),
    "hvac": (
        "M-",
        "H-",
        "HVAC",
        "DUCT",
        "DIFF",
        "GRIL",
        "AHU",
        "FCU",
        "CHWS",
        "CHWR",
        "REFR",
        "空调",
        "暖通",
        "风管",
        "送风",
        "排风",
        "采暖",
    ),
    "civil_site": (
        "C-",
        "SITE",
        "CIVIL",
        "TOPO",
        "CONT",
        "ROAD",
        "CURB",
        "GRAD",
        "DRAINAGE",
        "PLOT",
        "BOUND",
        "坐标",
        "总图",
        "道路",
        "竖向",
        "地形",
        "场地",
    ),
    "landscape": (
        "L-",
        "LAND",
        "TREE",
        "PLANT",
        "SHRUB",
        "LAWN",
        "PAVE",
        "LANDSCAPE",
        "景观",
        "绿化",
        "种植",
        "铺装",
    ),
    "interior": (
        "I-",
        "INT",
        "FURN",
        "FINI",
        "CEIL",
        "JOIN",
        "MILL",
        "室内",
        "装修",
        "吊顶",
    ),
}
ROLE_PATTERNS = [
    ("sheet_frame", ("FRAME", "BORDER", "TITLEBLOCK", "SHEET", "TK", "图框", "签栏")),
    ("annotation_dimension", ("DIMS", "DIM-", "DIMENSION", "尺寸")),
    ("annotation_level", ("LEVL", "LEVEL", "ELEV-TEXT", "标高")),
    ("annotation_grid", ("GRID-IDEN", "GRID", "轴网", "轴号")),
    ("annotation_title", ("TITL", "TITLE", "DRAWING-NAME", "图名")),
    ("annotation_note", ("ANNO", "NOTE", "TEXT", "LABEL", "IDEN", "说明", "文字")),
    ("wall", ("WALL", "墙")),
    ("door", ("DOOR", "门")),
    ("window", ("WIND", "WINDOW", "GLAZ", "CURT", "窗", "幕墙")),
    ("column", ("COLU", "COLUMN", "柱")),
    ("beam", ("BEAM", "梁")),
    ("slab", ("SLAB", "FLOOR", "板")),
    ("rebar", ("REBAR", "配筋", "钢筋")),
    ("foundation", ("FOUND", "PILE", "基础", "桩")),
    ("pipe", ("PIPE", "RISR", "WATR", "SAN", "SEWR", "DRAIN", "管")),
    ("duct", ("DUCT", "风管")),
    ("electrical_wire", ("WIRE", "CABLE", "CIRCUIT", "导线", "电缆")),
    (
        "electrical_equipment",
        ("POWER", "LIGHT", "SWCH", "SOCK", "PANEL", "配电", "照明"),
    ),
    ("fire_system", ("FIRE", "HYDR", "SPRK", "ALARM", "消防", "喷淋")),
    ("furniture_fixture", ("FURN", "FIXT", "EQUIP", "家具", "设备")),
    ("hatch_pattern", ("PATT", "HATCH", "FILL", "填充")),
    ("detail_geometry", ("DETL", "DETAIL", "FINE", "THIN", "细线", "详图")),
    ("site_boundary", ("SITE", "BOUND", "PLOT", "ROAD", "CURB", "场地", "红线")),
    ("landscape", ("TREE", "PLANT", "SHRUB", "LAWN", "景观", "绿化")),
]
SHEET_KIND_PATTERNS = [
    ("drawing_index", ("图纸目录", "图纸类别代码表", "DRAWING INDEX", "SHEET INDEX")),
    ("general_notes", ("设计说明", "专篇", "GENERAL NOTES", "SPECIFICATION")),
    ("schedule", ("门窗表", "材料表", "设备表", "SCHEDULE", "SCHED", "LIST")),
    ("plan", ("平面图", "PLAN")),
    ("elevation", ("立面图", "ELEVATION")),
    ("section", ("剖面图", "SECTION")),
    ("detail", ("详图", "大样图", "DETAIL", "DETL")),
    ("site_plan", ("总平面", "总图", "SITE PLAN")),
    ("diagram", ("系统图", "原理图", "SCHEMATIC", "DIAGRAM")),
]


@dataclass(slots=True)
class LayerProfileV15:
    original_name: str
    drawing_records: int
    discipline: str
    role: str
    canonical_name: str


@dataclass(slots=True)
class ConstructionProfileV15:
    source_pdf: str
    page_index: int
    primary_discipline: str
    discipline_scores: dict[str, float]
    sheet_kind: str
    sheet_kind_confidence: float
    scale_labels: list[int]
    drawing_records: int
    layer_count: int
    layers: list[LayerProfileV15]
    searchable_text_chars: int
    title_hint: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

    def save(self, path):
        Path(path).write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )


class ConstructionProfileAnalyzerV15:
    @staticmethod
    def _norm(v: str) -> str:
        return re.sub(r"\s+", " ", v or "").upper()

    def classify_layer(self, layer: str) -> tuple[str, str, str]:
        u = self._norm(layer)
        role = "unknown"
        for name, tokens in ROLE_PATTERNS:
            if any(t.upper() in u for t in tokens):
                role = name
                break
        scores = {}
        for d, tokens in DISCIPLINE_TOKENS.items():
            s = sum(1.0 for t in tokens if t.upper() in u)
            if s:
                scores[d] = s
        if role in {
            "wall",
            "door",
            "window",
            "annotation_dimension",
            "annotation_level",
            "annotation_grid",
            "detail_geometry",
        }:
            scores["architecture"] = scores.get("architecture", 0) + 0.8
        if role in {"column", "beam", "slab", "rebar", "foundation"}:
            scores["structure"] = scores.get("structure", 0) + 2
        if role == "pipe":
            scores["plumbing"] = scores.get("plumbing", 0) + 1.5
        if role == "duct":
            scores["hvac"] = scores.get("hvac", 0) + 1.5
        if role.startswith("electrical"):
            scores["electrical"] = scores.get("electrical", 0) + 1.5
        if role == "fire_system":
            scores["fire"] = scores.get("fire", 0) + 2
        disc = max(scores, key=scores.get) if scores else "general"
        prefix = {
            "architecture": "A",
            "structure": "S",
            "electrical": "E",
            "plumbing": "P",
            "fire": "F",
            "hvac": "M",
            "civil_site": "C",
            "landscape": "L",
            "interior": "I",
            "general": "G",
        }[disc]
        code = re.sub(r"[^A-Z0-9]+", "_", role.upper()).strip("_") or "UNKNOWN"
        return disc, role, f"{prefix}-{code}"

    def _sheet_kind(self, hay: str):
        u = self._norm(hay)
        hits = []
        for kind, tokens in SHEET_KIND_PATTERNS:
            n = sum(u.count(t.upper()) for t in tokens)
            if n:
                hits.append((n, kind))
        if not hits:
            return "other", 0.25
        hits.sort(reverse=True)
        top = hits[0]
        total = sum(x[0] for x in hits)
        return top[1], min(0.99, 0.55 + 0.44 * top[0] / max(total, 1))

    def analyze(self, pdf: fitz.Document, page_index: int) -> ConstructionProfileV15:
        page = pdf[page_index]
        try:
            drawings = page.get_cdrawings(extended=True)
        except TypeError:
            drawings = page.get_cdrawings()
        counts = Counter(
            str(d.get("layer", "") or "")
            for d in drawings
            if str(d.get("type", "")) in {"s", "f", "fs"}
        )
        try:
            text = page.get_text("text") or ""
        except Exception:
            text = ""
        source = str(getattr(pdf, "name", "") or "")
        combined = f"{text}\n" + "\n".join(counts)
        rows = []
        scores = defaultdict(float)
        for layer, count in counts.items():
            disc, role, canonical = self.classify_layer(layer)
            rows.append(LayerProfileV15(layer, int(count), disc, role, canonical))
            scores[disc] += math.log1p(count)
        u = self._norm(combined)
        for disc, tokens in DISCIPLINE_TOKENS.items():
            scores[disc] += min(12.0, sum(u.count(t.upper()) for t in tokens) * 0.18)
        primary = max(scores, key=scores.get) if scores else "general"
        kind, kconf = self._sheet_kind(combined)
        scales = sorted({int(x) for x in _SCALE_RE.findall(combined)})
        title = ""
        for line in (x.strip() for x in text.splitlines()):
            if any(
                t.upper() in line.upper()
                for _, tokens in SHEET_KIND_PATTERNS
                for t in tokens
            ):
                title = line[:160]
                break
        rows.sort(key=lambda r: (-r.drawing_records, r.original_name))
        total = sum(scores.values()) or 1
        norm = {k: round(v / total, 6) for k, v in sorted(scores.items()) if v > 0}
        warnings = []
        if len(scales) > 1:
            warnings.append(
                "multiple declared scales found; title scales are metadata only"
            )
        return ConstructionProfileV15(
            source,
            page_index,
            primary,
            norm,
            kind,
            kconf,
            scales,
            len(drawings),
            len(counts),
            rows,
            len(text.replace("\n", "")),
            title,
            warnings,
        )


def canonical_layer_map(profile):
    grouped = defaultdict(list)
    for row in profile.layers:
        grouped[row.canonical_name].append(row)
    out = {}
    for canonical, rows in grouped.items():
        rows = sorted(rows, key=lambda x: (-x.drawing_records, x.original_name))
        for i, row in enumerate(rows, 1):
            out[row.original_name] = (
                canonical if len(rows) == 1 else f"{canonical}_{i:02d}"
            )
    return out
