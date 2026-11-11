"""Tests for the malicious-code-review skill scripts: acquire, stage, inventory, deps.

Network access is not exercised: registry and OSV responses are replaced, so these
tests cover the decisions the scripts make about what to fetch, stage and report.
"""

import base64
import importlib.util
import io
import json
import os
import stat
import sys
import tarfile
import urllib.request
import zipfile
from importlib.machinery import SourceFileLoader
from pathlib import Path, PurePosixPath

import pytest

SCRIPTS = (
    Path(__file__).resolve().parent.parent
    / "dotfiles/.agent/skills/malicious-code-review/scripts"
)


def load(name: str):
    """Import one of the skill's scripts as a module without writing bytecode."""
    loader = SourceFileLoader(f"mcr_{name}", str(SCRIPTS / f"{name}.py"))
    spec = importlib.util.spec_from_loader(f"mcr_{name}", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    dont_write_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = dont_write_bytecode
    return module


@pytest.fixture(scope="module")
def acquire():
    """The acquire script."""
    return load("acquire")


@pytest.fixture(scope="module")
def stage():
    """The stage script."""
    return load("stage")


@pytest.fixture(scope="module")
def inventory():
    """The inventory script."""
    return load("inventory")


@pytest.fixture(scope="module")
def deps():
    """The deps script."""
    return load("deps")


def add_tar_member(
    tar: tarfile.TarFile, name: str, kind: bytes = tarfile.REGTYPE, data=b"", link=""
):
    """Add one member of any type to an open tar archive."""
    info = tarfile.TarInfo(name)
    info.type = kind
    info.size = len(data) if kind == tarfile.REGTYPE else 0
    info.linkname = link
    info.mode = 0o755
    tar.addfile(info, io.BytesIO(data) if kind == tarfile.REGTYPE else None)


@pytest.fixture
def hostile_tar(tmp_path: Path) -> Path:
    """A tar archive mixing ordinary files with escape attempts."""
    path = tmp_path / "pkg.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        add_tar_member(tar, "pkg/setup.py", data=b"print('hi')\n")
        add_tar_member(tar, "pkg/setup.py", data=b"second copy\n")
        add_tar_member(tar, "../escape.txt", data=b"x")
        add_tar_member(tar, "/etc/evil", data=b"x")
        add_tar_member(tar, "pkg/link", kind=tarfile.SYMTYPE, link="/home")
        add_tar_member(tar, "pkg/hard", kind=tarfile.LNKTYPE, link="pkg/setup.py")
        add_tar_member(tar, "pkg/dev", kind=tarfile.CHRTYPE)
        add_tar_member(tar, "pkg\\win.txt", data=b"x")
    return path


def test_stage_tar_keeps_regular_files_and_records_every_refusal(
    stage, hostile_tar, tmp_path
):
    # Arrange
    dest = tmp_path / "target"

    # Act
    status = stage.main([str(hostile_tar), str(dest)])

    # Assert
    assert status == 0
    staged = dest / "pkg/setup.py"
    assert staged.read_bytes() == b"print('hi')\n"
    assert stat.S_IMODE(staged.stat().st_mode) == 0o644
    assert sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*")) == [
        "pkg",
        "pkg/setup.py",
    ]
    assert not (tmp_path / "escape.txt").exists()


def test_stage_tar_summary_names_each_skipped_member(
    stage, hostile_tar, tmp_path, capsys
):
    # Act
    stage.main([str(hostile_tar), str(tmp_path / "target")])

    # Assert
    reasons = {
        e["path"]: e["reason"] for e in json.loads(capsys.readouterr().out)["skipped"]
    }
    assert reasons == {
        "pkg/setup.py": "duplicate path",
        "../escape.txt": "parent-directory component",
        "/etc/evil": "absolute path",
        "pkg/link": "symlink not staged",
        "pkg/hard": "hardlink not staged",
        "pkg/dev": "device or fifo not staged",
        "pkg\\win.txt": "backslash in name",
    }


