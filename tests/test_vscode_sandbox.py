"""Tests for dotfiles/bin/vscode-sandbox: CLI, roots, builders, preflight, seccomp,
Wayland, lock and supervision."""

import ast
import errno
import importlib.util
import json
import os
import pwd
import re
import select
import shlex
import shutil
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import types
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import ClassVar

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "dotfiles" / "bin" / "vscode-sandbox"


def load_script():
    """Import the executable without creating deployed bytecode files."""
    loader = SourceFileLoader("vscode_sandbox", str(SCRIPT))
    spec = importlib.util.spec_from_loader("vscode_sandbox", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    dont_write_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = dont_write_bytecode
    return module


sandbox = load_script()


# CLI parsing


def test_parse_args_collects_paths_and_repeated_ports():
    args = sandbox.parse_args(["--port", "8888", "a", "--port", "5432", "b"])

    assert args.paths == ["a", "b"]
    assert args.port == [8888, 5432]
    assert args.only_args is False


def test_parse_args_defaults():
    args = sandbox.parse_args([])

    assert args.paths == []
    assert args.port == []
    assert args.only_args is False


def test_parse_args_only_args_flag():
    assert sandbox.parse_args(["--only-args"]).only_args is True


def test_parse_args_rejects_unknown_option(capsys):
    with pytest.raises(SystemExit) as exc_info:
        sandbox.parse_args(["--unknown"])

    assert exc_info.value.code == 2
    assert "unrecognized arguments: --unknown" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["0", "65536", "-1", "http"])
def test_parse_args_rejects_invalid_port(capsys, value):
    with pytest.raises(SystemExit) as exc_info:
        sandbox.parse_args([f"--port={value}"])

    assert exc_info.value.code == 2
    assert "--port" in capsys.readouterr().err


def test_help_describes_file_argument_root(capsys):
    with pytest.raises(SystemExit) as exc_info:
        sandbox.parse_args(["--help"])

    assert exc_info.value.code == 0
    help_text = " ".join(capsys.readouterr().out.split())
    assert "each becomes a writable root" not in help_text
    assert "nearest .git ancestor, else its parent" in help_text


@pytest.mark.parametrize("value", ["1", "65535"])
def test_parse_args_accepts_port_bounds(value):
    assert sandbox.parse_args(["--port", value]).port == [int(value)]


# Root and port resolution


@pytest.fixture
def tmp(tmp_path, monkeypatch):
    """
    Provide a canonical temp tree with empty user constants.

    System trees enclosing the temp tree (e.g. /tmp) are dropped so the other rules can
    be tested; test_rejects_root_under_system_tree uses the real constant.
    """
    tmp = tmp_path.resolve()
    monkeypatch.setattr(sandbox, "ROOTS", ())
    monkeypatch.setattr(sandbox, "PORTS", ())
    monkeypatch.setattr(
        sandbox,
        "SYSTEM_TREES",
        tuple(tree for tree in SYSTEM_TREES if not tmp.is_relative_to(tree)),
    )
    (tmp / "home").mkdir()
    return tmp


SYSTEM_TREES = sandbox.SYSTEM_TREES


def resolve(argv, *, tmp, cwd=None, script=None):
    """Resolve a launch with the temp home, and a script and state dir outside it."""
    return sandbox.resolve_config(
        sandbox.parse_args(argv),
        home=tmp / "home",
        cwd=cwd or tmp / "home",
        script=script or tmp / "scripts" / "vscode-sandbox",
        state_dir=tmp / "runtime" / "vscode-sandbox",
    )


def rw(path):
    return sandbox.Root(path=path, mode="rw")


def mkdir(path):
    path.mkdir(parents=True)
    return path


@pytest.mark.parametrize(
    ("relative", "message"),
    [
        ("home", "is $HOME or one of its ancestors"),
        (".", "is $HOME or one of its ancestors"),
        ("home/.config/x", "is under a hidden entry of $HOME"),
        ("home/.config", "is under a hidden entry of $HOME"),
        ("home/bin/tools", "overlaps protected path"),
    ],
)
def test_rejects_rw_root(tmp, relative, message):
    mkdir(tmp / "home" / "bin")
    path = tmp / relative
    path.mkdir(parents=True, exist_ok=True)

    with pytest.raises(sandbox.SandboxError, match=re.escape(message)):
        resolve([str(path)], tmp=tmp)


def test_rejects_filesystem_root(tmp):
    with pytest.raises(
        sandbox.SandboxError, match=re.escape("is $HOME or one of its ancestors")
    ):
        resolve(["/"], tmp=tmp)


def test_rejects_root_under_system_tree(tmp, monkeypatch):
    monkeypatch.setattr(sandbox, "SYSTEM_TREES", SYSTEM_TREES)

    with (
        tempfile.TemporaryDirectory(dir="/tmp") as path,
        pytest.raises(
            sandbox.SandboxError, match=f"{path} overlaps protected path /tmp$"
        ),
    ):
        resolve([path], tmp=tmp)


def test_rejects_ancestor_of_symlinked_home_bin(tmp):
    mkdir(tmp / "dotfiles" / "bin")
    (tmp / "home" / "bin").symlink_to(tmp / "dotfiles" / "bin")

    with pytest.raises(
        sandbox.SandboxError, match=f"overlaps protected path {tmp}/dotfiles/bin$"
    ):
        resolve([str(tmp / "dotfiles")], tmp=tmp)


@pytest.mark.parametrize(
    "relative",
    [
        ".config/Code",
        ".vscode",
        ".vscode-shared",
        ".local/share/vscode-sandbox",
        ".local/share/vscode-sandbox/cache",
        ".local/share/vscode-sandbox/jupyter-runtime",
    ],
)
def test_rejects_root_holding_symlinked_rw_bind_source(tmp, relative):
    target = mkdir(tmp / "home" / "project" / "bind-source")
    link = tmp / "home" / relative
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)

    with pytest.raises(
        sandbox.SandboxError, match=f"overlaps protected path {target}$"
    ):
        resolve([str(tmp / "home" / "project")], tmp=tmp)


@pytest.mark.parametrize("relative", ["shared", "shared/sub"])
def test_rejects_root_at_or_inside_symlinked_vscode_shared_target(tmp, relative):
    target = mkdir(tmp / "elsewhere" / "shared")
    mkdir(target / "sub")
    (tmp / "home" / ".vscode-shared").symlink_to(target)

    with pytest.raises(
        sandbox.SandboxError, match=f"overlaps protected path {target}$"
    ):
        resolve([str(tmp / "elsewhere" / relative)], tmp=tmp)


def test_rejects_root_holding_symlinked_user_fonts_dir(tmp):
    target = mkdir(tmp / "home" / "project" / "fonts")
    (tmp / "home" / ".fonts").symlink_to(target)

    with pytest.raises(
        sandbox.SandboxError, match=f"overlaps protected path {target}$"
    ):
        resolve([str(tmp / "home" / "project")], tmp=tmp)


def test_rejects_root_covering_script(tmp):
    script = mkdir(tmp / "repo" / "bin") / "vscode-sandbox"
    script.touch()

    with pytest.raises(sandbox.SandboxError, match=f"protected path {script}$"):
        resolve([str(tmp / "repo")], tmp=tmp, script=script)


@pytest.mark.parametrize("relative", ["reference", "reference/sub"])
def test_rejects_rw_root_equal_to_or_inside_ro_constant_root(
    tmp, monkeypatch, relative
):
    mkdir(tmp / "reference" / "sub")
    monkeypatch.setattr(sandbox, "ROOTS", ((str(tmp / "reference"), "ro"),))

    with pytest.raises(
        sandbox.SandboxError, match=f"overlaps protected path {tmp}/reference$"
    ):
        resolve([str(tmp / relative)], tmp=tmp)


def test_rejects_rw_constant_root(tmp, monkeypatch):
    mkdir(tmp / "home" / ".config" / "x")
    monkeypatch.setattr(sandbox, "ROOTS", ((".config/x", "rw"),))

    with pytest.raises(
        sandbox.SandboxError, match=re.escape("under a hidden entry of $HOME")
    ):
        resolve([], tmp=tmp)


@pytest.fixture
def symlinked_hidden_entries(tmp):
    """Point ~/.ssh and ~/.config/gh at plain home folders, as a stow layout would."""
    (mkdir(tmp / "home" / "ssh-keys") / "config").touch()
    (tmp / "home" / ".ssh").symlink_to(tmp / "home" / "ssh-keys")
    mkdir(tmp / "home" / ".config")
    (tmp / "home" / ".config" / "gh").symlink_to(mkdir(tmp / "home" / "gh-hosts"))


@pytest.mark.parametrize("argument", [".ssh", ".ssh/config", ".config/gh"])
@pytest.mark.usefixtures("symlinked_hidden_entries")
def test_rejects_rw_root_through_symlinked_hidden_home_entry(tmp, argument):
    with pytest.raises(
        sandbox.SandboxError,
        match=f"writable root {tmp}/home/{argument} is under a hidden entry of",
    ):
        resolve([argument], tmp=tmp)


@pytest.mark.usefixtures("symlinked_hidden_entries")
def test_rejects_rw_constant_root_through_symlinked_hidden_home_entry(tmp, monkeypatch):
    monkeypatch.setattr(sandbox, "ROOTS", ((".ssh", "rw"),))

    with pytest.raises(
        sandbox.SandboxError,
        match=f"writable root {tmp}/home/.ssh is under a hidden entry of",
    ):
        resolve([], tmp=tmp)


def test_accepts_rw_root_given_as_home_through_parent_of_symlink(tmp):
    project = mkdir(tmp / "elsewhere" / "project")
    (tmp / "home" / "link").symlink_to(project)

    config = resolve(["link/.."], tmp=tmp)

    assert config.roots == (rw(tmp / "elsewhere"),)


def test_rejects_unknown_constant_root_mode(tmp, monkeypatch):
    monkeypatch.setattr(sandbox, "ROOTS", (("/", "RO"),))

    with pytest.raises(
        sandbox.SandboxError,
        match=re.escape("ROOTS entry '/' has mode 'RO', not ro or rw"),
    ):
        resolve([], tmp=tmp)


@pytest.mark.parametrize("relative", ["gems", "gems/gems/rake"])
def test_rejects_root_at_or_inside_gem_home(tmp, relative):
    path = mkdir(tmp / "home" / relative)

    with pytest.raises(
        sandbox.SandboxError, match=f"overlaps protected path {tmp}/home/gems$"
    ):
        resolve([str(path)], tmp=tmp)


def test_rejects_root_holding_symlinked_gem_home(tmp):
    target = mkdir(tmp / "home" / "project" / "gems")
    (tmp / "home" / "gems").symlink_to(target)

    with pytest.raises(
        sandbox.SandboxError, match=f"overlaps protected path {target}$"
    ):
        resolve([str(tmp / "home" / "project")], tmp=tmp)


@pytest.mark.parametrize("limit", ["/", "/run", "/data"])
def test_rejects_ro_root_at_limit(tmp, limit):
    with pytest.raises(
        sandbox.SandboxError, match=f"read-only root {limit} is or covers {limit}$"
    ):
        sandbox.check_ro(
            Path(limit), lexical=Path(limit), home=tmp / "home", protected=()
        )


@pytest.mark.parametrize(
    ("relative", "covered"),
    [
        (".", "home"),
        ("home/.config", "home/.config/"),
        ("home/.local", "home/.local/"),
        ("scripts", "scripts/vscode-sandbox"),
    ],
)
def test_rejects_ro_constant_root_covering_home_or_protected_path(
    tmp, monkeypatch, relative, covered
):
    root = tmp / relative
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(sandbox, "ROOTS", ((str(root), "ro"),))

    with pytest.raises(
        sandbox.SandboxError,
        match=f"read-only root {root} is or covers {re.escape(str(tmp / covered))}",
    ):
        resolve([], tmp=tmp)


def test_rejects_ro_constant_root_at_home(tmp, monkeypatch):
    monkeypatch.setattr(sandbox, "ROOTS", (("", "ro"),))

    with pytest.raises(
        sandbox.SandboxError, match=f"read-only root {tmp}/home is or covers"
    ):
        resolve([], tmp=tmp)


