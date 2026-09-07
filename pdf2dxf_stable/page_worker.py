"""One supervised page includes extraction, conversion, profiles and validation."""

import argparse
import json
import traceback
import gc
from pathlib import Path
from .backend_worker import main as backend_main
from .request import ConversionRequest
from .profiles import emit_universal, emit_legacy_r12
from .validation import validate_dxf


def main():
    parser = argparse.ArgumentParser()
    for name in ("source", "output", "request", "result", "seed"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--page", required=True, type=int)
    args = parser.parse_args()
    target, result_file = Path(args.output), Path(args.result)
    request = ConversionRequest.model_validate_json(Path(args.request).read_text())
    try:
        raw = target.parent / "backend.dxf"
        backend_json = target.parent / "backend.json"
        mode = "sheet" if request.scale_mode in ("page", "manual") else request.mode
        command = [
            args.source,
            "--page",
            str(args.page),
            "--output",
            str(raw),
            "--result-json",
            str(backend_json),
            "--mode",
            mode,
            "--request-json",
            args.request,
        ]
        if request.recover_pure_path_text:
            command.append("--recover-path-text")
        code = backend_main(command)
        payload = json.loads(backend_json.read_text())
        if code != 0 or not payload["ok"] or not raw.is_file():
            raise RuntimeError(
                "PAGE_BACKEND_FAILED: " + payload.get("error", "no DXF produced")
            )
        universal = (
            target
            if request.profile == "universal"
            else target.with_suffix(".universal.dxf")
        )
        profile = emit_universal(
            raw,
            universal,
            seed=args.seed,
            deterministic=request.deterministic,
            resource_root=target.parent,
            request=request,
        )
        gc.collect()
        validation = validate_dxf(
            universal,
            profile="universal",
            backend_payload=payload,
            dimension_p95_limit=request.dimension_p95_limit,
            allow_paper_space=mode == "sheet",
            request=request,
        )
        outputs = [universal.name] if request.profile == "universal" else []
        r12_profile = r12_validation = None
        if request.profile == "legacy-r12" or request.emit_r12:
            r12 = (
                target
                if request.profile == "legacy-r12"
                else target.with_suffix(".r12.dxf")
            )
            r12_profile = emit_legacy_r12(
                universal,
                r12,
                seed=args.seed + ":r12",
                deterministic=request.deterministic,
            ).to_dict()
            r12_validation = validate_dxf(
                r12,
                profile="legacy-r12",
                backend_payload=payload,
                dimension_p95_limit=request.dimension_p95_limit,
                allow_paper_space=mode == "sheet",
                request=request,
            )
            outputs.append(r12.name)
        validations = [validation] + ([r12_validation] if r12_validation else [])
        quality_ok = all(v["valid"] and not v["warnings"] for v in validations)
        if profile.warnings or (
            r12_profile and (r12_profile["warnings"] or r12_profile["downgraded"])
        ):
            quality_ok = False
        result = {
            "page": args.page + 1,
            "request": request.model_dump(),
            "status": "ok" if quality_ok else "degraded",
            "backend": payload,
            "universal_profile": profile.to_dict(),
            "universal_validation": validation,
            "r12_profile": r12_profile,
            "r12_validation": r12_validation,
            "output_names": outputs,
        }
    except Exception as exc:
        result = {
            "page": args.page + 1,
            "status": "failed",
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
    result_file.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 3 if result["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
