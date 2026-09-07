"""Download pinned open fonts and build a separately licensed .p2dfont bundle.

Run from the source checkout with the package installed. Downloads happen only
when this explicit build tool is invoked; conversion remains offline.
"""

from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
import urllib.request
import zipfile

from fontTools.ttLib import TTFont

from pdf2dxf_stable.engine.text.font_bundle import (
    FONT_BUNDLE_SCHEMA,
    MAX_BUNDLE_FILE_BYTES,
    bundle_file,
    file_record,
    load_font_bundle,
)
from pdf2dxf_stable.engine.text.font_catalog import (
    CHINESE_RANGES,
    DEFAULT_TOLERANCE_DIVISORS,
    FONT_CATALOG_RASTER_DECIMALS,
    FONT_OUTLINE_POLICY,
    UNICODE_CJK_VERSION,
    FontCatalogError,
    build_font_catalog,
    describe_font_catalog,
    load_font_catalog,
)


def _check_bytes(data, record):
    if (
        len(data) != record["bytes"]
        or hashlib.sha256(data).hexdigest() != record["sha256"]
    ):
        raise ValueError("open font source hash/size mismatch")


def fetch_download(cache, name, record, *, offline=False):
    """Cache only checksum-verified bytes, preserving any existing cache entry."""
    target = bundle_file(cache, name)
    size = record["bytes"]
    if type(size) is not int or not 0 < size <= MAX_BUNDLE_FILE_BYTES:
        raise ValueError("open font download exceeds size limit")
    if target.exists():
        if target.stat().st_size != size or file_record(target) != {
            key: record[key] for key in ("sha256", "bytes")
        }:
            raise ValueError(f"open font cache hash/size mismatch: {name}")
        return target
    if offline:
        raise ValueError(f"open font source unavailable in offline cache: {name}")
    url = record["url"]
    if not isinstance(url, str) or not url.startswith("https://"):
        raise ValueError("open font downloads require HTTPS")
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/octet-stream",
            "User-Agent": "PDF2DXF-open-fonts",
        },
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".download-", dir=target.parent) as temp:
        part = Path(temp) / "payload"
        count = 0
        with (
            urllib.request.urlopen(request, timeout=60) as response,
            part.open("wb") as stream,
        ):
            if not response.url.startswith("https://"):
                raise ValueError("open font download redirected away from HTTPS")
            while chunk := response.read(1024 * 1024):
                count += len(chunk)
                if count > size:
                    raise ValueError("open font download exceeds declared size")
                stream.write(chunk)
        if file_record(part) != {key: record[key] for key in ("sha256", "bytes")}:
            raise ValueError(f"open font download hash/size mismatch: {name}")
        # Exclusive creation also protects against a concurrent cache writer.
        with target.open("xb") as output, part.open("rb") as source:
            shutil.copyfileobj(source, output)
    return target


def source_payload(cache, downloads, spec, *, offline=False):
    size = spec["bytes"]
    if type(size) is not int or not 0 < size <= MAX_BUNDLE_FILE_BYTES:
        raise ValueError("open font member exceeds size limit")
    name = spec["download"]
    source = fetch_download(cache, name, downloads[name], offline=offline)
    if "member" in spec:
        member = spec["member"]
        # Read one named member in memory. Never extract archive paths to disk.
        with zipfile.ZipFile(source) as archive:
            matches = [
                entry for entry in archive.infolist() if entry.filename == member
            ]
            if len(matches) != 1 or matches[0].file_size != size:
                raise ValueError("invalid open font archive member")
            data = archive.read(matches[0])
    else:
        data = source.read_bytes()
    _check_bytes(data, spec)
    return data


