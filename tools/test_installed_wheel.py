"""Run the tests with the installed wheel from a temporary, source-free directory."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    source = Path(__file__).resolve().parents[1]
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    with tempfile.TemporaryDirectory(prefix="pdf2dxf-wheel-tests-") as name:
        isolated = Path(name)
        for directory in ("tests", "tools"):
            shutil.copytree(
                source / directory,
                isolated / directory,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        check = (
            "from pathlib import Path; import pdf2dxf_stable; "
            "p = Path(pdf2dxf_stable.__file__).resolve(); print(p); "
            f"assert not p.is_relative_to(Path({str(source)!r}) / 'pdf2dxf_stable'), p; "
            "assert 'site-packages' in p.parts, p"
        )
        subprocess.run([sys.executable, "-c", check], cwd=isolated, env=env, check=True)
        subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "tests"],
            cwd=isolated,
            env=env,
            check=True,
        )


if __name__ == "__main__":
    main()