@pytest.mark.parametrize("relative", [".ssh", ".ssh/keys", ".config/x"])
def test_rejects_ro_constant_root_inside_hidden_home_entry(tmp, monkeypatch, relative):
    mkdir(tmp / "home" / relative)
    monkeypatch.setattr(sandbox, "ROOTS", ((relative, "ro"),))

    with pytest.raises(
        sandbox.SandboxError,
        match=f"read-only root {tmp}/home/{relative} is under a hidden entry of",
    ):
        resolve([], tmp=tmp)


def test_rejects_ro_constant_root_resolving_into_hidden_home_entry(tmp, monkeypatch):
    target = mkdir(tmp / "home" / ".config" / "x")
    (tmp / "home" / "link").symlink_to(target)
    monkeypatch.setattr(sandbox, "ROOTS", (("link", "ro"),))

    with pytest.raises(
        sandbox.SandboxError,
        match=f"read-only root {target} is under a hidden entry of",
    ):
        resolve([], tmp=tmp)


def test_rejects_ro_constant_root_through_symlinked_hidden_home_entry(tmp, monkeypatch):
    mkdir(tmp / "elsewhere" / "ssh" / "keys")
    (tmp / "home" / ".ssh").symlink_to(tmp / "elsewhere" / "ssh")
    monkeypatch.setattr(sandbox, "ROOTS", ((".ssh/keys", "ro"),))

    with pytest.raises(
        sandbox.SandboxError,
        match=f"read-only root {tmp}/home/.ssh/keys is under a hidden entry of",
    ):
        resolve([], tmp=tmp)


@pytest.mark.parametrize(
    ("path", "lexical"),
    [
        ("/run/user/1000", "/run/user/1000"),
        ("/srv/elsewhere", "/run/user/1000/bus-link"),
    ],
)
def test_rejects_ro_root_inside_run(tmp, path, lexical):
    with pytest.raises(
        sandbox.SandboxError, match=f"read-only root {lexical} is inside /run$"
    ):
        sandbox.check_ro(
            Path(path), lexical=Path(lexical), home=tmp / "home", protected=()
        )


@pytest.mark.parametrize(
    "relative", ["projects/reference", "projects/.cache", "../shared"]
)
def test_accepts_ro_constant_root_in_plain_home_folder_or_outside_home(
    tmp, monkeypatch, relative
):
    root = mkdir(tmp / "home" / relative).resolve()
    monkeypatch.setattr(sandbox, "ROOTS", ((relative, "ro"),))

    config = resolve([], tmp=tmp)

    assert config.roots == (sandbox.Root(path=root, mode="ro"),)


def test_accepts_ro_root_given_as_home_through_parent_of_symlink(tmp):
    sandbox.check_ro(
        Path("/srv/elsewhere"), lexical=tmp / "home", home=tmp / "home", protected=()
    )


def test_accepts_ro_root_under_data(tmp):
    sandbox.check_ro(
        Path("/data/reference"),
        lexical=Path("/data/reference"),
        home=tmp / "home",
        protected=(),
    )


def test_accepts_nested_ro_constant_roots(tmp, monkeypatch):
    sub = mkdir(tmp / "reference" / "sub")
    monkeypatch.setattr(
        sandbox, "ROOTS", ((str(tmp / "reference"), "ro"), (str(sub), "ro"))
    )

    config = resolve([], tmp=tmp)

    assert config.roots == (
        sandbox.Root(path=tmp / "reference", mode="ro"),
        sandbox.Root(path=sub, mode="ro"),
    )


def test_rejects_missing_path(tmp):
    with pytest.raises(sandbox.SandboxError, match=r"cannot resolve .*/missing"):
        resolve([str(tmp / "missing")], tmp=tmp)


def test_git_file_pointing_elsewhere_resolves_to_its_directory(tmp):
    elsewhere = mkdir(tmp / "elsewhere")
    project = mkdir(tmp / "project" / "sub")
    (tmp / "project" / ".git").write_text(f"gitdir: {elsewhere}\n")

    config = resolve([], tmp=tmp, cwd=project)

    assert config.roots == (rw(tmp / "project"),)
    assert not any(root.path.is_relative_to(elsewhere) for root in config.roots)
    assert config.paths == (tmp / "project",)


def test_git_config_worktree_does_not_redirect_root(tmp):
    project = mkdir(tmp / "project")
    (mkdir(project / ".git") / "config").write_text("[core]\n\tworktree = /\n")

    config = resolve([], tmp=tmp, cwd=project)

    assert config.roots == (rw(project),)


def test_no_git_ancestor_resolves_to_no_root(tmp):
    assert resolve([], tmp=tmp, cwd=mkdir(tmp / "plain")).roots == ()


def test_git_walk_root_is_opened(tmp):
    mkdir(tmp / "project" / ".git")

    config = resolve([], tmp=tmp, cwd=mkdir(tmp / "project" / "sub"))

    assert sandbox.electron_args(config.paths)[-1] == str(tmp / "project")


def test_file_argument_roots_its_parent(tmp):
    file = mkdir(tmp / "project") / "notebook.ipynb"
    file.touch()

    config = resolve(["project/notebook.ipynb"], tmp=tmp, cwd=tmp)

    assert config.roots == (rw(tmp / "project"),)
    assert config.paths == (file,)


def test_file_argument_roots_its_nearest_git_ancestor(tmp):
    mkdir(tmp / "outer" / ".git")
    mkdir(tmp / "outer" / "repo" / ".git")
    file = mkdir(tmp / "outer" / "repo" / "notebooks") / "notebook.ipynb"
    file.touch()

    config = resolve([str(file)], tmp=tmp)

    assert config.roots == (rw(tmp / "outer" / "repo"),)
    assert config.paths == (file,)


def test_path_arguments_replace_git_walk(tmp):
    mkdir(tmp / "project" / ".git")
    other = mkdir(tmp / "other")

    config = resolve([str(other)], tmp=tmp, cwd=tmp / "project")

    assert config.roots == (rw(other),)


def test_constant_roots_resolve_under_home_with_their_modes(tmp, monkeypatch):
    shared = mkdir(tmp / "home" / "shared")
    reference = mkdir(tmp / "reference")
    monkeypatch.setattr(
        sandbox, "ROOTS", (("shared", "rw"), (str(tmp / "reference"), "ro"))
    )

    config = resolve([], tmp=tmp)

    assert config.roots == (
        rw(shared),
        sandbox.Root(path=reference, mode="ro"),
    )


def test_only_args_ignores_constant_roots(tmp, monkeypatch):
    project = mkdir(tmp / "project")
    monkeypatch.setattr(sandbox, "ROOTS", ((str(tmp / "missing"), "ro"),))

    config = resolve(["--only-args", str(project)], tmp=tmp)

    assert config.roots == (rw(project),)


def test_missing_constant_root_is_an_error(tmp, monkeypatch):
    monkeypatch.setattr(sandbox, "ROOTS", ((str(tmp / "missing"), "ro"),))

    with pytest.raises(sandbox.SandboxError, match="cannot resolve"):
        resolve([], tmp=tmp)


def test_roots_are_deduplicated_and_parents_first(tmp, monkeypatch):
    child = mkdir(tmp / "a" / "b")
    (child / "file.py").touch()
    mkdir(tmp / "a-sibling")
    monkeypatch.setattr(sandbox, "ROOTS", ((str(tmp / "a" / "b"), "rw"),))

    config = resolve(
        [str(child / "file.py"), str(tmp / "a-sibling"), str(child), str(tmp / "a")],
        tmp=tmp,
    )

    assert config.roots == (rw(tmp / "a"), rw(child), rw(tmp / "a-sibling"))


def test_ports_are_the_sorted_union_of_constant_and_arguments(tmp, monkeypatch):
    monkeypatch.setattr(sandbox, "PORTS", (8888, 5432))

    config = resolve(["--port", "5432", "--port", "3000"], tmp=tmp)

    assert config.ports == (3000, 5432, 8888)


def test_constant_port_outside_range_is_an_error(tmp, monkeypatch):
    monkeypatch.setattr(sandbox, "PORTS", (0,))

    with pytest.raises(sandbox.SandboxError, match="outside 1-65535: 0"):
        resolve([], tmp=tmp)


def test_main_reports_rejected_root(tmp, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp / "home"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp / "runtime"))
    monkeypatch.chdir(tmp)

    assert sandbox.main([str(tmp / "missing")]) == 1
    assert capsys.readouterr().err.startswith("vscode-sandbox: error: cannot resolve")


def test_main_runs_electron_detached_for_valid_launch(tmp, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp / "home"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp / "runtime"))
    monkeypatch.chdir(tmp)
    calls = []

    def run_sandbox(config, command, *, env, detach):
        calls.append((config, command, env, detach))
        return 7

    monkeypatch.setattr(sandbox, "run_sandbox", run_sandbox)

    assert sandbox.main([str(mkdir(tmp / "project"))]) == 7
    [(config, command, env, detach)] = calls
    assert config.paths == (tmp / "project",)
    assert command == sandbox.electron_args(config.paths)
    assert env == sandbox.host_env(os.environ)
    assert detach is True


@pytest.mark.parametrize(
    ("runtime", "root"),
    [
        ("project/runtime", "project"),
        ("project/runtime", "project/runtime/vscode-sandbox/sub"),
        ("runtime-link", "project"),
    ],
)
def test_main_rejects_root_overlapping_state_dir(
    tmp, monkeypatch, capsys, runtime, root
):
    state = mkdir(tmp / "project" / "runtime" / "vscode-sandbox" / "sub").parent
    (tmp / "runtime-link").symlink_to(tmp / "project" / "runtime")
    monkeypatch.setenv("HOME", str(tmp / "home"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp / runtime))
    monkeypatch.chdir(tmp)
    calls = []
    monkeypatch.setattr(sandbox, "run_sandbox", lambda *args, **kwargs: calls.append(1))

    assert sandbox.main([str(tmp / root)]) == 1
    assert f"overlaps protected path {state}\n" in capsys.readouterr().err
    assert calls == []


def test_main_rejects_relative_home(tmp, monkeypatch, capsys):
    monkeypatch.setenv("HOME", "home")
    monkeypatch.chdir(tmp)

    assert sandbox.main([]) == 1
    assert "HOME must be set to an absolute path" in capsys.readouterr().err


# Argv and environment builders


BIND_OPTIONS = ("--bind", "--ro-bind", "--ro-bind-try", "--dev-bind")


def options(args, option):
    """Return the two operands of every occurrence of a two-operand option."""
    return [
        (args[index + 1], args[index + 2])
        for index, arg in enumerate(args)
        if arg == option
    ]


@pytest.fixture
def built(tmp, monkeypatch):
    """Build bwrap arguments for a temp home with one rw and one ro root."""
    home = tmp / "home"
    dri = mkdir(tmp / "dri")
    for name in ("card0", "renderD128", "renderD129", "by-path"):
        (dri / name).touch()
    monkeypatch.setattr(sandbox, "DRI_DIR", str(dri))
    config = sandbox.Config(
        home=home,
        roots=(
            rw(mkdir(home / "project")),
            sandbox.Root(path=mkdir(tmp / "reference"), mode="ro"),
        ),
        ports=(),
        paths=(),
    )
    args = sandbox.bwrap_args(
        config,
        wayland_socket=tmp / "state" / "wayland-1",
        resolv_conf=tmp / "state" / "resolv-1.conf",
        sandbox_code=tmp / "state" / "code-1",
        env={"HOME": str(home), "LANG": "C.UTF-8"},
        command=("/usr/bin/true", "--flag"),
    )
    return config, args


def test_bwrap_namespace_flags_are_exact(built):
    _, args = built

    assert args[:15] == (
        "/usr/bin/bwrap",
        "--unshare-all",
        "--share-net",
        "--unshare-user",
        "--uid",
        str(os.getuid()),
        "--gid",
        str(os.getgid()),
        "--disable-userns",
        "--assert-userns-disabled",
        "--cap-drop",
        "ALL",
        "--die-with-parent",
        "--new-session",
        "--clearenv",
    )


