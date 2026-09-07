import importlib.util
import json
from pathlib import Path
import zipfile

import pytest


def exporter(name="prepare_public_release"):
    path = Path(__file__).resolve().parents[2] / f"tools/{name}.py"
    spec = importlib.util.spec_from_file_location("release_exporter", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def release_fixture(tmp_path):
    module = exporter()
    root = tmp_path / "source"
    for name in (*module.ROOT_FILES, *module.ASSETS, "pdf2dxf_stable/core.py"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture")
    (root / "SOURCE_ORIGIN.json").write_text(
        json.dumps(
            {
                "project_license": "pending_owner_decision",
                "publication_status": "local_review_only",
            }
        )
    )
    return module, root


def test_snapshot_excludes_private_evidence_fonts_and_git_history(tmp_path):
    module, source = release_fixture(tmp_path)
    private = [
        "verification/source-crops/private.png",
        "PROVENANCE.json",
        ".git/config",
        "tmp/secret.py",
        "pdf2dxf_stable/private.pdf",
        "tests/customer.dxf",
        "pdf2dxf_stable/engine/text/assets/private.ttf",
        ".venv/activate",
    ]
    for name in private:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("PRIVATE")
    result = module.export_release(source, tmp_path / "public")
    with zipfile.ZipFile(result["archive"]) as archive:
        assert not any(b"PRIVATE" in archive.read(name) for name in archive.namelist())
        manifest = json.loads(archive.read("public/RELEASE_MANIFEST.json"))
        assert "pdf2dxf_stable/core.py" in manifest["files"]
        assert len(manifest["files"]) == result["files"] - 1
    with pytest.raises(ValueError, match="already exist"):
        module.export_release(source, tmp_path / "public")


def test_snapshot_rejects_symlink_to_private_source(tmp_path):
    module, source = release_fixture(tmp_path)
    outside = tmp_path / "private.py"
    outside.write_text("PRIVATE")
    path = source / "pdf2dxf_stable/link.py"
    try:
        path.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable on this host")
    with pytest.raises(ValueError, match="symlinks"):
        module.export_release(source, tmp_path / "public")


@pytest.mark.parametrize(
    "name, data",
    [
        ("verification/log.txt", b"private"),
        ("../escape.py", b"unsafe"),
        ("tests/input.pdf", b"drawing"),
        ("README.md", b"example: /Users/" + b"alice/drawing.pdf"),
    ],
)
def test_distribution_checker_rejects_private_or_unsafe_members(tmp_path, name, data):
    module = exporter("check_distribution")
    path = tmp_path / "package.whl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(name, data)
    with pytest.raises(ValueError, match="private|unsafe|personal"):
        module.check_distribution(path)


def test_publication_gate_does_not_invent_license_approval(tmp_path):
    module = exporter("check_distribution")
    (tmp_path / "SOURCE_ORIGIN.json").write_text(
        json.dumps(
            {
                "project_license": "pending_owner_decision",
                "source_and_template_redistribution_rights": "pending_confirmation",
            }
        )
    )
    assert module.publication_blockers(tmp_path) == [
        "LICENSE_NOT_SELECTED",
        "PROJECT_LICENSE_UNCONFIRMED",
        "SOURCE_AND_TEMPLATE_RIGHTS_UNCONFIRMED",
    ]


def test_authorized_snapshot_preserves_bilingual_readmes_and_license(tmp_path):
    module, source = release_fixture(tmp_path)
    for name in ("LICENSE", "NOTICE"):
        (source / name).write_text("maintainer supplied license notice")
    (source / "SOURCE_ORIGIN.json").write_text(
        json.dumps(
            {
                "project_license": "AGPL-3.0-only",
                "source_and_template_redistribution_rights": "confirmed_by_owner",
                "publication_status": "authorized_public_release",
            }
        )
    )
    assert exporter("check_distribution").publication_blockers(source) == []
    result = module.export_release(source, tmp_path / "public")
    with zipfile.ZipFile(result["archive"]) as archive:
        manifest = json.loads(archive.read("public/RELEASE_MANIFEST.json"))
        assert manifest["license_status"] == "AGPL-3.0-only"
        assert manifest["publication_status"] == "authorized_public_release"
        assert {"README.md", "README.en.md", "LICENSE", "NOTICE"} <= manifest[
            "files"
        ].keys()


def test_public_distribution_requires_notices_inside_the_artifact(tmp_path):
    module = exporter("check_distribution")
    path = tmp_path / "package.whl"
    with zipfile.ZipFile(path, "w") as archive:
        for name in (
            "cli.py",
            "preflight.py",
            "engine/text/assets/chinese_glyph_templates.json",
            "engine/text/assets/engineering_glyphs.json",
        ):
            archive.writestr("pdf2dxf_stable/" + name, b"fixture")
    with pytest.raises(ValueError, match="missing distribution license notices"):
        module.check_distribution(path, require_license=True)
    with zipfile.ZipFile(path, "a") as archive:
        for name in ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"):
            archive.writestr("package.dist-info/licenses/" + name, b"fixture notice")
    with pytest.raises(ValueError, match="License-Expression"):
        module.check_distribution(path, require_license=True)
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr(
            "package.dist-info/METADATA",
            b"Metadata-Version: 2.4\nLicense-Expression: AGPL-3.0-only\n",
        )
    assert (
        module.check_distribution(path, require_license=True)["content_check"]
        == "passed"
    )
