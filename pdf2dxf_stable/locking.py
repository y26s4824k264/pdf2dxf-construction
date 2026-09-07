"""Bounded, cancellable output locks for POSIX and Windows."""

from contextlib import contextmanager
import errno
import os
import time


@contextmanager
def output_lock(path, *, timeout, cancel_event=None):
    deadline = time.monotonic() + timeout
    # Keep the lock inode after closing; unlinking permits concurrent lock owners.
    with path.open("a+b") as stream:
        if os.name == "nt" and os.fstat(stream.fileno()).st_size == 0:
            stream.write(b"0")
            stream.flush()
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise InterruptedError("CANCELLED: waiting for output lock")
            try:
                if os.name == "posix":
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    import msvcrt

                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                    raise
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"OUTPUT_LOCK_TIMEOUT: {path}") from exc
                if cancel_event is None:
                    time.sleep(0.05)
                else:
                    cancel_event.wait(0.05)
        try:
            yield
        finally:
            if os.name == "posix":
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            else:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
