import json
import sys
import threading
import time

import psutil
import pytest

from pdf2dxf_stable.batch import run_batch
from pdf2dxf_stable.cli import main
from pdf2dxf_stable.request import ConversionRequest
from pdf2dxf_stable.supervision import run_supervised
from pdf2dxf_stable.locking import output_lock


def test_cancelled_process_tree_exits_and_leaves_no_child(tmp_path):
    cancelled = threading.Event()
    pidfile = tmp_path / "pid.json"
    code = (
        "import json,os,subprocess,sys,time; from pathlib import Path; "
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']); "
        f"Path({str(pidfile)!r}).write_text(json.dumps([os.getpid(),child.pid])); "
        "time.sleep(30)"
    )

    def cancel_when_started():
        deadline = time.monotonic() + 5
        while not pidfile.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        cancelled.set()

    thread = threading.Thread(target=cancel_when_started)
    thread.start()
    try:
        result = run_supervised(
            [sys.executable, "-c", code],
            log=tmp_path / "worker.log",
            workdir=tmp_path,
            timeout=10,
            memory_mb=512,
            disk_mb=1024,
            cancel_event=cancelled,
        )
    finally:
        thread.join(timeout=6)
    assert result.reason == "CANCELLED" and result.elapsed_seconds < 5
    for pid in json.loads(pidfile.read_text()):
        assert (
            not psutil.pid_exists(pid)
            or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
        )


def test_batch_interrupt_signals_workers_before_join(tmp_path, monkeypatch):
    from pdf2dxf_stable import batch

    source = tmp_path / "input.pdf"
    source.touch()
    stopped = threading.Event()

    def worker(args, *, cancel_event):
        assert cancel_event.wait(3), "batch waited before sending cancellation"
        stopped.set()

    class InterruptedPool:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def map(self, function, args):
            self.thread = threading.Thread(target=function, args=(args[0],))
            self.thread.start()
            raise KeyboardInterrupt

        def __exit__(self, *args):
            self.thread.join(timeout=4)

    monkeypatch.setattr(batch, "_one", worker)
    monkeypatch.setattr(batch.concurrent.futures, "ThreadPoolExecutor", InterruptedPool)
    with pytest.raises(KeyboardInterrupt):
        run_batch(source, tmp_path / "out", ConversionRequest())
    assert stopped.is_set()


def test_cli_cancel_uses_exit_130_without_traceback(monkeypatch, capsys):
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr("pdf2dxf_stable.cli._execute", interrupted)
    assert main(["inspect", "input.pdf"]) == 130
    assert "cancelled" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["faces", "build"])
def test_invalid_font_has_actionable_cli_error(tmp_path, capsys, command):
    font = tmp_path / "broken.ttf"
    font.write_bytes(b"not a font")
    args = ["font-catalog", command, str(font)]
    if command == "build":
        args += ["-o", str(tmp_path / "out.p2dfont")]
    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == 2
    assert "Traceback" not in capsys.readouterr().err


def test_output_lock_times_out_and_can_be_cancelled(tmp_path):
    path = tmp_path / "output.dxf.lock"
    with output_lock(path, timeout=1):
        with pytest.raises(TimeoutError, match="OUTPUT_LOCK_TIMEOUT"):
            with output_lock(path, timeout=0.05):
                pytest.fail("two output owners acquired the same lock")
        cancelled = threading.Event()
        cancelled.set()
        with pytest.raises(InterruptedError, match="CANCELLED"):
            with output_lock(path, timeout=1, cancel_event=cancelled):
                pytest.fail("cancelled output acquired a lock")
    with output_lock(path, timeout=1):
        pass


def test_interrupted_conversion_persists_cancelled_report(tmp_path, monkeypatch):
    from pdf2dxf_stable import Converter, core

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(core, "run_supervised", interrupt)
    with pytest.raises(KeyboardInterrupt):
        Converter().convert("source.pdf", tmp_path / "output.dxf", ConversionRequest())
    report = json.loads((tmp_path / "output.report.json").read_text())
    assert report["errors"][-1]["code"] == "CANCELLED"
    assert report["status"] == "failed"


@pytest.mark.parametrize("operation", ["rgb", "xdata"])
@pytest.mark.parametrize("exception", [KeyboardInterrupt, SystemExit])
def test_dense_geometry_optional_metadata_does_not_swallow_cancellation(
    operation, exception
):
    from types import SimpleNamespace
    from pdf2dxf_stable.engine.geometry.construction import (
        ConstructionGraphicsKernelV15,
        _Bucket,
    )

    class Entity:
        @property
        def rgb(self):
            return None

        @rgb.setter
        def rgb(self, value):
            if operation == "rgb":
                raise exception()

        def set_xdata(self, *args):
            if operation == "xdata":
                raise exception()

    kernel = ConstructionGraphicsKernelV15()
    kernel.config.add_xdata = True
    msp = SimpleNamespace(add_line=lambda *args, **kwargs: Entity())
    stats = SimpleNamespace(
        dense_pattern_duplicates_or_joins=0,
        line_entities=0,
        dense_pattern_entities_out=0,
    )
    buckets = {"one": _Bucket({}, (0, 0, 0), 1.0, [((0, 0), (1, 1))])}
    with pytest.raises(exception):
        kernel._emit_buckets(msp, buckets, stats, 0)
