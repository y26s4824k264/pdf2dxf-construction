"""Verify optional font resource bundles without accessing fonts or the network."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .font_catalog import FontCatalogError, describe_font_catalog, load_font_catalog

FONT_BUNDLE_SCHEMA = "pdf2dxf.font_bundle.v1"
MAX_BUNDLE_FILES = 128
MAX_BUNDLE_FILE_BYTES = 200 * 1024 * 1024


def bundle_file(root: Path, name: str) -> Path:
    """Resolve an ordinary relative file; never follow bundle-owned symlinks."""
    if (
        not isinstance(name, str)
        or not name
        or "\\" in name
        or "\x00" in name
        or PurePosixPath(name).is_absolute()
        or PureWindowsPath(name).drive
        or any(part in {"", ".", ".."} for part in name.split("/"))
    ):
        raise FontCatalogError("font bundle contains an unsafe relative path")
    root = root.resolve()
    result = root.joinpath(*name.split("/"))
    cursor = result
    while cursor != root:
        if cursor.is_symlink():
            raise FontCatalogError("font bundle files cannot be symlinks")
        cursor = cursor.parent
    return result


def file_record(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"sha256": digest.hexdigest(), "bytes": path.stat().st_size}


def load_font_bundle(path: str | Path) -> dict[str, Any]:
    """Verify all declared files and return absolute catalog/protected paths.

    Hashes detect corruption, not publisher authenticity. Compare the downloaded
    bundle's SHA-256 against its trusted release before unpacking it.
    """
    source = Path(path).expanduser()
    try:
        if source.is_symlink() or source.stat().st_size > 2 * 1024 * 1024:
            raise FontCatalogError("invalid font bundle manifest file")
        source = source.resolve()
        manifest = json.loads(source.read_text(encoding="utf-8"))
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema") != FONT_BUNDLE_SCHEMA
        ):
            raise FontCatalogError("unsupported font bundle schema")
        records, catalogs = manifest.get("files"), manifest.get("catalogs")
        if not isinstance(records, dict) or not 1 <= len(records) <= MAX_BUNDLE_FILES:
            raise FontCatalogError("invalid font bundle file count")
        if not isinstance(catalogs, list) or not 1 <= len(catalogs) <= 32:
            raise FontCatalogError("invalid font bundle catalog count")
        files = {}
        for name, record in records.items():
            target = bundle_file(source.parent, name)
            if not (
                name in {"SOURCE_LOCK.json", "COVERAGE.json", "NOTICE.md"}
                or (name.startswith("catalogs/") and name.endswith(".p2dfont"))
                or (name.startswith("licenses/") and target.suffix in {".txt", ".md"})
            ):
                raise FontCatalogError("font bundle contains an unsupported file type")
            if target == source or not target.is_file() or not isinstance(record, dict):
                raise FontCatalogError("font bundle file is missing or invalid")
            size = record.get("bytes")
            if type(size) is not int or not 0 < size <= MAX_BUNDLE_FILE_BYTES:
                raise FontCatalogError("invalid font bundle file size")
            if target.stat().st_size != size or file_record(target) != record:
                raise FontCatalogError(f"font bundle file hash/size mismatch: {name}")
            files[name] = str(target)
        seen_ids, seen_paths = set(), set()
        paths = []
        for entry in catalogs:
            if not isinstance(entry, dict):
                raise FontCatalogError("invalid font bundle catalog entry")
            name, identifier = entry.get("path"), entry.get("id")
            licenses = entry.get("license_files")
            if (
                not isinstance(identifier, str)
                or not identifier
                or identifier in seen_ids
                or not isinstance(name, str)
                or name not in files
                or not name.endswith(".p2dfont")
                or name in seen_paths
                or not isinstance(entry.get("license"), str)
                or not entry["license"]
                or not isinstance(licenses, list)
                or not licenses
                or any(
                    not isinstance(item, str)
                    or item not in files
                    or not item.startswith("licenses/")
                    for item in licenses
                )
            ):
                raise FontCatalogError(
                    "invalid font bundle catalog or license reference"
                )
            seen_ids.add(identifier)
            seen_paths.add(name)
            paths.append(files[name])
        if {name for name in files if name.endswith(".p2dfont")} != seen_paths:
            raise FontCatalogError("font bundle has an undeclared catalog")
        return {
            "manifest": manifest,
            "path": str(source),
            "catalog_paths": paths,
            "protected_paths": [str(source), *files.values()],
        }
    except FontCatalogError:
        raise
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
        raise FontCatalogError(f"invalid font bundle: {exc}") from exc


def inspect_font_bundle(path: str | Path) -> dict[str, Any]:
    """Fully validate catalogs one at a time and report actual codepoint union."""
    bundle = load_font_bundle(path)
    codepoints: set[int] = set()
    summaries = []
    for entry, catalog_path in zip(
        bundle["manifest"]["catalogs"], bundle["catalog_paths"]
    ):
        catalog = load_font_catalog(catalog_path)
        if catalog.font["sha256"] != entry.get("source_sha256"):
            raise FontCatalogError("font bundle source hash disagrees with catalog")
        codepoints.update(template.codepoint for template in catalog.templates)
        summaries.append({"id": entry["id"], **describe_font_catalog(catalog)})
        del catalog
    from .font_catalog import HAN_RANGES

    return {
        "schema": FONT_BUNDLE_SCHEMA,
        "path": bundle["path"],
        "catalogs": summaries,
        "mapped_codepoint_union": len(codepoints),
        "han_codepoint_union": sum(
            any(start <= value <= end for start, end in HAN_RANGES)
            for value in codepoints
        ),
        "han_ranges": [
            {
                "start": f"U+{start:04X}",
                "end": f"U+{end:04X}",
                "mapped": sum(start <= value <= end for value in codepoints),
            }
            for start, end in HAN_RANGES
        ],
        "coverage_is_recognition_accuracy": False,
        "variation_sequences_supported": False,
    }