def test_stage_zip_skips_symlinks_and_traversal(stage, tmp_path):
    # Arrange
    archive = tmp_path / "pkg.whl"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("pkg/__init__.py", "")
        link = zipfile.ZipInfo("pkg/link")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        bundle.writestr(link, "/etc/passwd")
        bundle.writestr("../../escape.py", "")

    # Act
    status = stage.main([str(archive), str(tmp_path / "target")])

    # Assert
    assert status == 0
    assert [p.name for p in (tmp_path / "target").rglob("*") if p.is_file()] == [
        "__init__.py"
    ]
    assert not (tmp_path / "escape.py").exists()


def test_stage_abandons_and_removes_dest_past_the_size_limit(stage, tmp_path):
    # Arrange
    archive = tmp_path / "big.tar"
    with tarfile.open(archive, "w") as tar:
        add_tar_member(tar, "big.bin", data=b"0" * 2048)
    dest = tmp_path / "target"

    # Act
    status = stage.main([str(archive), str(dest), "--max-bytes", "1024"])

    # Assert
    assert status == 1
    assert not dest.exists()


def test_stage_refuses_an_existing_dest(stage, hostile_tar, tmp_path):
    # Arrange
    dest = tmp_path / "target"
    dest.mkdir()

    # Act / Assert
    assert stage.main([str(hostile_tar), str(dest)]) == 2


def test_stage_dir_skips_links_and_git_objects_but_keeps_hooks(stage, tmp_path, capsys):
    # Arrange
    source = tmp_path / "repo"
    (source / ".git/objects/ab").mkdir(parents=True)
    (source / ".git/objects/ab/cdef").write_bytes(b"blob")
    (source / ".git/hooks").mkdir()
    (source / ".git/hooks/post-checkout").write_text("#!/bin/sh\n")
    (source / ".git/hooks/post-checkout").chmod(0o755)
    (source / "src").mkdir()
    (source / "src/app.py").write_text("")
    (source / "secret-link").symlink_to(Path.home())
    (source / "dir-link").symlink_to(tmp_path)
    dest = tmp_path / "target"

    # Act
    status = stage.main(["--dir", str(source), str(dest)])

    # Assert
    assert status == 0
    staged = sorted(
        p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()
    )
    assert staged == [".git/hooks/post-checkout", "src/app.py"]
    assert not os.access(dest / ".git/hooks/post-checkout", os.X_OK)
    reasons = {
        e["path"]: e["reason"] for e in json.loads(capsys.readouterr().out)["skipped"]
    }
    assert reasons == {
        ".git/objects": "git object store",
        "dir-link": "symlink not staged",
        "secret-link": "symlink not staged",
    }


@pytest.mark.parametrize(
    ("name", "content", "expected"),
    [
        (
            "evil.pth",
            b"import os; os.system('x')\n./lib\n",
            "1 executable .pth line(s)",
        ),
        (
            "package.json",
            json.dumps(
                {"scripts": {"postinstall": "node x.js", "test": "jest"}}
            ).encode(),
            "lifecycle postinstall: node x.js",
        ),
        (
            "pyproject.toml",
            b'[build-system]\nbuild-backend = "backend"\nbackend-path = ["_build"]\n',
            "in-tree backend-path ['_build']",
        ),
    ],
)
def test_inventory_reports_execution_details(inventory, name, content, expected):
    # Act
    surfaces, flags = inventory.content_facts(
        PurePosixPath(name), head=content, complete=True
    )

    # Assert
    assert expected in surfaces
    assert flags == []


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (b"\x7fELF\x02\x01", "ELF binary"),
        (b"PK\x03\x04rest", "zip archive"),
        (b"text\x00more", "binary data"),
        (b"x = '" + b"QUJD" * 60 + b"'\n", "encoded-looking literal of 240 characters"),
        (b"a" * 2500, "line of 2500 characters (minified or embedded data)"),
    ],
)
def test_inventory_flags_opaque_content(inventory, content, expected):
    # Act
    _, flags = inventory.content_facts(
        PurePosixPath("file"), head=content, complete=True
    )

    # Assert
    assert expected in flags


