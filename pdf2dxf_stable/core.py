from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from .determinism import sha256
from .locking import output_lock
from .paths import protect_inputs
from .request import ConversionArtifact, ConversionRequest, ConversionResult
from .resources import atomic_copy
from .supervision import run_supervised
from .version import __version__


def _sheet_like(path, mode):
    if mode == "sheet":
        return True
    name = Path(path).name.upper()
    return name.startswith(("N", "T")) or any(
        token in name for token in ("目录", "说明", "专篇", "表格", "做法表", "门窗表")
    )


def _pages(path, spec):
    import fitz

    with fitz.open(path) as doc:
        count = doc.page_count
    if count == 0:
        raise ValueError("PDF_HAS_NO_PAGES")
    if spec == "all":
        return list(range(count))
    if not spec or any(not isinstance(n, int) or n < 1 or n > count for n in spec):
        raise ValueError(f"INVALID_PAGE_SELECTION: valid page range is 1..{count}")
    return sorted({n - 1 for n in spec})


def _write_json(path, data):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix="." + path.name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class Converter:
    def convert(
        self,
        source,
        target,
        request: ConversionRequest,
        events=None,
        *,
        cancel_event=None,
    ):
        source, target = (
            Path(source).expanduser().resolve(),
            Path(target).expanduser().resolve(),
        )
        if target.suffix.lower() != ".dxf":
            raise ValueError("output path must end in .dxf")
        inputs = [source, *request.outline_font_catalogs]
        for destination in (
            target,
            target.with_suffix(".report.json"),
            target.with_suffix(target.suffix + ".lock"),
        ):
            protect_inputs(destination, inputs)
        target.parent.mkdir(parents=True, exist_ok=True)
        # OS locks release after a crash. Keep the file to avoid inode races.
        lock = target.with_suffix(target.suffix + ".lock")
        with output_lock(
            lock, timeout=request.timeout_seconds, cancel_event=cancel_event
        ):
            return self._convert(source, target, request, events, cancel_event)

    def _convert(self, source, target, request, events, cancel_event=None):
        job = Path(tempfile.mkdtemp(prefix=target.stem + "_work_", dir=target.parent))
        pages, artifacts, warnings, errors = [], [], [], []
        report = target.with_suffix(".report.json")
        preflight = {}
        try:
            env = dict(
                os.environ,
                PYTHONHASHSEED="0",
                OMP_NUM_THREADS="1",
                OPENBLAS_NUM_THREADS="1",
            )
            request_file, result_file = job / "request.json", job / "preflight.json"
            request_file.write_text(request.model_dump_json(), encoding="utf-8")
            outcome = run_supervised(
                [
                    sys.executable,
                    "-m",
                    "pdf2dxf_stable.preflight",
                    "--source",
                    str(source),
                    "--workdir",
                    str(job / "repair"),
                    "--request",
                    str(request_file),
                    "--result",
                    str(result_file),
                ],
                log=job / "preflight.log",
                workdir=job,
                timeout=request.timeout_seconds,
                memory_mb=request.memory_limit_mb,
                disk_mb=request.temp_disk_limit_mb,
                env=env,
                cancel_event=cancel_event,
            )
            preflight = (
                json.loads(result_file.read_text(encoding="utf-8"))
                if result_file.is_file()
                else {}
            )
            preflight["resources"] = asdict(outcome)
            if outcome.reason or outcome.returncode != 0 or not preflight.get("ok"):
                raise ValueError(
                    f"{outcome.reason or 'PDF_UNRECOVERABLE'}: "
                    + json.dumps(preflight, ensure_ascii=False)
                )
            selected = Path(preflight["repair"]["selected"])
            selected_pages = preflight["selected_pages"]
            inputs = [source, *request.outline_font_catalogs]
            # Check every page before publishing any page of a multi-page document.
            for page in selected_pages:
                suffix = "" if len(selected_pages) == 1 else f"_p{page + 1:03d}"
                final = target.with_name(target.stem + suffix + target.suffix)
                protect_inputs(final, inputs)
                if request.emit_r12:
                    protect_inputs(final.with_suffix(".r12.dxf"), inputs)
            src_hash = preflight["source_sha256"]
            for page in selected_pages:
                page_dir = job / f"p{page + 1:03d}"
                page_dir.mkdir()
                suffix = "" if len(selected_pages) == 1 else f"_p{page + 1:03d}"
                output = page_dir / (target.stem + suffix + target.suffix)
                mode = request.mode
                if mode == "auto":
                    mode = "sheet" if _sheet_like(source, mode) else "blocks"
                effective = request.model_copy(update={"mode": mode})
                request_file, result_file = (
                    page_dir / "request.json",
                    page_dir / "result.json",
                )
                request_file.write_text(effective.model_dump_json(), encoding="utf-8")
                seed = hashlib.sha256(
                    (
                        src_hash
                        + f":{page}:"
                        + __version__
                        + ":"
                        + json.dumps(effective.model_dump(), sort_keys=True)
                    ).encode()
                ).hexdigest()
                command = [
                    sys.executable,
                    "-m",
                    "pdf2dxf_stable.page_worker",
                    "--source",
                    str(selected),
                    "--page",
                    str(page),
                    "--output",
                    str(output),
                    "--request",
                    str(request_file),
                    "--result",
                    str(result_file),
                    "--seed",
                    seed,
                ]
                if callable(events):
                    events({"event": "page_started", "page": page + 1})
                outcome = run_supervised(
                    command,
                    log=page_dir / "worker.log",
                    workdir=job,
                    timeout=request.timeout_seconds,
                    memory_mb=request.memory_limit_mb,
                    disk_mb=request.temp_disk_limit_mb,
                    env=env,
                    cancel_event=cancel_event,
                )
                if (
                    outcome.reason
                    or outcome.returncode != 0
                    or not result_file.is_file()
                ):
                    detail = (
                        json.loads(result_file.read_text(encoding="utf-8"))
                        if result_file.is_file()
                        else {}
                    )
                    row = {
                        "page": page + 1,
                        "status": "failed",
                        "resources": asdict(outcome),
                        "detail": detail,
                    }
                    errors.append(
                        {
                            "code": outcome.reason or "PAGE_BACKEND_FAILED",
                            "page": page + 1,
                            "log": str(page_dir / "worker.log"),
                            "detail": detail,
                        }
                    )
                else:
                    row = json.loads(result_file.read_text(encoding="utf-8"))
                    row["resources"] = asdict(outcome)
                    # Resources precede DXFs so a published IMAGEDEF always resolves.
                    for image in sorted((page_dir / "images").glob("*")):
                        final = target.parent / "images" / image.name
                        protect_inputs(final, inputs)
                        atomic_copy(image, final)
                        artifacts.append(
                            ConversionArtifact(
                                "image", str(final), sha256(final), final.stat().st_size
                            )
                        )
                    for name in row.pop("output_names"):
                        final = target.parent / name
                        protect_inputs(final, inputs)
                        atomic_copy(page_dir / name, final)
                        artifacts.append(
                            ConversionArtifact(
                                "dxf", str(final), sha256(final), final.stat().st_size
                            )
                        )
                        for key in ("universal_validation", "r12_validation"):
                            if row.get(key) and Path(row[key]["path"]).name == name:
                                row[key]["path"] = str(final)
                        for key in ("universal_profile", "r12_profile"):
                            if (
                                row.get(key)
                                and Path(row[key]["output_dxf"]).name == name
                            ):
                                row[key]["output_dxf"] = str(final)
                    if row["status"] != "ok":
                        warnings.append({"code": "PAGE_QUALITY_GATE", "page": page + 1})
                pages.append(row)
                if callable(events):
                    events(
                        {
                            "event": "page_finished",
                            "page": page + 1,
                            "status": row["status"],
                        }
                    )
                if row["status"] == "failed" and not request.allow_partial:
                    break
                if cancel_event is not None and cancel_event.is_set():
                    break
        # The public conversion boundary reports worker and filesystem failures alike.
        except KeyboardInterrupt:
            # The supervisor has already killed the active process tree.
            errors.append({"code": "CANCELLED", "message": "conversion interrupted"})
            result = ConversionResult(
                "degraded" if any(a.kind == "dxf" for a in artifacts) else "failed",
                str(source),
                artifacts,
                pages,
                warnings,
                errors,
                str(report),
                input_validation=preflight,
            )
            _write_json(report, result.to_dict())
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append({"code": "CONVERSION_FAILED", "message": str(exc)})
        status = (
            "failed"
            if not any(a.kind == "dxf" for a in artifacts)
            else ("degraded" if errors or warnings else "ok")
        )
        # A report cannot hash itself; its hash lives in the returned result only.
        artifacts = list({(a.kind, a.path): a for a in artifacts}.values())
        artifacts.append(ConversionArtifact("report", str(report)))
        result = ConversionResult(
            status,
            str(source),
            artifacts,
            pages,
            warnings,
            errors,
            str(report),
            input_validation=preflight,
        )
        _write_json(report, result.to_dict())
        artifacts[-1].sha256, artifacts[-1].size_bytes = (
            sha256(report),
            report.stat().st_size,
        )
        return result
