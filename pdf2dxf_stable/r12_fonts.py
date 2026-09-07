"""Provision optional R12 text metrics without replacing existing DXF styles."""

from pathlib import Path
from weakref import WeakSet

_fallback_managers = WeakSet()


def ensure_r12_fonts():
    from ezdxf.fonts import fonts
    from ezdxf.fonts.font_manager import FontNotFoundError

    try:
        fonts.font_manager.get_font_face(fonts.font_manager.fallback_font_name())
        return fonts.font_manager in _fallback_managers
    except FontNotFoundError:
        pass
    try:
        import matplotlib
    except ImportError as exc:
        raise RuntimeError(
            "R12_FONT_UNAVAILABLE: install pdf2dxf-construction[render] or supply system fonts; "
            "the universal DXF preserves MTEXT without these metrics"
        ) from exc
    directory = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
    fonts.font_manager.build([str(directory)], support_dirs=False)
    # ezdxf 1.4 caches an absent Arial name even for an empty font cache.
    # Adding fonts does not invalidate that name; recompute it without clearing
    # existing fonts or changing any DXF text style definitions.
    fonts.font_manager._fallback_font_name = ""
    fonts.font_manager.get_font_face(fonts.font_manager.fallback_font_name())
    _fallback_managers.add(fonts.font_manager)
    return True