def test_bwrap_ends_with_seccomp_fd_and_inner_stage(built):
    _, args = built

    assert args[-9:] == (
        "--seccomp",
        "3",
        "--",
        "/bin/sh",
        "-c",
        sandbox.INNER_STAGE,
        "sh",
        "/usr/bin/true",
        "--flag",
    )
    assert args.count("--seccomp") == 1


def test_bwrap_binds_no_secret_or_data_source(built):
    config, args = built
    home = config.home
    secrets = (
        home / ".ssh",
        home / ".config" / "gh",
        home / ".local" / "share" / "keyrings",
        Path("/data"),
    )

    sources = [Path(src) for option in BIND_OPTIONS for src, _ in options(args, option)]

    assert sources
    assert not [
        src for src in sources for secret in secrets if src.is_relative_to(secret)
    ]


def test_bwrap_ro_binds_every_home_ro_path(built):
    config, args = built

    expected = [(str(config.home / rel),) * 2 for rel in sandbox.HOME_RO_PATHS]

    assert options(args, "--ro-bind-try") == expected


def bare_bwrap_args(tmp):
    """Build bwrap arguments for the temp home with no roots."""
    home = tmp / "home"
    return sandbox.bwrap_args(
        sandbox.Config(home=home, roots=(), ports=(), paths=()),
        wayland_socket=tmp / "wayland-1",
        resolv_conf=tmp / "resolv-1.conf",
        sandbox_code=tmp / "code-1",
        env={"HOME": str(home)},
        command=("/usr/bin/true",),
    )


def test_bwrap_ro_binds_user_fonts_dir(tmp):
    fonts = tmp / "home" / ".fonts"

    args = bare_bwrap_args(tmp)

    # bwrap skips a --ro-bind-try whose source is absent
    assert (str(fonts), str(fonts)) in options(args, "--ro-bind-try")
    assert (str(fonts), str(fonts)) not in options(args, "--bind")


def test_bwrap_binds_sandbox_code_over_home_bin_shim(tmp):
    shim = mkdir(tmp / "home" / "bin") / "code"
    shim.touch()

    args = bare_bwrap_args(tmp)

    assert (str(tmp / "code-1"), str(shim)) in options(args, "--ro-bind")
    # Over the shim the ~/bin bind brings in, not under it
    assert args.index(str(shim.parent)) < args.index(str(tmp / "code-1"))


def test_bwrap_binds_no_sandbox_code_without_home_bin_shim(tmp):
    mkdir(tmp / "home" / "bin")

    args = bare_bwrap_args(tmp)

    assert str(tmp / "code-1") not in args


def test_sandbox_code_carries_the_wrapper_owned_switches():
    switches = sandbox.ELECTRON_SWITCHES

    command = shlex.split(sandbox.SANDBOX_CODE.splitlines()[1])

    assert "--no-sandbox" in switches
    assert command == ["exec", "/usr/bin/code", *switches, "$@"]


def test_sandbox_code_passes_switches_then_arguments_to_rpm_cli(tmp_path):
    received = tmp_path / "args"
    rpm_cli = tmp_path / "rpm-code"
    rpm_cli.write_text(f'#!/bin/sh\nprintf "%s\\0" "$@" > {received}\n')
    rpm_cli.chmod(0o755)
    code = tmp_path / "code"
    code.write_text(sandbox.SANDBOX_CODE.replace("/usr/bin/code", str(rpm_cli), 1))
    code.chmod(0o755)
    args = ["notes.py", "a  b", "", "*"]

    subprocess.run([code, *args], env={}, check=True, timeout=10)

    assert "/usr/bin/code" in sandbox.SANDBOX_CODE
    assert received.read_bytes().split(b"\0")[:-1] == [
        arg.encode() for arg in (*sandbox.ELECTRON_SWITCHES, *args)
    ]


def test_bwrap_rw_binds_only_profile_store_and_rw_roots(built):
    config, args = built
    home = config.home
    store = home / ".local" / "share" / "vscode-sandbox"

    assert sorted(options(args, "--bind")) == sorted(
        [
            (str(home / "project"),) * 2,
            (str(home / ".config" / "Code"),) * 2,
            (str(home / ".vscode"),) * 2,
            (str(home / ".vscode-shared"),) * 2,
            (str(store / "cache"), str(home / ".cache")),
            (
                str(store / "jupyter-runtime"),
                str(home / ".local" / "share" / "jupyter" / "runtime"),
            ),
        ]
    )


def test_bwrap_ro_binds_system_view_root_wayland_and_resolv(built, tmp):
    _, args = built
    resolv = str(Path("/etc/resolv.conf").resolve())

    assert options(args, "--ro-bind") == [
        ("/usr", "/usr"),
        ("/etc", "/etc"),
        *((path, path) for path in sandbox.SYS_PATHS),
        (str(tmp / "reference"),) * 2,
        (str(tmp / "state" / "wayland-1"), f"/run/user/{os.getuid()}/wayland-0"),
        (str(tmp / "state" / "resolv-1.conf"), resolv),
    ]


def test_bwrap_exposes_only_render_nodes(built):
    _, args = built

    assert [dest for _, dest in options(args, "--dev-bind")] == [
        "/dev/dri/renderD128",
        "/dev/dri/renderD129",
    ]


def test_bwrap_mounts_fresh_tmpfs_before_roots(built):
    config, args = built

    tmpfs = [args[index + 1] for index, arg in enumerate(args) if arg == "--tmpfs"]
    first_root = args.index(str(config.home / "project"))

    assert tmpfs == ["/dev/shm", "/tmp", "/run", str(config.home)]
    assert args.index(str(config.home)) < first_root
    assert first_root < args.index("--ro-bind-try")


def test_bwrap_sets_only_the_given_environment(built, tmp):
    _, args = built

    assert options(args, "--setenv") == [
        ("HOME", str(tmp / "home")),
        ("LANG", "C.UTF-8"),
    ]
    assert args.index("--clearenv") < args.index("--setenv")


def test_resolv_args_create_missing_parents_under_run():
    assert sandbox.resolv_args(
        Path("/state/resolv-1.conf"),
        Path("/run/systemd/resolve/stub-resolv.conf"),
    ) == (
        "--dir",
        "/run/systemd",
        "--dir",
        "/run/systemd/resolve",
        "--ro-bind",
        "/state/resolv-1.conf",
        "/run/systemd/resolve/stub-resolv.conf",
    )


def test_resolv_args_bind_over_etc_file_directly():
    assert sandbox.resolv_args(Path("/s/r.conf"), Path("/etc/resolv.conf")) == (
        "--ro-bind",
        "/s/r.conf",
        "/etc/resolv.conf",
    )


def test_pasta_args_without_ports():
    assert sandbox.pasta_args(()) == (
        "/usr/bin/pasta",
        "--config-net",
        "-t",
        "none",
        "-u",
        "none",
        "-T",
        "none",
        "-U",
        "none",
        "--no-map-gw",
        "--dns-forward",
        "169.254.1.1",
        "--",
    )


def test_pasta_args_forward_listed_ports_only():
    args = sandbox.pasta_args((3000, 8888))

    assert args[args.index("-T") + 1] == "3000,8888"
    assert args.count("-T") == 1
    assert args[2:4] == ("-t", "none")
    assert args[4:6] == ("-u", "none")


def test_stages_route_log_seccomp_and_ready_descriptors():
    outer = sandbox.outer_stage(
        Path("/store/code.log"), Path("/s/seccomp-1.bpf"), Path("/s/ready-1.fifo")
    )
    inner = sandbox.inner_stage(("/usr/share/code/code", "/p"))

    assert outer == (
        "/bin/sh",
        "-c",
        'exec >>"$1" 2>&1 3<"$2" 4>"$3"; shift 3; exec "$@"',
        "sh",
        "/store/code.log",
        "/s/seccomp-1.bpf",
        "/s/ready-1.fifo",
    )
    assert inner == (
        "/bin/sh",
        "-c",
        'printf r >&4 && exec 4>&- && exec "$@"',
        "sh",
        "/usr/share/code/code",
        "/p",
    )


def test_stages_open_and_close_descriptors(tmp):
    log = tmp / "code.log"
    log.write_text("earlier\n")
    seccomp = tmp / "seccomp.bpf"
    seccomp.write_text("program")
    ready = tmp / "ready"
    ready.write_text("")
    probe = (
        "/bin/sh",
        "-c",
        "cat <&3 && if { true >&4; } 2>/dev/null; then echo open; else echo closed; fi"
        " && echo err >&2",
    )

    result = subprocess.run(
        (
            *sandbox.outer_stage(log, seccomp, ready),
            *sandbox.inner_stage(probe),
        ),
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )

    assert (result.stdout, result.stderr) == ("", "")
    assert log.read_text() == "earlier\nprogramclosed\nerr\n"
    assert ready.read_text() == "r"


def test_electron_switches_follow_code_args(monkeypatch):
    monkeypatch.setattr(sandbox, "CODE_ARGS", ("--password-store=gnome", "--x"))

    args = sandbox.electron_args((Path("/p/a"), Path("/p/b.ipynb")))

    assert args == (
        "/usr/share/code/code",
        "--password-store=gnome",
        "--x",
        "--no-sandbox",
        "--ozone-platform=wayland",
        "--password-store=basic",
        "/p/a",
        "/p/b.ipynb",
    )


def test_sandbox_env_sets_wrapper_keys_and_forwards_locale(monkeypatch, tmp):
    monkeypatch.setattr(sandbox, "EXTRA_ENV", {"FOO": "bar"})
    home = tmp / "home"
    user = pwd.getpwuid(os.getuid()).pw_name

    env = sandbox.sandbox_env(
        {"HOME": "/elsewhere", "LANG": "C.UTF-8", "LC_TIME": "en_GB.UTF-8"},
        home=home,
    )

    assert env == {
        "HOME": str(home),
        "USER": user,
        "LOGNAME": user,
        "PATH": f"{home}/bin:{home}/.local/bin:/usr/local/bin:/usr/bin",
        "SHELL": "/bin/bash",
        "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}",
        "WAYLAND_DISPLAY": "wayland-0",
        "XDG_SESSION_TYPE": "wayland",
        "LANG": "C.UTF-8",
        "LC_TIME": "en_GB.UTF-8",
        "FOO": "bar",
    }


def test_sandbox_env_drops_bus_and_x11_variables(tmp):
    env = sandbox.sandbox_env(
        {
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
            "DBUS_SYSTEM_BUS_ADDRESS": "unix:path=/run/dbus/system_bus_socket",
            "DISPLAY": ":0",
        },
        home=tmp / "home",
    )

    assert not [key for key in env if key.startswith("DBUS_") or key == "DISPLAY"]


def test_sandbox_env_rejects_extra_env_collision(monkeypatch, tmp):
    monkeypatch.setattr(sandbox, "EXTRA_ENV", {"PATH": "/x", "SHELL": "/x", "OK": "1"})

    with pytest.raises(
        sandbox.SandboxError, match=r"EXTRA_ENV must not set PATH, SHELL$"
    ):
        sandbox.sandbox_env({}, home=tmp / "home")


# Preflight

BWRAP_VERSION = "bubblewrap 0.12.0\n"
PASTA_VERSION = "pasta 0^20261002.gcba3570-1.fc44.x86_64\n"


def stub(path, output, status=0):
    """Write an executable that prints output and exits with status."""
    path.write_text(f"#!/bin/sh\nprintf '%s' '{output}'\nexit {status}\n")
    path.chmod(0o755)
    return path


@pytest.fixture
def host(tmp, monkeypatch):
    """Point the binaries at stubs printing the T1.1 host versions."""
    bin_dir = mkdir(tmp / "usr-bin")
    monkeypatch.setattr(sandbox, "BWRAP", str(stub(bin_dir / "bwrap", BWRAP_VERSION)))
    monkeypatch.setattr(sandbox, "PASTA", str(stub(bin_dir / "pasta", PASTA_VERSION)))
    monkeypatch.setattr(sandbox, "ELECTRON", str(stub(bin_dir / "code", "")))
    runtime = mkdir(tmp / "runtime")
    env = {"XDG_RUNTIME_DIR": str(runtime), "WAYLAND_DISPLAY": "wayland-1"}
    return env, runtime


