def glyph_capability():
    from .engine.text.dxf_text import CATALOG, load_catalog

    missing = []
    error = None
    try:
        templates = load_catalog()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        missing = [CATALOG.name]
        templates = []
        error = str(exc)
    return {
        "available": not missing,
        "missing": missing,
        "error": error,
        "templates": len(templates),
        "scope": "DXF engineering dimension digits with contextual verification",
        "native_pdf_text": True,
        "ocr_enabled": False,
    }