def test_inventory_diff_strips_version_directories_and_lists_surfaces_first(
    inventory, tmp_path, capsys
):
    # Arrange
    review = tmp_path / "review"
    for tree, version, setup in (("baseline", "1.0", "old"), ("target", "1.1", "new")):
        root = review / tree / f"pkg-{version}"
        root.mkdir(parents=True)
        (root / "setup.py").write_text(setup)
        (root / "README.md").write_text("same")
    (review / "target/pkg-1.1/zz.pth").write_text("import os\n")

    # Act
    status = inventory.main([str(review)])

    # Assert
    assert status == 0
    out = capsys.readouterr().out
    assert "2 added" not in out
    assert "1 added, 0 removed, 1 changed." in out
    changes = out.split("## Changes from baseline")[1]
    assert changes.index("added `zz.pth`") < changes.index("### Removed")
    assert "changed `setup.py` — Python build script" in changes


UV_LOCK_OLD = """
version = 1

[[package]]
name = "alpha"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "beta"
version = "2.0.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "gone"
version = "0.1.0"
source = { registry = "https://pypi.org/simple" }
"""

UV_LOCK_NEW = """
version = 1

[[package]]
name = "alpha"
version = "1.1.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "beta"
version = "2.0.0"
source = { registry = "https://mirror.example/simple" }

[[package]]
name = "fresh"
version = "0.0.1"
source = { git = "https://github.com/example/fresh?rev=abc" }

[[package]]
name = "newpub"
version = "3.0.0"
source = { registry = "https://pypi.org/simple" }
"""


@pytest.fixture
def uv_locks(tmp_path: Path) -> tuple[Path, Path]:
    """An old and a new uv.lock with every kind of change."""
    old_dir, new_dir = tmp_path / "old", tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    (old_dir / "uv.lock").write_text(UV_LOCK_OLD)
    (new_dir / "uv.lock").write_text(UV_LOCK_NEW)
    return old_dir / "uv.lock", new_dir / "uv.lock"


def test_deps_diff_classifies_uv_lock_changes(deps, uv_locks):
    # Act
    out = "\n".join(deps.diff(*uv_locks, with_osv=False))

    # Assert
    sections = dict(part.split("\n", 1) for part in out.split("## ")[1:])
    assert (
        "fresh 0.0.1 (git https://github.com/example/fresh?rev=abc)"
        in sections["Added"]
    )
    assert "newpub 3.0.0" in sections["Added"]
    assert "alpha 1.0.0 → 1.1.0" in sections["Re-versioned"]
    assert (
        "beta 2.0.0: registry https://pypi.org/simple → registry https://mirror.example/simple"
        in sections["Same version, changed source"]
    )
    assert "gone 0.1.0" in sections["Removed"]
    nonpublic = sections["New or changed entries from a non-public source"]
    assert "fresh" in nonpublic
    assert "beta" in nonpublic
    assert "alpha" not in nonpublic


def test_deps_osv_reports_mal_records_apart_and_never_sends_private_packages(
    deps, uv_locks, monkeypatch
):
    # Arrange
    sent = []

    def fake_query(ecosystem, packages):
        sent.extend(packages)
        return [
            ["MAL-2026-1", "GHSA-x"] if name == "newpub" else [] for name, _ in packages
        ]

    monkeypatch.setattr(deps, "osv_query", fake_query)

    # Act
    out = "\n".join(deps.diff(*uv_locks, with_osv=True))

    # Assert
    assert sorted(sent) == [("alpha", "1.1.0"), ("newpub", "3.0.0")]
    osv = out.split("## OSV")[1]
    assert "**newpub 3.0.0**: MAL-2026-1" in osv
    assert "newpub 3.0.0: GHSA-x" in osv
    assert "fresh 0.0.1" in osv.split("### Not queried")[1]
    assert "beta 2.0.0" in osv.split("### Not queried")[1]


