"""Create a reviewable standalone source snapshot; never publish or copy Git history."""

import argparse
import hashlib
import json
from pathlib import Path
import zipfile


ROOT_FILES = (
    "README.md",
    "README.en.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "THIRD_PARTY_NOTICES.md",
    "SOURCE_ORIGIN.json",
    ".gitignore",
    "setup.py",
    "pyproject.toml",
    "MANIFEST.in",
)
TREES = {
    "pdf2dxf_stable": {".py"},
    "tests": {".py", ".json"},
    "tools": {".py"},
    "docs": {".md", ".json"},
    ".github": {".md", ".yml"},
}
ASSETS = (
    "pdf2dxf_stable/engine/text/assets/chinese_glyph_templates.json",
    "pdf2dxf_stable/engine/text/assets/engineering_glyphs.json",
)


def release_files(source):
    source = Path(source).resolve()
    selected = {Path(name) for name in (*ROOT_FILES, *ASSETS)}
    # A license is included only after the owner has supplied it.
    selected.update(
        Path(name) for name in ("LICENSE", "NOTICE") if (source / name).is_file()
    )
    for tree, suffixes in TREES.items():
        selected.update(
            path.relative_to(source)
            for path in (source / tree).rglob("*")
            if path.is_file()
            and path.suffix in suffixes
            and not any(
                part.startswith(".") or part == "__pycache__"
                for part in path.relative_to(source / tree).parts
            )
        )
    for relative in sorted(selected):
        path = source / relative
        if any(
            parent.is_symlink() for parent in (path, *path.parents) if parent != source
        ):
            raise ValueError(f"release inputs cannot be symlinks: {relative}")
        if not path.is_file() or not path.resolve().is_relative_to(source):
            raise ValueError(
                f"release input is missing or outside the source: {relative}"
            )
    return sorted(selected)


def export_release(source, destination):
    source, destination = (
        Path(source).resolve(),
        Path(destination).expanduser().resolve(),
    )
    archive = destination.with_name(destination.name + ".zip")
    if destination.exists() or archive.exists():
        raise ValueError("release destination and ZIP must not already exist")
    if source == destination or source.is_relative_to(destination):
        raise ValueError("release destination must not contain the source directory")
    files = release_files(source)
    payloads = {path.as_posix(): (source / path).read_bytes() for path in files}
    origin = json.loads(payloads["SOURCE_ORIGIN.json"])
    manifest = {
        "schema": "pdf2dxf.source_snapshot.v1",
        "publication_status": origin.get("publication_status", "local_review_only"),
        "license_status": origin.get("project_license", "pending_owner_decision"),
        "files": {
            name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            for name, data in sorted(payloads.items())
        },
    }
    payloads["RELEASE_MANIFEST.json"] = (
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    ).encode()
    destination.mkdir(parents=True)
    for name, data in payloads.items():
        output = destination / name
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, data in sorted(payloads.items()):
            entry = zipfile.ZipInfo(
                f"{destination.name}/{name}", date_time=(2026, 1, 1, 0, 0, 0)
            )
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            bundle.writestr(entry, data)
    return {
        "directory": str(destination),
        "archive": str(archive),
        "files": len(payloads),
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination")
    args = parser.parse_args()
    print(
        json.dumps(
            export_release(Path(__file__).resolve().parents[1], args.destination),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
