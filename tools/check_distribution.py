"""Check distribution contents and report the separate publication authorization gate."""

import argparse
from email import message_from_bytes
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
import zipfile


PRIVATE_PARTS = {
    "verification",
    "tmp",
    ".git",
    ".venv",
    "__pycache__",
    "PROVENANCE.json",
}
PRIVATE_SUFFIXES = {
    ".pdf",
    ".dxf",
    ".p2dfont",
    ".ttf",
    ".otf",
    ".ttc",
    ".otc",
    ".png",
    ".pyc",
}
PERSONAL_PATH = re.compile(rb"(?:/Users/|/home/)[A-Za-z0-9_][^\s\"'<>]*")


def _members(path):
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError(f"symbolic link in distribution: {info.filename}")
                if not info.is_dir():
                    yield info.filename, archive.read(info)
    else:
        with tarfile.open(path, "r:gz") as archive:
            for info in archive:
                if info.isdir():
                    continue
                if not info.isfile():
                    raise ValueError(f"non-regular distribution member: {info.name}")
                yield info.name, archive.extractfile(info).read()


def check_distribution(path, *, require_license=False):
    path = Path(path)
    if not (path.suffix == ".whl" or path.name.endswith(".tar.gz")):
        raise ValueError("expected a wheel or .tar.gz source distribution")
    seen = set()
    notices = set()
    license_expressions = []
    for name, data in _members(path):
        relative = PurePosixPath(name)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or "\\" in name
            or name in seen
        ):
            raise ValueError(f"unsafe or duplicate distribution path: {name}")
        seen.add(name)
        if relative.name in {"METADATA", "PKG-INFO"}:
            license_expressions.append(
                message_from_bytes(data).get("License-Expression")
            )
        if (
            relative.name in {"LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"}
            and data.strip()
        ):
            notices.add(relative.name)
        if (
            PRIVATE_PARTS.intersection(relative.parts)
            or relative.suffix.lower() in PRIVATE_SUFFIXES
        ):
            raise ValueError(f"private/generated file in distribution: {name}")
        if PERSONAL_PATH.search(data):
            raise ValueError(f"personal filesystem path in distribution: {name}")
    required = (
        "pdf2dxf_stable/cli.py",
        "pdf2dxf_stable/preflight.py",
        "pdf2dxf_stable/engine/text/assets/chinese_glyph_templates.json",
        "pdf2dxf_stable/engine/text/assets/engineering_glyphs.json",
    )
    for name in required:
        if not any(member == name or member.endswith("/" + name) for member in seen):
            raise ValueError(f"missing required distribution file: {name}")
    if require_license:
        missing = {"LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"} - notices
        if missing:
            raise ValueError(f"missing distribution license notices: {sorted(missing)}")
        if not license_expressions or any(
            value != "AGPL-3.0-only" for value in license_expressions
        ):
            raise ValueError(
                "distribution metadata must declare License-Expression: AGPL-3.0-only"
            )
    return {"file": path.name, "members": len(seen), "content_check": "passed"}


def publication_blockers(source):
    source = Path(source)
    origin = json.loads((source / "SOURCE_ORIGIN.json").read_text(encoding="utf-8"))
    blockers = []
    if (
        not (source / "LICENSE").is_file()
        or not (source / "LICENSE").read_bytes().strip()
    ):
        blockers.append("LICENSE_NOT_SELECTED")
    if origin.get("project_license") in {None, "", "pending_owner_decision"}:
        blockers.append("PROJECT_LICENSE_UNCONFIRMED")
    if origin.get("source_and_template_redistribution_rights") != "confirmed_by_owner":
        blockers.append("SOURCE_AND_TEMPLATE_RIGHTS_UNCONFIRMED")
    return blockers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs="+")
    parser.add_argument(
        "--public",
        action="store_true",
        help="also require the owner's license/rights metadata",
    )
    args = parser.parse_args()
    try:
        results = [
            check_distribution(path, require_license=args.public)
            for path in args.artifacts
        ]
        blockers = publication_blockers(Path(__file__).resolve().parents[1])
    except (ValueError, OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
        parser.error(str(exc))
    print(
        json.dumps({"artifacts": results, "publication_blockers": blockers}, indent=2)
    )
    return 5 if args.public and blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())