@pytest.fixture
def no_spawn(monkeypatch):
    """Fail the test if anything forks, spawns or runs a subprocess."""

    def fail(*args, **kwargs):
        raise AssertionError("spawned a process")

    monkeypatch.setattr(subprocess, "Popen", fail)
    monkeypatch.setattr(os, "fork", fail)
    monkeypatch.setattr(os, "posix_spawn", fail)
    monkeypatch.setattr(os, "posix_spawnp", fail)


def test_bwrap_version_parses_host_string():
    assert sandbox.bwrap_version(BWRAP_VERSION) == (0, 12, 0)


@pytest.mark.parametrize(
    ("output", "date"),
    [
        (PASTA_VERSION, 20261002),
        ("pasta 2025_04_15.2340bbf\n", 20250415),
    ],
)
def test_pasta_date_parses_fedora_and_upstream_strings(output, date):
    assert sandbox.pasta_date(output) == date


@pytest.mark.parametrize(
    ("parse", "output"),
    [
        ("bwrap_version", "bubblewrap\n"),
        ("bwrap_version", "bwrap 0.12.0\n"),
        ("pasta_date", "pasta unknown version\n"),
        ("pasta_date", "pasta 0^2026.g1-1\n"),
        ("pasta_date", "passt 2025_04_15.2340bbf\n"),
    ],
)
def test_unparsable_version_is_an_error(parse, output):
    with pytest.raises(sandbox.SandboxError, match="cannot parse"):
        getattr(sandbox, parse)(output)


def test_tool_version_returns_stdout(tmp):
    assert sandbox.tool_version(str(stub(tmp / "bwrap", BWRAP_VERSION))) == (
        BWRAP_VERSION
    )


def test_tool_version_failure_is_an_error(tmp):
    with pytest.raises(sandbox.SandboxError, match=r"cannot run .*bwrap --version"):
        sandbox.tool_version(str(stub(tmp / "bwrap", "", status=1)))


def test_preflight_creates_host_dirs(tmp, host):
    env, runtime = host
    home = tmp / "home"

    paths = sandbox.preflight(env, home=home)

    store = home / ".local" / "share" / "vscode-sandbox"
    assert paths == sandbox.HostPaths(
        state_dir=runtime / "vscode-sandbox",
        store=store,
        display=runtime / "wayland-1",
    )
    assert (runtime / "vscode-sandbox").stat().st_mode & 0o777 == 0o700
    assert store.stat().st_mode & 0o777 == 0o700
    for directory in (
        store / "cache",
        store / "jupyter-runtime",
        home / ".config" / "Code",
        home / ".vscode",
        home / ".vscode-shared",
    ):
        assert directory.is_dir()


def test_preflight_keeps_absolute_wayland_display(tmp, host):
    env, _ = host

    paths = sandbox.preflight(
        {**env, "WAYLAND_DISPLAY": "/elsewhere/wayland-9"}, home=tmp / "home"
    )

    assert paths.display == Path("/elsewhere/wayland-9")


def assert_nothing_created(tmp, runtime):
    assert not (runtime / "vscode-sandbox").exists()
    assert not (tmp / "home" / ".local").exists()


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("XDG_RUNTIME_DIR", None, "XDG_RUNTIME_DIR must be set"),
        ("XDG_RUNTIME_DIR", "runtime", "XDG_RUNTIME_DIR must be set"),
        ("WAYLAND_DISPLAY", None, "WAYLAND_DISPLAY must be set"),
        ("WAYLAND_DISPLAY", "", "WAYLAND_DISPLAY must be set"),
    ],
)
def test_preflight_missing_variable_raises_before_any_spawn(
    tmp, host, no_spawn, key, value, message
):
    env, runtime = host
    env.pop(key)
    if value is not None:
        env[key] = value

    with pytest.raises(sandbox.SandboxError, match=message):
        sandbox.preflight(env, home=tmp / "home")

    assert_nothing_created(tmp, runtime)


@pytest.mark.parametrize("constant", ["BWRAP", "PASTA", "ELECTRON"])
@pytest.mark.parametrize("kind", ["missing", "not executable", "directory"])
def test_preflight_missing_binary_raises_before_any_spawn(
    tmp, host, no_spawn, monkeypatch, constant, kind
):
    env, runtime = host
    path = tmp / "broken"
    if kind == "not executable":
        path.write_text("#!/bin/sh\n")
    elif kind == "directory":
        path.mkdir()
    monkeypatch.setattr(sandbox, constant, str(path))

    with pytest.raises(
        sandbox.SandboxError, match=f"{path} is missing or not executable"
    ):
        sandbox.preflight(env, home=tmp / "home")

    assert_nothing_created(tmp, runtime)


@pytest.mark.parametrize(
    ("bwrap", "pasta", "message"),
    [
        (
            "bubblewrap 0.11.2\n",
            PASTA_VERSION,
            r"bubblewrap >= 0\.12\.0 required, found 0\.11\.2",
        ),
        (
            BWRAP_VERSION,
            "pasta 0^20250414.g2340bbf-1.fc42.x86_64\n",
            "pasta >= 2025_04_15 required, found 20250414",
        ),
        (
            BWRAP_VERSION,
            "pasta 2024_12_31.abc1234\n",
            "pasta >= 2025_04_15 required, found 20241231",
        ),
        ("bwrap version unknown\n", PASTA_VERSION, "cannot parse .* --version"),
        (BWRAP_VERSION, "pasta unknown version\n", "cannot parse .* --version"),
    ],
)
def test_preflight_bad_version_raises_before_any_spawn(
    tmp, host, no_spawn, monkeypatch, bwrap, pasta, message
):
    env, runtime = host
    outputs = {sandbox.BWRAP: bwrap, sandbox.PASTA: pasta}
    monkeypatch.setattr(sandbox, "tool_version", outputs.__getitem__)

    with pytest.raises(sandbox.SandboxError, match=message):
        sandbox.preflight(env, home=tmp / "home")

    assert_nothing_created(tmp, runtime)


def test_preflight_accepts_minimum_versions(tmp, host, no_spawn, monkeypatch):
    env, _ = host
    outputs = {
        sandbox.BWRAP: "bubblewrap 0.12.0\n",
        sandbox.PASTA: "pasta 2025_04_15.2340bbf\n",
    }
    monkeypatch.setattr(sandbox, "tool_version", outputs.__getitem__)

    assert sandbox.preflight(env, home=tmp / "home").state_dir.is_dir()


def test_preflight_unwritable_store_is_an_error(tmp, host):
    env, _ = host
    (mkdir(tmp / "home" / ".local" / "share") / "vscode-sandbox").write_text("")

    with pytest.raises(sandbox.SandboxError, match=r"cannot create .*vscode-sandbox"):
        sandbox.preflight(env, home=tmp / "home")


# Environment access


def test_host_env_keeps_only_allowed_keys():
    environ = {
        "HOME": "/h",
        "XDG_RUNTIME_DIR": "/r",
        "WAYLAND_DISPLAY": "wayland-1",
        "LANG": "C.UTF-8",
        "LC_ALL": "C",
        "PATH": "/usr/bin",
        "VSCODE_SANDBOX_DISABLE": "1",
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
    }

    assert sandbox.host_env(environ) == {
        "HOME": "/h",
        "XDG_RUNTIME_DIR": "/r",
        "WAYLAND_DISPLAY": "wayland-1",
        "LANG": "C.UTF-8",
        "LC_ALL": "C",
    }


def test_script_reads_environment_only_through_host_env():
    tree = ast.parse(SCRIPT.read_text())
    names = {
        *(node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)),
        *(node.id for node in ast.walk(tree) if isinstance(node, ast.Name)),
        *(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        ),
    }
    environ_reads = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "environ"
    ]
    host_env_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "host_env"
    ]
    home_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "home"
    ]

    assert {"HOME", "XDG_RUNTIME_DIR", "WAYLAND_DISPLAY", "LANG"} == sandbox.ENV_KEYS
    assert not names & {
        "getenv",
        "getenvb",
        "environb",
        "expanduser",
        "expandvars",
        "getuser",
    }
    assert not home_calls
    assert len(environ_reads) == 1
    assert len(host_env_calls) == 1
    assert host_env_calls[0].args == [environ_reads[0]]
    assert ast.unparse(environ_reads[0]) == "os.environ"


# Interpreter isolation


