from __future__ import annotations
import concurrent.futures
import hashlib
import json
import time
import threading
from functools import partial
from pathlib import Path
from .core import Converter, _write_json
from .paths import protect_inputs
from .request import ConversionRequest


def _collect(source):
    p = Path(source).expanduser().resolve()
    if p.is_dir():
        out = sorted(
            q for q in p.rglob("*") if q.is_file() and q.suffix.lower() == ".pdf"
        )
    elif p.suffix.lower() in {".json", ".yaml", ".yml"}:
        text = p.read_text(encoding="utf-8")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            try:
                import yaml

                data = yaml.safe_load(text)
            except Exception as exc:
                raise ValueError(f"cannot parse manifest: {exc}") from exc
        rows = (
            (data.get("documents") or data.get("files") or data.get("corpus") or [])
            if isinstance(data, dict)
            else data
        )
        out = []
        if not isinstance(rows, list):
            raise ValueError("manifest must contain a list of PDF paths")
        for row in rows:
            value = row.get("path") if isinstance(row, dict) else row
            if not isinstance(value, str) or not value.strip():
                raise ValueError("manifest entries must contain a nonempty PDF path")
            q = Path(value).expanduser()
            q = q if q.is_absolute() else p.parent / q
            out.append(q)
    else:
        out = [p]
    if not out:
        raise ValueError("no PDF inputs found in source or manifest")
    if any(q.suffix.lower() != ".pdf" for q in out):
        raise ValueError("source and manifest entries must be PDF paths")
    return list(dict.fromkeys(q.resolve() for q in out))


def _destination(path, out):
    path = Path(path).resolve()
    identifier = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:20]
    name = path.stem[:40] + "__" + identifier
    return Path(out) / name / (name + ".dxf")


def _one(args, *, cancel_event=None):
    path, out, request_dict = args
    request = ConversionRequest(**request_dict)
    target = _destination(path, out)
    try:
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("CANCELLED: batch item has not started")
        return (
            Converter()
            .convert(path, target, request, cancel_event=cancel_event)
            .to_dict()
        )
    except Exception as exc:
        return {
            "status": "failed",
            "source": str(path),
            "artifacts": [],
            "errors": [{"code": "BATCH_ITEM_FAILED", "message": str(exc)}],
        }


def run_batch(source, output_dir, request: ConversionRequest):
    files = _collect(source)
    summary = Path(output_dir).expanduser().resolve() / "batch_summary.json"
    protect_inputs(summary, [source, *files, *request.outline_font_catalogs])
    started = time.time()
    rows = []
    args = [(str(p), str(summary.parent), request.model_dump()) for p in files]
    cancelled = threading.Event()
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max(1, request.workers)
    ) as pool:
        try:
            for row in pool.map(partial(_one, cancel_event=cancelled), args):
                rows.append(row)
        except BaseException:
            # Signal before the executor waits for active workers to exit.
            cancelled.set()
            raise
    payload = {
        "schema": "pdf2dxf.stable.batch.v2",
        "source": str(source),
        "output_dir": str(output_dir),
        "count": len(rows),
        "ok": sum(r["status"] == "ok" for r in rows),
        "degraded": sum(r["status"] == "degraded" for r in rows),
        "failed": sum(r["status"] == "failed" for r in rows),
        "elapsed_seconds": time.time() - started,
        "jobs": rows,
    }
    out = summary.parent
    out.mkdir(parents=True, exist_ok=True)
    _write_json(summary, payload)
    return payload


def run_regression(source, output_dir, request: ConversionRequest):
    files = _collect(source)
    summary = Path(output_dir).expanduser().resolve() / "regression_summary.json"
    protect_inputs(summary, [source, *files, *request.outline_font_catalogs])
    rows = []
    request = request.model_copy(update={"deterministic": True})
    for p in files:
        runs = []
        for index in (1, 2):
            result = _one((p, summary.parent / f"run_{index}", request.model_dump()))
            dxf = [a for a in result["artifacts"] if a["kind"] == "dxf"]
            runs.append(
                {
                    "status": result["status"],
                    "hashes": [a["sha256"] for a in dxf],
                    "result": result,
                }
            )
        rows.append(
            {
                "source": str(p),
                "deterministic": runs[0]["hashes"] == runs[1]["hashes"]
                and bool(runs[0]["hashes"]),
                "runs": runs,
            }
        )
    payload = {
        "schema": "pdf2dxf.stable.regression.v2",
        "count": len(rows),
        "passed": sum(
            r["deterministic"] and all(x["status"] == "ok" for x in r["runs"])
            for r in rows
        ),
        "failed": sum(
            not (r["deterministic"] and all(x["status"] == "ok" for x in r["runs"]))
            for r in rows
        ),
        "documents": rows,
    }
    out = summary.parent
    out.mkdir(parents=True, exist_ok=True)
    _write_json(summary, payload)
    return payload