def test_deps_reads_package_lock_and_marks_registry_sources(deps, tmp_path):
    # Arrange
    lock = tmp_path / "package-lock.json"
    lock.write_text(
        json.dumps(
            {
                "lockfileVersion": 3,
                "packages": {
                    "": {"name": "app"},
                    "node_modules/@scope/lib": {
                        "version": "1.0.0",
                        "resolved": "https://registry.npmjs.org/@scope/lib/-/lib-1.0.0.tgz",
                    },
                    "node_modules/local": {"link": True},
                    "node_modules/gitdep": {
                        "version": "0.1.0",
                        "resolved": "git+ssh://x",
                    },
                },
            }
        )
    )

    # Act
    ecosystem, packages = deps.read_lock(lock)

    # Assert
    assert ecosystem == "npm"
    assert {(p.name, p.public) for p in packages} == {
        ("@scope/lib", True),
        ("gitdep", False),
    }


def test_deps_rejects_lockfile_version_1(deps, tmp_path):
    # Arrange
    lock = tmp_path / "package-lock.json"
    lock.write_text(json.dumps({"lockfileVersion": 1, "dependencies": {}}))

    # Act / Assert
    with pytest.raises(deps.DepsError, match="lockfileVersion 1"):
        deps.read_lock(lock)


def pypi_file(filename: str, packagetype: str) -> dict:
    """A PyPI JSON API file record."""
    return {"filename": filename, "packagetype": packagetype}


def test_acquire_selects_sdist_and_pure_wheel_by_default(acquire):
    # Arrange
    files = [
        pypi_file("pkg-1.0.tar.gz", "sdist"),
        pypi_file("pkg-1.0-py3-none-any.whl", "bdist_wheel"),
        pypi_file("pkg-1.0-cp313-cp313-manylinux_2_28_x86_64.whl", "bdist_wheel"),
    ]

    # Act
    selected = acquire.select_pypi_files(files, wanted=())

    # Assert
    assert [f["filename"] for f in selected] == [
        "pkg-1.0.tar.gz",
        "pkg-1.0-py3-none-any.whl",
    ]


def test_acquire_asks_for_a_file_when_only_platform_wheels_exist(acquire):
    # Arrange
    files = [pypi_file("pkg-1.0-cp313-cp313-win_amd64.whl", "bdist_wheel")]

    # Act / Assert
    with pytest.raises(acquire.AcquireError, match="choose with --file"):
        acquire.select_pypi_files(files, wanted=())


def test_acquire_previous_release_ignores_later_uploads(acquire):
    # Arrange
    releases = {
        "1.0": [{"upload_time_iso_8601": "2024-01-01T00:00:00Z"}],
        "1.1": [{"upload_time_iso_8601": "2024-06-01T00:00:00Z"}],
        "0.9-backport": [{"upload_time_iso_8601": "2024-09-01T00:00:00Z"}],
        "2.0": [{"upload_time_iso_8601": "2025-01-01T00:00:00Z"}],
    }

    # Act / Assert
    assert acquire.previous_release(releases, version="2.0") == (
        "0.9-backport",
        "2024-09-01T00:00:00Z",
    )


def test_acquire_npm_integrity_comparison(acquire):
    # Arrange
    digest = bytes(range(64))
    integrity = "sha512-" + base64.b64encode(digest).decode()

    # Act / Assert
    assert acquire.npm_integrity_matches(integrity, sha512_hex=digest.hex()) is True
    assert acquire.npm_integrity_matches(integrity, sha512_hex="00" * 64) is False
    assert acquire.npm_integrity_matches("sha1-abc", sha512_hex=digest.hex()) is None


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("../../.bashrc", "bashrc"),
        ("pkg 1.0.tgz", "pkg_1.0.tgz"),
        ("a/b/c.whl", "c.whl"),
    ],
)
def test_acquire_safe_filename(acquire, name, expected):
    assert acquire.safe_filename(name) == expected


def test_acquire_refuses_non_https(acquire):
    with pytest.raises(acquire.AcquireError, match="non-HTTPS"):
        acquire.open_url("http://example.invalid/x")


def test_acquire_refuses_redirect_off_https(acquire):
    # Arrange
    handler = acquire.HttpsOnlyRedirect()
    request = urllib.request.Request("https://example.invalid/a")

    # Act / Assert
    with pytest.raises(acquire.AcquireError, match="non-HTTPS"):
        handler.redirect_request(
            request, None, 302, "Found", {}, "http://example.invalid/b"
        )
