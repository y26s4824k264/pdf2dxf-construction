"""Repair missing native PDF Unicode from the actual embedded TrueType glyph IDs.

This is input decoding, not outline recognition. The latter still reads saved
DXF geometry only. Never distribute extracted fonts or use semantic guesses.
"""

import hashlib
import io
import re

from fontTools.ttLib import TTFont


def _name(value):
    # PDF BaseFont may use the full face name while texttrace uses PostScript.
    # Colliding normalized names still require agreement from every font below.
    return re.sub(r"[\s_-]", "", str(value).split("+")[-1])


def repair_embedded_unicode(page, traces):
    """Only replace U+FFFD when every same-named embedded face agrees uniquely."""
    needed = {
        _name(trace.get("font", ""))
        for trace in traces
        if any(char[0] == 0xFFFD for char in trace.get("chars", ()))
    }
    if not needed:
        return 0
    try:
        fonts = page.get_fonts(full=True)
        document = page.parent
    except (AttributeError, RuntimeError, ValueError):
        return 0
    faces = {name: {} for name in needed}
    for info in fonts:
        name = _name(info[3])
        if name not in faces:
            continue
        try:
            _, _, _, data = document.extract_font(info[0])
            if not data or len(data) > 64 * 1024 * 1024:
                raise ValueError("embedded font unavailable or too large")
            digest = hashlib.sha256(data).hexdigest()
            if digest in faces[name]:
                continue
            with TTFont(io.BytesIO(data), lazy=True) as font:
                if "glyf" not in font:
                    raise ValueError("only verified TrueType glyph IDs are supported")
                labels = {}
                for table in font["cmap"].tables:
                    if not table.isUnicode():
                        continue
                    for code, glyph in table.cmap.items():
                        if (
                            not (32 <= code <= 0x10FFFF)
                            or 127 <= code <= 159
                            or 0xD800 <= code <= 0xDFFF
                            or code in (0xFFFD, 0xFFFE, 0xFFFF)
                        ):
                            continue
                        gid = font.getGlyphID(glyph)
                        if gid:
                            labels.setdefault(gid, set()).add(code)
                faces[name][digest] = labels
        except Exception:  # A corrupt optional font must not abort geometry conversion.
            faces[name][f"unavailable-{info[0]}"] = {}
    count = 0
    for trace in traces:
        family = faces.get(_name(trace.get("font", "")), {})
        if not family:
            continue
        chars = []
        repaired = False
        for item in trace.get("chars", ()):
            if item[0] == 0xFFFD:
                values = [labels.get(item[1], set()) for labels in family.values()]
                if all(len(value) == 1 for value in values):
                    codes = set.union(*values)
                    if len(codes) == 1:
                        item = (next(iter(codes)), *item[1:])
                        count += 1
                        repaired = True
            chars.append(item)
        trace["chars"] = tuple(chars)
        if repaired:
            digest = hashlib.sha256(
                ",".join(sorted(family)).encode("ascii")
            ).hexdigest()
            trace["unicode_source"] = "texttrace+embedded-cmap:" + digest
    return count
