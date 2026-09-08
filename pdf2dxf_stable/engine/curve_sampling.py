"""Shared numeric boundary for PDF and font-template cubic sampling."""

from __future__ import annotations

import math


def cubic_sample_count(flatness: float, tolerance: float, max_samples: int = 96) -> int:
    """Keep serialization noise within 1e-4 samples from crossing an integer.

    PDF float coordinates can move an ideal count of 9 to 9.000077, while
    the same font curve at another position yields 8.999983. Applying ceil
    directly gives different polylines and consequently different glyph
    masks. Snap only this bounded count tie; coordinates, curve controls,
    configured tolerance and all other ceil decisions remain unchanged.
    """
    count = 2.0 + math.sqrt(max(flatness, 0.0) / max(tolerance, 1e-4)) * 5.0
    nearest = round(count)
    if abs(count - nearest) <= 1e-4:
        count = nearest
    return int(max(4, min(max_samples, math.ceil(count))))