def _json_bytes(value):
    return (
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode()


def build_bundle(lock_path, cache, output, group, *, catalog_cache=None, offline=False):
    lock_path, cache, output = (
        Path(lock_path).resolve(),
        Path(cache).resolve(),
        Path(output).resolve(),
    )
    lock_data = lock_path.read_bytes()
    lock = json.loads(lock_data)
    if (
        lock.get("schema") != "pdf2dxf.open_font_sources.v1"
        or lock.get("charset") != "chinese"
    ):
        raise ValueError("unsupported open font source lock")
    fonts = [font for font in lock["fonts"] if group == "all" or font["group"] == group]
    if not 1 <= len(fonts) <= 32 or len({font["id"] for font in fonts}) != len(fonts):
        raise ValueError("invalid open font selection")
    if any(
        not isinstance(font["id"], str)
        or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", font["id"])
        for font in fonts
    ):
        raise ValueError("invalid open font identifier")
    archive_path = output.with_name(output.name + ".zip")
    if output.exists() or archive_path.exists():
        raise ValueError("font bundle output directory and ZIP must not already exist")
    # Only selected, verified payloads enter the distribution. Source fonts stay
    # in the build cache and are never copied into the runtime bundle or wheel.
    output.mkdir(parents=True)
    cache.mkdir(parents=True, exist_ok=True)
    records, entries, coverage = {}, [], []
    builder_versions = {
        name: version(name) for name in ("fonttools", "numpy", "opencv-python-headless")
    }
    with tempfile.TemporaryDirectory(
        prefix=".font-build-", dir=cache.parent
    ) as temporary:
        for font in fonts:
            identifier = font["id"]
            target = bundle_file(output, "catalogs/" + identifier + ".p2dfont")
            data = source_payload(
                cache, lock["downloads"], font["source"], offline=offline
            )
            source_name = (
                font["source"]
                .get("member", font["source"]["download"])
                .rsplit("/", 1)[-1]
            )
            source = bundle_file(Path(temporary), source_name)
            source.write_bytes(data)
            del data
            license_files = []
            if not font["license"] or not font["notices"]:
                raise ValueError("open font license and notices are required")
            for spec in font["notices"]:
                name = spec["path"]
                if not name.startswith("licenses/"):
                    raise ValueError("open font notices must be under licenses/")
                notice = bundle_file(output, name)
                payload = source_payload(
                    cache, lock["downloads"], spec, offline=offline
                )
                if name not in records:
                    notice.parent.mkdir(parents=True, exist_ok=True)
                    with notice.open("xb") as stream:
                        stream.write(payload)
                    records[name] = file_record(notice)
                elif records[name] != {key: spec[key] for key in ("sha256", "bytes")}:
                    raise ValueError("conflicting font notices at the same path")
                license_files.append(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            cached = (
                bundle_file(Path(catalog_cache), identifier + ".p2dfont")
                if catalog_cache
                else None
            )
            start = time.monotonic()
            if cached is not None and cached.is_file():
                shutil.copyfile(cached, target)
            else:

                def progress(done, total):
                    if done % 2000 == 0 or done == total:
                        print(
                            f"{identifier}: {done}/{total} ({time.monotonic() - start:.1f}s)",
                            file=sys.stderr,
                            flush=True,
                        )

                build_font_catalog(source, target, progress=progress)
            catalog = load_font_catalog(target)
            if (
                catalog.font["sha256"] != font["source"]["sha256"]
                or catalog.font["face_index"] != 0
                or catalog.charset != "chinese"
                or catalog.tolerance_divisors != DEFAULT_TOLERANCE_DIVISORS
                or catalog.raster_round_decimals != FONT_CATALOG_RASTER_DECIMALS
                or catalog.outline_policy != FONT_OUTLINE_POLICY
                or catalog.unicode_cjk_version != UNICODE_CJK_VERSION
            ):
                raise ValueError(
                    "cached font catalog does not match the source/build contract"
                )
            with TTFont(source, lazy=True) as sfnt:
                mapped = {
                    cp
                    for cp in (sfnt.getBestCmap() or {})
                    if any(first <= cp <= last for first, last in CHINESE_RANGES)
                }
            actual = {template.codepoint for template in catalog.templates}
            if not actual <= mapped:
                raise ValueError(
                    "font catalog contains codepoints absent from source cmap"
                )
            summary = describe_font_catalog(catalog)
            summary.pop("path")
            # The catalog's original source filename is non-semantic; the source
            # hash, face index and template dataset establish its identity.
            summary.update(
                id=identifier, missing_mapped_codepoints=sorted(mapped - actual)
            )
            coverage.append(summary)
            del catalog
            name = target.relative_to(output).as_posix()
            records[name] = file_record(target)
            entries.append(
                {
                    "id": identifier,
                    "path": name,
                    "family": font["family"],
                    "source_sha256": font["source"]["sha256"],
                    "license": font["license"],
                    "license_files": license_files,
                }
            )
            print(
                f"verified {identifier}: {summary['templates']} templates",
                file=sys.stderr,
                flush=True,
            )
        reports = {
            "SOURCE_LOCK.json": lock_data,
            "COVERAGE.json": _json_bytes(
                {
                    "builder_versions": builder_versions,
                    "fonts": coverage,
                    "coverage_is_recognition_accuracy": False,
                    "variation_sequences_supported": False,
                }
            ),
            "NOTICE.md": (
                "# PDF2DXF optional glyph catalog resources / 可选字形资源\n\n"
                "These derived geometric templates retain each source font's license. "
                "See font-bundle.json and licenses/ for attribution and full terms. "
                "The code's AGPL license does not replace these terms. "
                "Resource identifiers are project-local names; original font names identify sources only.\n\n"
                "本资源中的几何模板保留各源字体许可及版权声明，见 font-bundle.json 与 licenses/。"
                "项目代码的 AGPL 不替代字体许可；原字体名称仅用于标示来源。"
                "覆盖数量不代表任意字体识别率；不支持 IVS 多码点异体序列。\n"
            ).encode(),
        }
        for name, payload in reports.items():
            (output / name).write_bytes(payload)
            records[name] = file_record(output / name)
        manifest = {
            "schema": FONT_BUNDLE_SCHEMA,
            "version": lock["version"],
            "group": group,
            "source_lock_sha256": hashlib.sha256(lock_data).hexdigest(),
            "catalogs": entries,
            "files": records,
        }
        (output / "font-bundle.json").write_bytes(_json_bytes(manifest))
    load_font_bundle(output / "font-bundle.json")
    with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_STORED) as archive:
        for name in sorted(["font-bundle.json", *records]):
            info = zipfile.ZipInfo(
                output.name + "/" + name, date_time=(2026, 1, 1, 0, 0, 0)
            )
            info.external_attr = 0o100644 << 16
            archive.writestr(info, (output / name).read_bytes())
    return {
        "directory": str(output),
        "archive": str(archive_path),
        **file_record(archive_path),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", required=True, type=Path)
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--group", choices=("core", "extended", "all"), default="core")
    parser.add_argument(
        "--catalog-cache",
        type=Path,
        help="reuse verified catalogs from an earlier build",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="require all pinned source downloads in cache",
    )
    args = parser.parse_args(argv)
    try:
        result = build_bundle(
            args.lock,
            args.cache,
            args.output,
            args.group,
            catalog_cache=args.catalog_cache,
            offline=args.offline,
        )
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        FontCatalogError,
        zipfile.BadZipFile,
    ) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