def test_shebang_ignores_pythonpath_and_cwd_modules(tmp):
    interpreter, *flags = SCRIPT.read_text().splitlines()[0].removeprefix("#!").split()
    (tmp / "argparse.py").write_text("raise SystemExit('shadowed argparse')\n")

    result = subprocess.run(
        (sys.executable, *flags, str(SCRIPT), "--help"),
        cwd=tmp,
        env={"PYTHONPATH": f":{tmp}"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert interpreter == "/usr/bin/python3"
    assert result.returncode == 0, result.stderr
    assert "usage: vscode-sandbox" in result.stdout


# Seccomp


class FakeFilter:
    """Record the calls build_seccomp makes on a libseccomp SyscallFilter."""

    instances: ClassVar[list[FakeFilter]] = []

    def __init__(self, defaction):
        self.defaction = defaction
        self.calls = []
        FakeFilter.instances.append(self)

    def add_rule(self, action, syscall, *args):
        self.calls.append(("add_rule", action, syscall, args))

    def add_rule_exactly(self, action, syscall, *args):
        self.calls.append(("add_rule_exactly", action, syscall, args))

    def add_arch(self, arch):
        self.calls.append(("add_arch", arch))

    def export_bpf(self, file):
        file.write(b"bpf")


@pytest.fixture
def fake_seccomp(monkeypatch):
    """Install a fake seccomp module whose actions and arguments are plain tuples."""
    module = types.SimpleNamespace(
        ALLOW="ALLOW",
        ERRNO=lambda number: ("ERRNO", number),
        Arg=lambda arg, op, datum_a, datum_b=0: (arg, op, datum_a, datum_b),
        EQ="EQ",
        NE="NE",
        GE="GE",
        MASKED_EQ="MASKED_EQ",
        SyscallFilter=FakeFilter,
    )
    monkeypatch.setattr(FakeFilter, "instances", [])
    monkeypatch.setitem(sys.modules, "seccomp", module)
    return module


EPERM = ("ERRNO", errno.EPERM)
ENOSYS = ("ERRNO", errno.ENOSYS)
EAFNOSUPPORT = ("ERRNO", errno.EAFNOSUPPORT)
FLATPAK_EPERM = [
    "syslog",
    "uselib",
    "acct",
    "quotactl",
    "add_key",
    "keyctl",
    "request_key",
    "move_pages",
    "mbind",
    "get_mempolicy",
    "set_mempolicy",
    "migrate_pages",
    "unshare",
    "setns",
    "mount",
    "umount",
    "umount2",
    "pivot_root",
    "chroot",
    "modify_ldt",
    "perf_event_open",
    "ptrace",
]
FLATPAK_ENOSYS = [
    "clone3",
    "open_tree",
    "move_mount",
    "fsopen",
    "fsconfig",
    "fsmount",
    "fspick",
    "mount_setattr",
]
# CLONE_NEWNS, NEWCGROUP, NEWUTS, NEWIPC, NEWUSER, NEWPID, NEWNET
CLONE_FLAGS = (
    0x00020000,
    0x02000000,
    0x04000000,
    0x08000000,
    0x10000000,
    0x20000000,
    0x40000000,
)
TIOCSTI, TIOCLINUX = 0x5412, 0x541C
# Every family below AF_NETLINK (16) except AF_UNSPEC, AF_UNIX, AF_INET and AF_INET6
DENIED_FAMILIES = (3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15)


def test_build_seccomp_adds_exactly_the_flatpak_rules_and_clone_flags(
    tmp, fake_seccomp
):
    sandbox.build_seccomp(tmp / "seccomp.bpf")

    (bpf,) = FakeFilter.instances
    expected = [
        *(("add_rule", EPERM, name, ()) for name in FLATPAK_EPERM),
        *(("add_rule", ENOSYS, name, ()) for name in FLATPAK_ENOSYS),
        *(
            ("add_rule", EPERM, "clone", ((0, "MASKED_EQ", flag, flag),))
            for flag in CLONE_FLAGS
        ),
        *(
            ("add_rule", EPERM, "ioctl", ((1, "MASKED_EQ", 0xFFFFFFFF, request),))
            for request in (TIOCSTI, TIOCLINUX)
        ),
        ("add_rule", EPERM, "personality", ((0, "NE", 0, 0),)),
        *(
            ("add_rule_exactly", EAFNOSUPPORT, "socket", ((0, "EQ", family, 0),))
            for family in DENIED_FAMILIES
        ),
        ("add_rule_exactly", EAFNOSUPPORT, "socket", ((0, "GE", 17, 0),)),
    ]
    assert bpf.defaction == "ALLOW"
    assert sorted(bpf.calls, key=repr) == sorted(expected, key=repr)
    assert len([call for call in bpf.calls if call[2] == "clone"]) == 7
    assert (tmp / "seccomp.bpf").read_bytes() == b"bpf"


def test_build_seccomp_adds_no_architecture(tmp, fake_seccomp):
    sandbox.build_seccomp(tmp / "seccomp.bpf")

    (bpf,) = FakeFilter.instances
    assert not [call for call in bpf.calls if call[0] == "add_arch"]


def test_build_seccomp_missing_bindings_abort(tmp, monkeypatch):
    monkeypatch.setitem(sys.modules, "seccomp", None)

    with pytest.raises(sandbox.SandboxError, match="libseccomp-python"):
        sandbox.build_seccomp(tmp / "seccomp.bpf")

    assert not (tmp / "seccomp.bpf").exists()


def test_build_seccomp_libseccomp_error_aborts(tmp, fake_seccomp, monkeypatch):
    def fail(self, action, syscall, *args):
        raise RuntimeError("Library error (errno = -22)")

    monkeypatch.setattr(FakeFilter, "add_rule", fail)

    with pytest.raises(sandbox.SandboxError, match="cannot build the seccomp filter"):
        sandbox.build_seccomp(tmp / "seccomp.bpf")

    assert not (tmp / "seccomp.bpf").exists()


def test_build_seccomp_unwritable_path_aborts(tmp, fake_seccomp):
    with pytest.raises(sandbox.SandboxError, match="cannot build the seccomp filter"):
        sandbox.build_seccomp(tmp / "missing" / "seccomp.bpf")


# Wayland


def encode(object_id, opcode, *args):
    """Encode a Wayland message independently of the script's encoder."""
    body = b""
    for arg in args:
        if isinstance(arg, str):
            data = arg.encode() + b"\0"
            body += struct.pack("=I", len(data)) + data.ljust(
                -(-len(data) // 4) * 4, b"\0"
            )
        else:
            body += struct.pack("=I", arg)
    return struct.pack("=II", object_id, (8 + len(body)) << 16 | opcode) + body


MANAGER = "wp_security_context_manager_v1"
ALLOWED = (*sorted(sandbox.WAYLAND_GLOBALS), "wl_output", "wl_seat")


class FakeCompositor:
    """
    Serve one Wayland connection on a listening path from a thread.

    Advertises the given globals, answers wl_display.sync, keeps the fds sent with
    create_listener, and records every request with the fds it took. With
    error_on set to "get_registry" or "create_listener", that request is answered
    with wl_display.error; with silent set, nothing is ever answered.
    """

    def __init__(self, path, globals_, *, error_on=None, silent=False):
        self.globals = globals_
        self.error_on = error_on
        self.silent = silent
        self.requests = []
        self.fds = []
        self.eof = False
        self.registry = self.manager = None
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(str(path))
        self.listener.listen()
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        self.listener.settimeout(5)
        conn, _ = self.listener.accept()
        with conn:
            conn.settimeout(5)
            buffer, pending = b"", []
            while True:
                try:
                    data, fds, _, _ = socket.recv_fds(conn, 4096, 4)
                except TimeoutError, ConnectionResetError:
                    return
                pending += fds
                self.fds += fds
                if not data:
                    self.eof = True
                    return
                buffer += data
                while len(buffer) >= 8:
                    size = struct.unpack_from("=I", buffer, 4)[0] >> 16
                    if len(buffer) < size:
                        break
                    message, buffer = buffer[:size], buffer[size:]
                    object_id, header = struct.unpack_from("=II", message)
                    opcode = header & 0xFFFF
                    taken = 2 if (object_id, opcode) == (self.manager, 1) else 0
                    self.requests.append((message, pending[:taken]))
                    del pending[:taken]
                    if self.silent:
                        continue
                    try:
                        self.respond(conn, object_id, opcode, message[8:])
                    except BrokenPipeError:
                        return

    def respond(self, conn, object_id, opcode, body):
        (first,) = struct.unpack_from("=I", body) if body else (None,)
        if (object_id, opcode) == (1, 1):
            self.registry = first
            if self.error_on == "get_registry":
                conn.sendall(encode(1, 0, 1, 1, "invalid method"))
                return
            for name, interface in enumerate(self.globals, start=1):
                conn.sendall(encode(first, 0, name, interface, 1))
        elif (object_id, opcode) == (1, 0):
            conn.sendall(encode(first, 0, 0) + encode(1, 1, first))
        elif (object_id, opcode) == (self.registry, 0):
            (self.manager,) = struct.unpack_from("=I", body, len(body) - 4)
        elif (object_id, opcode) == (self.manager, 1) and self.error_on == (
            "create_listener"
        ):
            conn.sendall(encode(1, 0, self.manager, 0, "listen_fd is not listening"))

    def join(self):
        self.thread.join(timeout=10)
        assert not self.thread.is_alive()
        self.listener.close()

    def close_fds(self):
        for fd in self.fds:
            os.close(fd)


@pytest.fixture
def short_dir():
    """Provide a directory short enough for AF_UNIX socket paths."""
    path = Path(tempfile.mkdtemp(prefix="vsb-"))
    yield path
    shutil.rmtree(path)


@pytest.fixture
def compositors():
    """Track fake compositors so their threads and received fds are cleaned up."""
    started = []

    def start(*args, **kwargs):
        compositor = FakeCompositor(*args, **kwargs)
        started.append(compositor)
        return compositor

    yield start
    for compositor in started:
        compositor.join()
        compositor.close_fds()


def hung_up(fd):
    """Report whether the peer of a pipe read end has closed every write end."""
    poller = select.poll()
    poller.register(fd, select.POLLIN)
    return any(events & select.POLLHUP for _, events in poller.poll(0))


def test_wl_message_encodes_strings_padded_to_four_bytes():
    assert sandbox.wl_message(2, 0, "abc") == encode(2, 0, "abc")
    assert sandbox.wl_message(2, 0, "abcd") == (
        struct.pack("=III", 2, 20 << 16, 5) + b"abcd\0\0\0\0"
    )


def test_wl_string_decodes_and_skips_padding():
    body = struct.pack("=I", 5) + b"abcd\0\0\0\0" + struct.pack("=I", 9)

    assert sandbox.wl_string(body, 0) == ("abcd", 12)


def test_create_security_context_sends_exact_requests(short_dir, compositors):
    display, listener = short_dir / "display", short_dir / "listener"
    compositor = compositors(display, (*ALLOWED, MANAGER))

    close_fd = sandbox.create_security_context(display, listener)
    os.close(close_fd)
    compositor.join()

    manager_name = len(ALLOWED) + 1
    assert [message for message, _ in compositor.requests] == [
        struct.pack("=III", 1, 12 << 16 | 1, 2),
        struct.pack("=III", 1, 12 << 16 | 0, 3),
        struct.pack("=III", 2, 56 << 16 | 0, manager_name)
        + struct.pack("=I", 31)
        + b"wp_security_context_manager_v1\0\0"
        + struct.pack("=II", 1, 4),
        struct.pack("=III", 4, 12 << 16 | 1, 5),
        struct.pack("=II", 5, 8 << 16 | 4),
        struct.pack("=III", 1, 12 << 16 | 0, 6),
    ]
    assert [len(fds) for _, fds in compositor.requests] == [0, 0, 0, 2, 0, 0]


def test_create_security_context_passes_listening_socket_then_close_fd(
    short_dir, compositors
):
    display, listener = short_dir / "display", short_dir / "listener"
    compositor = compositors(display, (*ALLOWED, MANAGER))

    close_fd = sandbox.create_security_context(display, listener)
    compositor.join()

    (_, (listen_fd, close_read)) = compositor.requests[3]
    with socket.socket(fileno=os.dup(listen_fd)) as received:
        assert received.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN) == 1
        assert received.getsockname() == str(listener)
    assert stat.S_ISFIFO(os.fstat(close_read).st_mode)
    assert stat.S_ISFIFO(os.fstat(close_fd).st_mode)
    assert not hung_up(close_read)
    os.close(close_fd)
    assert hung_up(close_read)


def test_create_security_context_listener_outlives_the_connection(
    short_dir, compositors
):
    display, listener = short_dir / "display", short_dir / "listener"
    compositor = compositors(display, (*ALLOWED, MANAGER))

    close_fd = sandbox.create_security_context(display, listener)
    compositor.join()

    assert compositor.eof
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(5)
        client.connect(str(listener))
    os.close(close_fd)


def test_create_security_context_without_manager_aborts(short_dir, compositors):
    display, listener = short_dir / "display", short_dir / "listener"
    compositor = compositors(display, ALLOWED)

    with pytest.raises(sandbox.SandboxError, match=f"offers no {MANAGER}"):
        sandbox.create_security_context(display, listener)
    compositor.join()

    assert not listener.exists()
    assert len(compositor.requests) == 2


def test_create_security_context_error_event_aborts_and_closes_close_fd(
    short_dir, compositors
):
    display, listener = short_dir / "display", short_dir / "listener"
    compositor = compositors(display, (*ALLOWED, MANAGER), error_on="create_listener")

    with pytest.raises(sandbox.SandboxError, match="listen_fd is not listening"):
        sandbox.create_security_context(display, listener)
    compositor.join()

    (_, (_, close_read)) = compositor.requests[3]
    assert hung_up(close_read)


def test_create_security_context_times_out_on_silent_compositor(
    short_dir, compositors, monkeypatch
):
    monkeypatch.setattr(sandbox, "WAYLAND_TIMEOUT", 1.0)
    display = short_dir / "display"
    compositors(display, (*ALLOWED, MANAGER), silent=True)

    start = time.monotonic()
    with pytest.raises(sandbox.SandboxError, match=r"no reply .* within 1\.0 s"):
        sandbox.create_security_context(display, short_dir / "listener")

    assert time.monotonic() - start < 4


def test_create_security_context_missing_display_aborts(short_dir):
    with pytest.raises(sandbox.SandboxError, match="Wayland setup through"):
        sandbox.create_security_context(short_dir / "none", short_dir / "listener")


def test_audit_globals_accepts_the_allowlist(short_dir, compositors):
    compositors(short_dir / "listener", ALLOWED)

    sandbox.audit_globals(short_dir / "listener")


@pytest.mark.parametrize(
    "extra", ["zwlr_screencopy_manager_v1", MANAGER, "ext_workspace_manager_v1"]
)
def test_audit_globals_rejects_an_extra_global(short_dir, compositors, extra):
    compositors(short_dir / "listener", (*ALLOWED, extra))

    with pytest.raises(sandbox.SandboxError, match=f"WAYLAND_GLOBALS: {extra}$"):
        sandbox.audit_globals(short_dir / "listener")


def test_audit_globals_error_event_aborts(short_dir, compositors):
    compositors(short_dir / "listener", ALLOWED, error_on="get_registry")

    with pytest.raises(sandbox.SandboxError, match="Wayland error 1 on object 1"):
        sandbox.audit_globals(short_dir / "listener")


def test_audit_globals_times_out_on_silent_listener(
    short_dir, compositors, monkeypatch
):
    monkeypatch.setattr(sandbox, "WAYLAND_TIMEOUT", 1.0)
    compositors(short_dir / "listener", ALLOWED, silent=True)

    start = time.monotonic()
    with pytest.raises(sandbox.SandboxError, match=r"no reply .* within 1\.0 s"):
        sandbox.audit_globals(short_dir / "listener")

    assert time.monotonic() - start < 4


# Lock


# Prefix for python -c drivers: loads the script given as argv[1] as `sandbox`
LOAD = """
import importlib.util
import os
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

sys.dont_write_bytecode = True
loader = SourceFileLoader("vscode_sandbox", sys.argv[1])
spec = importlib.util.spec_from_loader("vscode_sandbox", loader)
sandbox = importlib.util.module_from_spec(spec)
loader.exec_module(sandbox)
"""

ACQUIRE = (
    LOAD
    + """
try:
    sandbox.acquire_lock(Path(sys.argv[2]))
except sandbox.SandboxError as error:
    sys.exit(str(error))
print("locked", flush=True)
if sys.argv[3:] == ["hold"]:
    sys.stdin.read()
"""
)


def acquire(state, *extra):
    return subprocess.run(
        (sys.executable, "-c", ACQUIRE, str(SCRIPT), str(state), *extra),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_lock_contention_fails_until_the_holder_is_killed(tmp):
    state = mkdir(tmp / "state")
    holder = subprocess.Popen(
        (sys.executable, "-c", ACQUIRE, str(SCRIPT), str(state), "hold"),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None
        assert select.select([holder.stdout], [], [], 30)[0]
        assert holder.stdout.readline() == "locked\n"

        contended = acquire(state)

        holder.kill()
        assert holder.wait(timeout=30) == -9
        after_kill = acquire(state)
    finally:
        holder.kill()
        holder.wait(timeout=30)

    assert contended.returncode == 1
    assert contended.stderr == (
        "vscode-sandbox is already running; open the path from the running window, "
        "or close it and relaunch\n"
    )
    assert after_kill.returncode == 0, after_kill.stderr
    assert after_kill.stdout == "locked\n"
    assert (state / "lock").stat().st_mode & 0o777 == 0o600


# Supervision


# Replaces preflight, seccomp and the Wayland steps, stubs pasta and bwrap, and runs
# main() with the test command in place of Electron
LAUNCH = (
    LOAD
    + """
import json
import subprocess
import time

spec = json.loads(sys.argv[2])
tmp = Path(spec["tmp"])
host = sandbox.HostPaths(
    state_dir=tmp / "state", store=tmp / "store", display=tmp / "wayland-1"
)


def build_seccomp(path):
    (tmp / "after-purge").write_text(" ".join(sorted(os.listdir(host.state_dir))))
    path.write_bytes(b"")


def create_security_context(display_path, socket_path):
    socket_path.touch()
    read_end, write_end = os.pipe()
    os.close(read_end)
    return write_end


def recorded_supervise(*args, **kwargs):
    (tmp / "supervisor.pid.tmp").write_text(str(os.getpid()))
    os.replace(tmp / "supervisor.pid.tmp", tmp / "supervisor.pid")
    return supervise(*args, **kwargs)


def hold_spawn():
    (tmp / "spawn-held").touch()
    while not (tmp / "spawn-go").exists():
        time.sleep(0.05)


def gated_popen(*args, **kwargs):
    hold_spawn()
    return popen(*args, **kwargs)


def recorded_popen(*args, **kwargs):
    (tmp / "popen-called").touch()
    return popen(*args, **kwargs)


def gated_getppid():
    # Sampled first, so the guard's parent check passes and only a pending stop
    # can cancel the spawn
    ppid = getppid()
    hold_spawn()
    return ppid


run_sandbox = sandbox.run_sandbox
supervise = sandbox.supervise
sandbox.supervise = recorded_supervise
popen = subprocess.Popen
if spec["gate_spawn"] == "popen":
    subprocess.Popen = gated_popen
elif spec["gate_spawn"] == "check":
    subprocess.Popen = recorded_popen
    getppid = os.getppid
    os.getppid = gated_getppid
if not spec["find_outer"]:
    sandbox.find_outer = lambda pasta, pasta_fd: None
if not spec["subreaper"]:
    # An invalid option makes the supervisor's prctl fail
    sandbox.PR_SET_CHILD_SUBREAPER = -1
sandbox.PASTA = spec["pasta"]
sandbox.BWRAP = spec["bwrap"]
sandbox.READY_TIMEOUT = spec["ready_timeout"]
if not spec["pasta_deathsig"]:
    # As on Fedora, where the exec into pasta_t clears pasta's parent-death signal
    sandbox.die_with_parent = lambda parent: None
sandbox.preflight = lambda env, *, home: host
sandbox.build_seccomp = build_seccomp
sandbox.create_security_context = create_security_context
sandbox.audit_globals = lambda socket_path: None
sandbox.resolve_config = lambda args, **kwargs: sandbox.Config(
    home=tmp / "home", roots=(), ports=(), paths=()
)
sandbox.electron_args = lambda paths: tuple(spec["command"])
sandbox.run_sandbox = lambda config, command, *, env, detach: run_sandbox(
    config, command, env=env, detach=spec["detach"]
)
sys.exit(sandbox.main([]))
"""
)

# Drops the stubbed tool's options up to "--" and execs the rest, as pasta and bwrap do
EXEC_REST = 'while [ "$1" != -- ]; do shift; done; shift; exec "$@"'


def shell_tool(path, body):
    """Write an executable /bin/sh script."""
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(0o755)
    return path


def gone(pid):
    """Report whether a process has exited."""
    try:
        status = Path(f"/proc/{pid}/stat").read_text()
    except FileNotFoundError, ProcessLookupError:
        return True
    return status.rsplit(")", 1)[1].split()[0] == "Z"


def proc_entries():
    """Yield each running pid's /proc directory."""
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            yield entry


def children(pid):
    """Return the pids whose parent is pid."""
    found = set()
    for entry in proc_entries():
        try:
            status = (entry / "stat").read_text()
        except FileNotFoundError, ProcessLookupError:
            continue
        if int(status.rsplit(")", 1)[1].split()[1]) == pid:
            found.add(int(entry.name))
    return found


def strays(tmp):
    """
    Return the live processes whose command line names tmp: launchers, supervisors,
    guards, and stubs before they exec.
    """
    found = set()
    for entry in proc_entries():
        try:
            cmdline = (entry / "cmdline").read_bytes()
        except FileNotFoundError, ProcessLookupError:
            continue
        if str(tmp).encode() in cmdline:
            found.add(int(entry.name))
    return found


def wait_for(predicate, timeout=10.0):
    """Poll until predicate holds, failing after timeout seconds."""
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.05)


def state_entries(tmp):
    return sorted(os.listdir(tmp / "state"))


@pytest.fixture
def launch(tmp):
    """
    Run the launcher in a subprocess; the supervisor records its pid, and pasta's stub
    its own before exec. With gate_spawn, the guard holds until spawn-go exists, in its
    pre-spawn checks ("check") or in Popen ("popen"). Without find_outer, the guard
    never finds the outer stage; without subreaper, the supervisor cannot become one.
    """
    (tmp / "state").mkdir(mode=0o700)
    mkdir(tmp / "store")

    def run(
        command=("/bin/true",),
        *,
        pasta=EXEC_REST,
        bwrap=EXEC_REST,
        ready_timeout=30.0,
        detach=True,
        wait=True,
        pasta_deathsig=True,
        gate_spawn=None,
        find_outer=True,
        subreaper=True,
    ):
        record = f'echo $$ > "{tmp}/pasta.pid"'
        spec = {
            "tmp": str(tmp),
            "pasta": str(shell_tool(tmp / "pasta", f"{record}\n{pasta}")),
            "bwrap": str(shell_tool(tmp / "bwrap", bwrap)),
            "ready_timeout": ready_timeout,
            "command": command,
            "detach": detach,
            "pasta_deathsig": pasta_deathsig,
            "gate_spawn": gate_spawn,
            "find_outer": find_outer,
            "subreaper": subreaper,
        }
        argv = (sys.executable, "-c", LAUNCH, str(SCRIPT), json.dumps(spec))
        env = {
            "HOME": str(tmp / "home"),
            "XDG_RUNTIME_DIR": str(tmp / "runtime"),
            "PATH": "/usr/bin:/bin",
        }
        if not wait:
            return subprocess.Popen(
                argv,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        return subprocess.run(
            argv, env=env, capture_output=True, text=True, timeout=30, check=False
        )

    yield run
    for name in ("pasta.pid", "supervisor.pid"):
        path = tmp / name
        if path.exists() and not gone(pid := int(path.read_text())):
            os.kill(pid, signal.SIGKILL)
    for pid in strays(tmp):
        os.kill(pid, signal.SIGKILL)


def pid_of(tmp, name):
    path = tmp / f"{name}.pid"
    wait_for(path.exists)
    return int(path.read_text())


def parent_of(pid):
    return int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[1])


def guard_of(tmp):
    """Return the guard's pid: pasta's parent."""
    return parent_of(pid_of(tmp, "pasta"))


def ns_init_of(pasta):
    """Wait for pasta's child that is PID 1 of its PID namespace, and return it."""

    def ns_inits():
        found = set()
        for child in children(pasta):
            try:
                status = Path(f"/proc/{child}/status").read_text()
            except FileNotFoundError, ProcessLookupError:
                continue
            if re.search(r"^NSpid:.*\t1$", status, re.MULTILINE):
                found.add(child)
        return found

    wait_for(ns_inits)
    (init,) = ns_inits()
    return init


def holds_pidfd_on(holder, pid):
    """Report whether holder has a pidfd open on pid."""
    for fd in os.listdir(f"/proc/{holder}/fd"):
        try:
            target = os.readlink(f"/proc/{holder}/fd/{fd}")
            info = Path(f"/proc/{holder}/fdinfo/{fd}").read_text()
        except FileNotFoundError:
            continue
        if target == "anon_inode:[pidfd]" and f"Pid:\t{pid}\n" in info:
            return True
    return False


def outer_stage_of(tmp):
    """
    Return pasta's and its namespace init's pids once the guard holds a pidfd on the
    namespace init.
    """
    pasta = pid_of(tmp, "pasta")
    init = ns_init_of(pasta)
    wait_for(lambda: holds_pidfd_on(parent_of(pasta), init))
    return pasta, init


def lock_free(tmp):
    """Report whether the lock can be taken; release it at once if so."""
    try:
        fd = sandbox.acquire_lock(tmp / "state")
    except sandbox.SandboxError:
        return False
    os.close(fd)
    return True


def wait_until_unlocked(tmp, pids):
    """
    Wait until the lock is free, then check that no process in pids, and none naming
    tmp, outlived it.
    """
    wait_for(lambda: lock_free(tmp))
    assert [pid for pid in pids if not gone(pid)] == []
    assert not strays(tmp)


def stop_holding_pasta(tmp, pasta, init, trigger):
    """
    Stop the sandbox with trigger while pasta is stopped, so it cannot reap the outer
    stage: the lock stays held after the outer stage dies, until pasta has exited.
    """
    os.kill(pasta, signal.SIGSTOP)
    trigger()
    wait_for(lambda: gone(init))
    held = not lock_free(tmp)
    os.kill(pasta, signal.SIGCONT)
    assert held
    wait_until_unlocked(tmp, (pasta, init))


def hold(tmp, name):
    """Shell code that creates <name>-held, then waits until <name>-go exists."""
    return (
        f'touch "{tmp}/{name}-held"; '
        f'while [ ! -e "{tmp}/{name}-go" ]; do sleep 0.05; done'
    )


def ns_pasta(tmp, *, before="", inside=""):
    """
    A pasta stub that, like pasta, runs the rest as PID 1 of a new PID namespace and
    stays its parent, next to a helper child. It ignores SIGTERM and never kills its
    children, as SELinux keeps pasta from signalling the sandbox. before runs ahead of
    the namespace, inside in the namespace ahead of the outer stage.
    """
    init = f"{inside}; " if inside else ""
    return (
        f"trap '' TERM; "
        f'tail -f "{tmp}/pasta.pid" > /dev/null & '
        f"{before}{'; ' if before else ''}"
        'while [ "$1" != -- ]; do shift; done; shift; '
        f"exec unshare --user --pid --fork -- /bin/sh -c '{init}exec \"$@\"' "
        f'"{tmp}/ns-init" "$@"'
    )


def loop(tmp):
    """A command that runs until killed; its argv names tmp."""
    return ("/bin/sh", "-c", "while :; do sleep 0.05; done", str(tmp))


# Reports fd 4, stdin, stdout and whether stdin or stdout is a TTY to "$1"
FD_REPORT = (
    "if { true >&4; } 2>/dev/null; then fd4=open; else fd4=closed; fi; "
    "if [ -t 0 ] || [ -t 1 ]; then tty=tty; else tty=none; fi; "
    'printf "%s\\n" "$fd4" "$(readlink /proc/$$/fd/0)" "$(readlink /proc/$$/fd/1)" '
    '"$tty" > "$1.tmp" && mv "$1.tmp" "$1"'
)


def test_ready_sandbox_detaches_with_launcher_exit_0(tmp, launch):
    report = tmp / "report"

    result = launch(("/bin/sh", "-c", FD_REPORT, "sh", str(report)))

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    wait_for(report.exists)
    assert report.read_text().splitlines() == [
        "closed",
        "/dev/null",
        str(tmp / "store" / "code.log"),
        "none",
    ]
    wait_for(lambda: gone(pid_of(tmp, "supervisor")))
    assert not strays(tmp)
    assert state_entries(tmp) == ["lock"]


@pytest.mark.parametrize("detach", [True, False])
def test_log_receives_bwrap_and_command_output_but_not_pastas(tmp, launch, detach):
    log = tmp / "store" / "code.log"
    log.write_text("previous launch\n")
    stdio = " ".join(f'"$(readlink /proc/$$/fd/{fd})"' for fd in (0, 1, 2))
    pasta = (
        f'printf "%s\\n" {stdio} > "{tmp}/pasta-stdio"; '
        f"echo pasta-out; echo pasta-err >&2; {EXEC_REST}"
    )
    bwrap = f"echo bwrap-out; echo bwrap-err >&2; {EXEC_REST}"

    result = launch(
        ("/bin/sh", "-c", "echo command-out; echo command-err >&2"),
        pasta=pasta,
        bwrap=bwrap,
        detach=detach,
    )

    assert result.returncode == 0, result.stderr
    if detach:
        wait_for(lambda: gone(pid_of(tmp, "supervisor")))
    assert (tmp / "pasta-stdio").read_text().splitlines() == ["/dev/null"] * 3
    assert log.read_text() == "bwrap-out\nbwrap-err\ncommand-out\ncommand-err\n"


def test_bwrap_failure_before_exec_exits_1_naming_the_log(tmp, launch):
    result = launch(bwrap="exit 3")

    assert result.returncode == 1
    assert re.fullmatch(
        r"vscode-sandbox: error: the sandbox (exited|stopped) before it was ready"
        r"( \(pasta's output is not logged\))?; see "
        rf"{re.escape(str(tmp))}/store/code.log\n",
        result.stderr,
    )
    assert state_entries(tmp) == ["lock"]


def test_pasta_exiting_before_the_outer_stage_does_not_hang(tmp, launch):
    start = time.monotonic()

    result = launch(pasta="exit 0")

    assert time.monotonic() - start < 10
    assert result.returncode == 1
    assert result.stderr == (
        "vscode-sandbox: error: the sandbox stopped before it was ready (pasta's "
        f"output is not logged); see {tmp}/store/code.log\n"
    )
    assert state_entries(tmp) == ["lock"]


def test_pasta_never_ready_is_killed_after_ready_timeout(tmp, launch):
    start = time.monotonic()

    # SIGTERM is ignored, so the guard's SIGKILL stops it, not PR_SET_PDEATHSIG
    result = launch(pasta="trap '' TERM; exec sleep 30", ready_timeout=1.0)

    assert time.monotonic() - start < 10
    assert result.returncode == 1
    assert result.stderr == (
        "vscode-sandbox: error: the sandbox was not ready within 1.0 s; see "
        f"{tmp}/store/code.log\n"
    )
    assert gone(pid_of(tmp, "pasta"))
    assert not strays(tmp)
    assert state_entries(tmp) == ["lock"]


def test_sigterm_to_supervisor_stops_the_stubs_and_removes_launch_files(tmp, launch):
    result = launch(("/bin/sleep", "30"))
    assert result.returncode == 0, result.stderr
    pasta, supervisor = pid_of(tmp, "pasta"), pid_of(tmp, "supervisor")
    assert not gone(pasta)
    assert len(state_entries(tmp)) == 6

    os.kill(supervisor, signal.SIGTERM)

    wait_for(lambda: gone(pasta) and gone(supervisor))
    assert not strays(tmp)
    assert state_entries(tmp) == ["lock"]


@pytest.mark.parametrize(
    ("bwrap", "logged"),
    [
        (EXEC_REST, r"the launcher exited before the sandbox was ready"),
        (
            "exit 3",
            r"the sandbox (exited|stopped) before it was ready( \(pasta's output is "
            r"not logged\))?; see .*/code\.log",
        ),
    ],
)
def test_interrupted_launcher_stops_the_sandbox(tmp, launch, bwrap, logged):
    started, go = tmp / "bwrap-started", tmp / "go"
    # SIGTERM is ignored from here on, so the guard's SIGKILL stops the sandbox, not
    # PR_SET_PDEATHSIG
    hold = (
        f'trap \'\' TERM; touch "{started}"; while [ ! -e "{go}" ]; do sleep 0.05; done'
    )
    launcher = launch(("/bin/sleep", "30"), bwrap=f"{hold}; {bwrap}", wait=False)
    wait_for(started.exists)
    pasta, supervisor = pid_of(tmp, "pasta"), pid_of(tmp, "supervisor")

    launcher.send_signal(signal.SIGINT)
    _, stderr = launcher.communicate(timeout=30)
    go.touch()

    wait_for(lambda: gone(pasta) and gone(supervisor))
    assert launcher.returncode == 130
    assert stderr == "vscode-sandbox: error: interrupted\n"
    assert re.fullmatch(
        rf"vscode-sandbox: error: {logged}\n", (tmp / "store" / "code.log").read_text()
    )
    assert not strays(tmp)
    assert state_entries(tmp) == ["lock"]


def test_launch_binds_executable_sandbox_code_over_home_bin_shim(tmp, launch):
    home = tmp / "home"
    (mkdir(home / "bin") / "code").touch()
    copy = tmp / "sandbox-code"
    bwrap = (
        'while [ "$1" != -- ]; do '
        f'if [ "$1" = --ro-bind ] && [ "$3" = "{home}/bin/code" ]; then '
        f'cp -p "$2" "{copy}"; fi; shift; done; shift; exec "$@"'
    )

    result = launch(bwrap=bwrap, detach=False)

    assert result.returncode == 0, result.stderr
    assert copy.read_text() == sandbox.SANDBOX_CODE
    assert os.access(copy, os.X_OK)
    assert state_entries(tmp) == ["lock"]


def test_stale_launch_files_are_purged_before_the_launch(tmp, launch):
    state = tmp / "state"
    for name in (
        "wayland-999999",
        "seccomp-999999.bpf",
        "resolv-999999.conf",
        "code-999999",
    ):
        (state / name).touch()
    os.mkfifo(state / "ready-999999.fifo")

    result = launch()

    assert result.returncode == 0, result.stderr
    assert (tmp / "after-purge").read_text() == "lock"


@pytest.mark.parametrize(
    ("script", "status"), [("exit 7", 7), ("kill -KILL $$", 128 + signal.SIGKILL)]
)
def test_undetached_launch_returns_pasta_exit_status(tmp, launch, script, status):
    result = launch(("/bin/sh", "-c", script), detach=False)

    assert result.returncode == status, result.stderr
    assert not strays(tmp)
    assert state_entries(tmp) == ["lock"]


@pytest.mark.parametrize("gate", ["check", "popen"])
def test_supervisor_death_before_pasta_starts_keeps_the_lock_until_teardown(
    tmp, launch, gate
):
    launcher = launch(
        loop(tmp),
        pasta=ns_pasta(tmp),
        pasta_deathsig=False,
        gate_spawn=gate,
        wait=False,
    )
    wait_for((tmp / "spawn-held").exists)

    os.kill(pid_of(tmp, "supervisor"), signal.SIGKILL)
    _, stderr = launcher.communicate(timeout=30)
    held = not lock_free(tmp)
    (tmp / "spawn-go").touch()

    assert launcher.returncode == 1
    assert stderr == (
        "vscode-sandbox: error: the supervisor exited before the sandbox was ready; "
        f"see {tmp}/store/code.log\n"
    )
    assert held
    wait_until_unlocked(tmp, ())
    if gate == "check":
        assert not (tmp / "popen-called").exists()


def test_supervisor_death_before_the_outer_stage_is_found_kills_pasta(tmp, launch):
    launcher = launch(
        loop(tmp),
        pasta=ns_pasta(tmp, before=hold(tmp, "pasta")),
        pasta_deathsig=False,
        wait=False,
    )
    wait_for((tmp / "pasta-held").exists)
    pasta = pid_of(tmp, "pasta")

    os.kill(pid_of(tmp, "supervisor"), signal.SIGKILL)
    wait_for(lambda: gone(pasta))
    (tmp / "pasta-go").touch()

    launcher.communicate(timeout=30)
    assert launcher.returncode == 1
    wait_until_unlocked(tmp, (pasta,))


def test_supervisor_death_with_the_outer_stage_not_yet_found_kills_it(tmp, launch):
    result = launch(
        loop(tmp), pasta=ns_pasta(tmp), pasta_deathsig=False, find_outer=False
    )
    assert result.returncode == 0, result.stderr
    pasta = pid_of(tmp, "pasta")
    init = ns_init_of(pasta)

    os.kill(pid_of(tmp, "supervisor"), signal.SIGKILL)

    wait_until_unlocked(tmp, (pasta, init))


def test_supervisor_death_while_the_outer_stage_blocks_opening_fd_4(tmp, launch):
    launcher = launch(
        loop(tmp),
        pasta=ns_pasta(tmp, inside=hold(tmp, "init")),
        pasta_deathsig=False,
        wait=False,
    )
    wait_for((tmp / "init-held").exists)
    pasta, init = outer_stage_of(tmp)
    guard, supervisor = parent_of(pasta), pid_of(tmp, "supervisor")
    # Stopped, the guard acts only once the outer stage blocks on the FIFO, which has
    # no reader left
    os.kill(guard, signal.SIGSTOP)
    os.kill(supervisor, signal.SIGKILL)
    wait_for(lambda: gone(supervisor))
    # Exited, the launcher holds no lock copy that could stand in for the guard's
    launcher.wait(timeout=30)
    (tmp / "init-go").touch()
    wait_for(lambda: Path(f"/proc/{init}/wchan").read_text() == "wait_for_partner")

    stop_holding_pasta(tmp, pasta, init, lambda: os.kill(guard, signal.SIGCONT))

    launcher.communicate(timeout=30)
    assert launcher.returncode == 1


@pytest.mark.parametrize("ready", [False, True], ids=["bwrap setup", "ready"])
def test_supervisor_death_after_the_outer_stage_is_found_kills_it(tmp, launch, ready):
    bwrap = EXEC_REST if ready else f"{hold(tmp, 'bwrap')}; {EXEC_REST}"
    launcher = launch(
        loop(tmp), pasta=ns_pasta(tmp), bwrap=bwrap, pasta_deathsig=False, wait=False
    )
    if ready:
        launcher.communicate(timeout=30)
        assert launcher.returncode == 0
    else:
        wait_for((tmp / "bwrap-held").exists)
    pasta, init = outer_stage_of(tmp)
    supervisor = pid_of(tmp, "supervisor")

    def kill_supervisor():
        os.kill(supervisor, signal.SIGKILL)
        # Exited, the launcher holds no lock copy that could stand in for the guard's
        launcher.wait(timeout=30)

    stop_holding_pasta(tmp, pasta, init, kill_supervisor)

    launcher.communicate(timeout=30)
    assert launcher.returncode == (0 if ready else 1)


def test_sigterm_to_supervisor_kills_the_outer_stage(tmp, launch):
    result = launch(loop(tmp), pasta=ns_pasta(tmp), pasta_deathsig=False)
    assert result.returncode == 0, result.stderr
    pasta, init = outer_stage_of(tmp)

    os.kill(pid_of(tmp, "supervisor"), signal.SIGTERM)

    wait_until_unlocked(tmp, (pasta, init))
    assert state_entries(tmp) == ["lock"]


def test_ready_timeout_kills_the_outer_stage(tmp, launch):
    result = launch(
        loop(tmp),
        pasta=ns_pasta(tmp),
        bwrap=f"{hold(tmp, 'bwrap')}; {EXEC_REST}",
        ready_timeout=1.0,
        pasta_deathsig=False,
    )

    assert result.returncode == 1
    assert result.stderr == (
        "vscode-sandbox: error: the sandbox was not ready within 1.0 s; see "
        f"{tmp}/store/code.log\n"
    )
    assert (tmp / "bwrap-held").exists()
    wait_until_unlocked(tmp, (pid_of(tmp, "pasta"),))
    assert state_entries(tmp) == ["lock"]


def test_pasta_exit_kills_the_outer_stage(tmp, launch):
    result = launch(loop(tmp), pasta=ns_pasta(tmp), pasta_deathsig=False)
    assert result.returncode == 0, result.stderr
    pasta, init = outer_stage_of(tmp)

    os.kill(pasta, signal.SIGKILL)

    wait_until_unlocked(tmp, (pasta, init))
    assert state_entries(tmp) == ["lock"]


def test_guard_exits_when_pasta_exits(tmp, launch):
    go = tmp / "go"
    result = launch(("/bin/sh", "-c", f'while [ ! -e "{go}" ]; do sleep 0.05; done'))
    assert result.returncode == 0, result.stderr
    pasta, supervisor = pid_of(tmp, "pasta"), pid_of(tmp, "supervisor")
    guard = guard_of(tmp)

    # Stopped, the supervisor can neither signal nor reap the guard
    os.kill(supervisor, signal.SIGSTOP)
    try:
        go.touch()
        wait_for(lambda: gone(pasta) and gone(guard))
    finally:
        os.kill(supervisor, signal.SIGCONT)

    wait_for(lambda: gone(supervisor))
    assert not strays(tmp)
    assert state_entries(tmp) == ["lock"]


def test_guard_holds_only_stdio_the_lock_its_wakeup_pipe_and_sandbox_pidfds(
    tmp, launch
):
    result = launch(loop(tmp), pasta=ns_pasta(tmp), pasta_deathsig=False)
    assert result.returncode == 0, result.stderr
    pasta, init = outer_stage_of(tmp)
    guard = parent_of(pasta)
    log = str(tmp / "store" / "code.log")

    fds = sorted(int(fd) for fd in os.listdir(f"/proc/{guard}/fd"))
    targets = [os.readlink(f"/proc/{guard}/fd/{fd}") for fd in fds]

    assert fds[:3] == [0, 1, 2]
    assert targets[:3] == ["/dev/null", log, log]
    assert sorted(re.sub(r"\[\d+\]$", "", target) for target in targets[3:]) == sorted(
        [
            str(tmp / "state" / "lock"),
            "pipe:",
            "pipe:",
            "anon_inode:[pidfd]",
            "anon_inode:[pidfd]",
        ]
    )
    assert holds_pidfd_on(guard, pasta)
    assert holds_pidfd_on(guard, init)


def test_launch_aborts_when_the_supervisor_cannot_become_a_subreaper(tmp, launch):
    result = launch(subreaper=False)

    assert result.returncode == 1
    assert result.stderr == (
        "vscode-sandbox: error: cannot become a child subreaper: Invalid argument\n"
    )
    assert not (tmp / "pasta.pid").exists()
    assert state_entries(tmp) == ["lock"]


def stopped_early(tmp):
    """The launcher's error for a guard that exits before the sandbox is ready."""
    return (
        "vscode-sandbox: error: the sandbox stopped before it was ready (pasta's "
        f"output is not logged); see {tmp}/store/code.log\n"
    )


def assert_next_launch_succeeds(launch):
    result = launch()
    assert result.returncode == 0, result.stderr


def test_guard_death_before_pasta_starts_fails_the_launch(tmp, launch):
    launcher = launch(loop(tmp), gate_spawn="popen", wait=False)
    wait_for((tmp / "spawn-held").exists)
    (guard,) = children(pid_of(tmp, "supervisor"))

    os.kill(guard, signal.SIGKILL)
    _, stderr = launcher.communicate(timeout=30)

    assert launcher.returncode == 1
    assert stderr == stopped_early(tmp)
    assert not (tmp / "pasta.pid").exists()
    wait_until_unlocked(tmp, ())
    assert state_entries(tmp) == ["lock"]
    assert_next_launch_succeeds(launch)


def test_guard_death_before_the_outer_stage_exists_kills_pasta(tmp, launch):
    launcher = launch(
        loop(tmp),
        pasta=ns_pasta(tmp, before=hold(tmp, "pasta")),
        pasta_deathsig=False,
        wait=False,
    )
    wait_for((tmp / "pasta-held").exists)
    pasta = pid_of(tmp, "pasta")

    os.kill(parent_of(pasta), signal.SIGKILL)

    wait_until_unlocked(tmp, (pasta,))
    _, stderr = launcher.communicate(timeout=30)
    assert launcher.returncode == 1
    assert stderr == stopped_early(tmp)
    assert state_entries(tmp) == ["lock"]
    assert_next_launch_succeeds(launch)


def test_guard_death_with_the_outer_stage_not_yet_found_kills_it(tmp, launch):
    result = launch(
        loop(tmp), pasta=ns_pasta(tmp), pasta_deathsig=False, find_outer=False
    )
    assert result.returncode == 0, result.stderr
    pasta = pid_of(tmp, "pasta")
    init = ns_init_of(pasta)

    os.kill(parent_of(pasta), signal.SIGKILL)

    wait_until_unlocked(tmp, (pasta, init))
    assert state_entries(tmp) == ["lock"]
    assert_next_launch_succeeds(launch)


def test_guard_death_after_the_outer_stage_is_found_kills_it(tmp, launch):
    result = launch(loop(tmp), pasta=ns_pasta(tmp), pasta_deathsig=False)
    assert result.returncode == 0, result.stderr
    pasta, init = outer_stage_of(tmp)

    os.kill(parent_of(pasta), signal.SIGKILL)

    wait_until_unlocked(tmp, (pasta, init))
    assert state_entries(tmp) == ["lock"]
    assert_next_launch_succeeds(launch)


def test_guard_death_during_its_teardown_kills_what_remains(tmp, launch):
    result = launch(loop(tmp), pasta=ns_pasta(tmp), pasta_deathsig=False)
    assert result.returncode == 0, result.stderr
    pasta, init = outer_stage_of(tmp)
    guard = parent_of(pasta)
    # Stopped, pasta cannot reap the outer stage the guard has killed, so the guard
    # stays in its teardown, waiting for pasta
    os.kill(pasta, signal.SIGSTOP)
    os.kill(pid_of(tmp, "supervisor"), signal.SIGTERM)
    wait_for(lambda: gone(init))

    os.kill(guard, signal.SIGKILL)

    wait_until_unlocked(tmp, (pasta, init))
    assert state_entries(tmp) == ["lock"]
    assert_next_launch_succeeds(launch)


PREEXEC = (
    LOAD
    + """
import ctypes

parent = os.getppid() if sys.argv[2] == "match" else os.getppid() + 1
sandbox.die_with_parent(parent)
deathsig = ctypes.c_int()
assert ctypes.CDLL(None).prctl(2, ctypes.byref(deathsig)) == 0
print(deathsig.value)
"""
)


@pytest.mark.parametrize(
    ("parent", "status", "stdout"),
    [("mismatch", 1, ""), ("match", 0, f"{signal.SIGTERM.value}\n")],
)
def test_preexec_exits_unless_the_parent_matches(parent, status, stdout):
    result = subprocess.run(
        (sys.executable, "-c", PREEXEC, str(SCRIPT), parent),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == status, result.stderr
    assert result.stdout == stdout


@pytest.fixture
def steps(tmp, monkeypatch):
    """Record run_sandbox's steps in-process, with supervise replaced."""
    state = tmp / "state"
    state.mkdir(mode=0o700)
    host = sandbox.HostPaths(
        state_dir=state, store=mkdir(tmp / "store"), display=tmp / "wayland-1"
    )
    calls = []
    close_fds = []

    def record(name, result=None):
        def step(*args, **kwargs):
            calls.append(name)
            return result

        return step

    def wrap(name, function):
        def step(*args, **kwargs):
            calls.append(name)
            return function(*args, **kwargs)

        return step

    def create_security_context(display_path, socket_path):
        calls.append("security context")
        socket_path.touch()
        read_end, write_end = os.pipe()
        close_fds.append((read_end, write_end))
        return write_end

    monkeypatch.setattr(sandbox, "preflight", record("preflight", host))
    monkeypatch.setattr(sandbox, "acquire_lock", wrap("lock", sandbox.acquire_lock))
    monkeypatch.setattr(
        sandbox, "remove_launch_files", wrap("purge", sandbox.remove_launch_files)
    )
    monkeypatch.setattr(sandbox, "build_seccomp", record("seccomp"))
    monkeypatch.setattr(sandbox, "create_security_context", create_security_context)
    monkeypatch.setattr(sandbox, "audit_globals", record("audit"))
    monkeypatch.setattr(os, "mkfifo", wrap("fifo", os.mkfifo))
    monkeypatch.setattr(sandbox, "supervise", record("spawn", 0))
    config = sandbox.Config(home=tmp / "home", roots=(), ports=(), paths=())
    yield config, calls, close_fds
    for read_end, _ in close_fds:
        os.close(read_end)


def test_run_sandbox_steps_run_in_order(steps):
    config, calls, _ = steps

    assert sandbox.run_sandbox(config, ("/bin/true",), env={}, detach=False) == 0
    assert calls == [
        "preflight",
        "lock",
        "purge",
        "seccomp",
        "security context",
        "audit",
        "fifo",
        "spawn",
        "purge",
    ]


@pytest.mark.parametrize("failing", ["build_seccomp", "audit_globals"])
def test_failed_step_aborts_before_spawn_and_cleans_up(
    tmp, steps, monkeypatch, failing
):
    config, calls, close_fds = steps

    def fail(*args, **kwargs):
        raise sandbox.SandboxError("step failed")

    monkeypatch.setattr(sandbox, failing, fail)

    with pytest.raises(sandbox.SandboxError, match="step failed"):
        sandbox.run_sandbox(config, ("/bin/true",), env={}, detach=False)
    assert "spawn" not in calls
    assert state_entries(tmp) == ["lock"]
    assert all(hung_up(read_end) for read_end, _ in close_fds)
    assert len(close_fds) == (failing == "audit_globals")


# Launch shim


def test_code_shim_passes_arguments_unchanged(tmp_path):
    home = tmp_path / "home"
    (home / "bin").mkdir(parents=True)
    stub = home / "bin" / "vscode-sandbox"
    stub.write_text('#!/bin/sh\nprintf "%s\\0" "$@" > "$HOME/args"\n')
    stub.chmod(0o755)
    args = ["--port", "8888", "my project", "a  b", "", "*"]

    subprocess.run(
        [REPO_ROOT / "dotfiles" / "bin" / "code", *args],
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
        check=True,
        timeout=10,
    )

    assert (home / "args").read_bytes().split(b"\0")[:-1] == [
        arg.encode() for arg in args
    ]
