from __future__ import annotations
import shutil
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass(slots=True)
class RepairAttempt:
    method: str
    output: str | None
    success: bool
    message: str = ""
    returncode: int | None = None


@dataclass(slots=True)
class RepairResult:
    source: str
    selected: str | None
    attempts: list[RepairAttempt]
    repaired: bool

    def to_dict(self):
        return asdict(self)


def _can_open(path: Path) -> tuple[bool, str]:
    try:
        import fitz

        with fitz.open(path) as doc:
            if not doc.is_pdf:
                return False, "NOT_PDF: input is not a PDF document"
            if doc.needs_pass:
                return (
                    False,
                    "PASSWORD_REQUIRED: encrypted PDFs must be unlocked before conversion",
                )
            if doc.page_count <= 0:
                return False, "zero pages"
            _ = doc[0].rect
        return True, ""
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def recover_pdf(source: str | Path, work_dir: str | Path) -> RepairResult:
    source, work = Path(source), Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    attempts = []
    ok, msg = _can_open(source)
    attempts.append(RepairAttempt("original", str(source), ok, msg))
    if ok:
        return RepairResult(str(source), str(source), attempts, False)
    if not source.is_file() or msg.startswith(("NOT_PDF:", "PASSWORD_REQUIRED:")):
        return RepairResult(str(source), None, attempts, False)

    qpdf = shutil.which("qpdf")
    if qpdf:
        out = work / f"{source.stem}.qpdf.pdf"
        cmd = [qpdf, "--warning-exit-0", str(source), str(out)]
        attempt = _repair_tool("qpdf", cmd, out)
        attempts.append(attempt)
        if attempt.success:
            return RepairResult(str(source), str(out), attempts, True)
    else:
        attempts.append(RepairAttempt("qpdf", None, False, "qpdf not installed"))

    mutool = shutil.which("mutool")
    if mutool:
        out = work / f"{source.stem}.mutool.pdf"
        attempt = _repair_tool(
            "mutool-clean", [mutool, "clean", "-gg", str(source), str(out)], out
        )
        attempts.append(attempt)
        if attempt.success:
            return RepairResult(str(source), str(out), attempts, True)
    else:
        attempts.append(
            RepairAttempt("mutool-clean", None, False, "mutool not installed")
        )

    # PyMuPDF rewrite is the final local recovery path, never the first step.
    try:
        import fitz

        out = work / f"{source.stem}.mupdf-rewrite.pdf"
        with fitz.open(source) as doc:
            doc.save(out, garbage=4, deflate=True, clean=True)
        ok2, msg2 = _can_open(out)
        attempts.append(
            RepairAttempt("mupdf-rewrite", str(out), ok2, msg2, 0 if ok2 else 1)
        )
        if ok2:
            return RepairResult(str(source), str(out), attempts, True)
    except Exception as exc:
        attempts.append(
            RepairAttempt("mupdf-rewrite", None, False, f"{type(exc).__name__}: {exc}")
        )
    return RepairResult(str(source), None, attempts, False)


def _repair_tool(method, command, output):
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return RepairAttempt(method, str(output), False, "REPAIR_TOOL_TIMEOUT")
    except OSError as exc:
        return RepairAttempt(method, str(output), False, f"REPAIR_TOOL_FAILED: {exc}")
    ok, reason = (
        _can_open(output)
        if output.exists()
        else (False, (proc.stderr or proc.stdout)[-2000:])
    )
    return RepairAttempt(method, str(output), ok, reason, proc.returncode)
