"""PDF validation, repair and page selection inside a supervised child process."""

import argparse
import json
from pathlib import Path

from .determinism import sha256
from .repair import recover_pdf


def prepare_pdf(source, workdir, pages):
    from .core import _pages

    repair = recover_pdf(source, workdir)
    result = {
        "schema": "pdf2dxf.input_validation.v1",
        "ok": False,
        "repair": repair.to_dict(),
    }
    if repair.selected:
        result.update(
            selected_pages=_pages(repair.selected, pages),
            source_sha256=sha256(source),
            ok=True,
        )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "workdir", "request", "result"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    try:
        request = json.loads(Path(args.request).read_text(encoding="utf-8"))
        result = prepare_pdf(args.source, args.workdir, request["pages"])
    except Exception as exc:
        result = {
            "schema": "pdf2dxf.input_validation.v1",
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    Path(args.result).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0 if result["ok"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
