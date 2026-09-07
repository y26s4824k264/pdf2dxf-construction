from ezdxf import DXFValueError, transform
from ezdxf.math import Matrix44

UNITS = {
    "auto": (4, 1.0),
    "mm": (4, 1.0),
    "cm": (5, 10.0),
    "m": (6, 1000.0),
    "inch": (1, 25.4),
}


def output_unit_info(doc):
    """Read persisted units, including the R12 fallback written by this package."""
    codes = {
        value[0]: (name, value[1]) for name, value in UNITS.items() if name != "auto"
    }
    code = int(doc.header.get("$INSUNITS", 0))
    if code not in codes:
        try:
            tags = list(doc.layers.get("0").get_xdata("PDF2DXF_STABLE"))
        except DXFValueError:
            tags = []
        for index, (kind, value) in enumerate(tags[:-1]):
            if kind == 1000 and value == "INSUNITS" and tags[index + 1][0] == 1070:
                code = int(tags[index + 1][1])
                break
    return codes.get(code, ("unknown", 1.0))


def apply_output_options(doc, request):
    code, mm_per_unit = UNITS[request.units]
    scale = request.manual_scale if request.scale_mode == "manual" else 1.0
    factor = scale / mm_per_unit
    if factor != 1.0:
        failures = list(transform.inplace(doc.modelspace(), Matrix44.scale(factor)))
        if failures:
            raise ValueError("OUTPUT_TRANSFORM_FAILED: " + str(failures[:3]))
        for key in ("$EXTMIN", "$EXTMAX"):
            if key in doc.header:
                doc.header[key] = tuple(float(v) * factor for v in doc.header[key])
    doc.header["$INSUNITS"] = code
    if "PDF2DXF_STABLE" not in doc.appids:
        doc.appids.add("PDF2DXF_STABLE")
    doc.layers.get("0").set_xdata(
        "PDF2DXF_STABLE",
        [
            (1000, "scale_mode"),
            (1000, request.scale_mode),
            (1000, "manual_scale"),
            (1040, float(scale)),
            (1000, "INSUNITS"),
            (1070, code),
        ],
    )
