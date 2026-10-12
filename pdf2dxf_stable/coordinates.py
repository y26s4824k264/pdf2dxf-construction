"""Portable, per-entity coordinate evidence for downstream DXF consumers.

This records the saved-DXF validator's decision, not merely INSUNITS or a
declared scale. Consumers must retain the tags when copying/splitting entities.
"""

import ezdxf

from .determinism import canonicalize_ascii_dxf

COORDINATE_APPID = "PDF2DXF_COORDS"


def stamp_coordinate_contract(path, validation, *, page, seed=None):
    document = ezdxf.readfile(path)
    if COORDINATE_APPID not in document.appids:
        document.appids.add(COORDINATE_APPID)
    tags = [
        (1000, "v1"),
        (1000, validation["scale_status"]),
        (1070, int(validation["model_ready"])),
        (1000, validation["output_units"]),
        (1071, int(page)),
    ]
    document.layers.get("0").set_xdata(COORDINATE_APPID, tags)
    for block in document.blocks:
        for entity in block:
            entity.set_xdata(COORDINATE_APPID, tags)
    document.saveas(path)
    if seed is not None:
        canonicalize_ascii_dxf(path, seed=seed)
