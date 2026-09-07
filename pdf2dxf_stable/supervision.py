"""Monitor the complete conversion process tree, including final DXF export."""

from dataclasses import dataclass
from pathlib import Path
import os
import signal
import subprocess
import time
import psutil


@dataclass
class ProcessOutcome:
    returncode: int
    reason: str | None
    peak_rss_bytes: int
    elapsed_seconds: float


def _kill_tree(proc):
    try:
        root = psutil.Process(proc.pid)
        children = root.children(recursive=True)
    except psutil.NoSuchProcess:
        children = []
    if os.name == "posix":
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    else:
        for child in reversed(children):
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        proc.terminate()
    try:
        proc.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass
    # On macOS a group containing only reparented zombies can return EPERM.
    # Signal only live descendants, preserving psutil's process identity check.
    living = []
    for child in children:
        try:
            if child.is_running() and child.status() != psutil.STATUS_ZOMBIE:
                living.append(child)
        except psutil.NoSuchProcess:
            pass
    if os.name == "posix" and (proc.poll() is None or living):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            # Each known live child is still killed individually below.
            pass
    for child in reversed(living):
        try:
            child.kill()
        except psutil.NoSuchProcess:
            pass
    if proc.poll() is None:
        proc.kill()
    proc.wait()


def run_supervised(
    command, *, log, workdir, timeout, memory_mb, disk_mb, env=None, cancel_event=None
):
    started = time.monotonic()
    peak = 0
    reason = None
    last_disk_check = 0.0
    if cancel_event is not None and cancel_event.is_set():
        return ProcessOutcome(-1, "CANCELLED", 0, 0.0)
    with Path(log).open("wb") as output:
        proc = subprocess.Popen(
            command,
            stdout=output,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=os.name == "posix",
        )
        try:
            root = psutil.Process(proc.pid)
            while proc.poll() is None:
                elapsed = time.monotonic() - started
                rss = 0
                try:
                    processes = [root, *root.children(recursive=True)]
                except psutil.NoSuchProcess:
                    processes = []
                for process in processes:
                    try:
                        rss += process.memory_info().rss
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                peak = max(peak, rss)
                if cancel_event is not None and cancel_event.is_set():
                    reason = "CANCELLED"
                elif elapsed > timeout:
                    reason = "PAGE_TIMEOUT"
                elif rss > memory_mb * 1024 * 1024:
                    reason = "MEMORY_LIMIT"
                if elapsed - last_disk_check >= 0.5:
                    size = 0
                    for file in Path(workdir).rglob("*"):
                        try:
                            if file.is_file():
                                size += file.stat().st_size
                        except FileNotFoundError:
                            pass
                    if size > disk_mb * 1024 * 1024:
                        reason = "TEMP_DISK_LIMIT"
                    last_disk_check = elapsed
                if reason:
                    _kill_tree(proc)
                    break
                time.sleep(0.1)
        except BaseException:
            _kill_tree(proc)
            raise
    return ProcessOutcome(proc.returncode, reason, peak, time.monotonic() - started)
