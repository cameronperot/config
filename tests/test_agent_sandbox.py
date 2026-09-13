"""
Tests for dotfiles/bin/agent-sandbox: path checks, resolution, argv and the CLI.

Dry-run tests assert the printed bwrap argv only.
"""

import ast
import errno
import importlib.util
import os
import pwd
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from dataclasses import replace
from importlib.machinery import SourceFileLoader
from itertools import pairwise
from pathlib import Path

import pytest
import test_c
from test_c import commit_repo, git

# Module attributes register these as fixtures of this module.
bare_layout = test_c.bare_layout
plain_repo = test_c.plain_repo

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "dotfiles" / "bin" / "agent-sandbox"


def load_script():
    """Import the executable without creating deployed bytecode files."""
    loader = SourceFileLoader("agent_sandbox", str(SCRIPT))
    spec = importlib.util.spec_from_loader("agent_sandbox", loader)
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


def runtime(
    home: Path, cwd: Path | None = None, env_extra: dict[str, str] | None = None
):
    """Build an explicit invoker context with an isolated environment."""
    return sandbox.Runtime(
        home=home,
        cwd=cwd or home,
        env={**base_env(home), **(env_extra or {})},
        uid=os.getuid(),
        gid=os.getgid(),
        user="tester",
    )


TIOCSTI = Path("/proc/sys/dev/tty/legacy_tiocsti")
TESTER_HOME = Path("/home/tester")
EXPECTED_AGENTS = ("pi", "omp", "opencode", "claude")
EXPECTED_DENY_PREFIXES = (
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/lib64",
    "/etc",
    "/opt",
    "/var",
    "/boot",
    "/root",
    "/srv",
    "/tmp",
    "/run",
    "/proc",
    "/sys",
    "/dev",
)
EXPECTED_HOME_RO_PATHS = (
    ".config/git/config",
    ".config/git/ignore",
    ".config/git/attributes",
    ".config/pip",
    ".config/pnpm",
    ".config/uv",
    ".local/bin",
    ".local/lib",
    ".local/share/claude",
    ".local/share/pnpm",
    ".local/share/uv",
)
EXPECTED_AGENT_STATE_DIRS = {
    "pi": (".agent", ".pi"),
    "omp": (".agent", ".omp"),
    "opencode": (
        ".agent",
        ".opencode",
        ".local/share/opencode",
        ".local/state/opencode",
        ".local/share/opentui",
    ),
    "claude": (".agent", ".claude", ".local/state/claude"),
}
EXPECTED_AGENT_RO_PATHS = {
    "pi": (
        ".agent/skills",
        ".agent/prompts",
        ".agent/rules",
        ".pi/agent/skills",
        ".pi/agent/prompts",
        ".pi/agent/settings.json",
        ".pi/agent/guard-rules.json",
        ".pi/agent/AGENTS.md",
        ".pi/agent/agents",
        ".pi/agent/extensions",
    ),
    "omp": (
        ".agent/skills",
        ".agent/prompts",
        ".agent/rules",
        ".omp/agent/skills",
        ".omp/agent/prompts",
        ".omp/agent/config.yml",
        ".omp/agent/AGENTS.md",
        ".omp/agent/extensions",
    ),
    "opencode": (
        ".agent/skills",
        ".agent/prompts",
        ".agent/rules",
        ".config/opencode",
    ),
    "claude": (
        ".agent/skills",
        ".agent/prompts",
        ".agent/rules",
        ".claude/settings.json",
        ".claude/skills",
        ".claude/rules",
        ".claude/agents",
        ".claude/commands",
    ),
}
EXPECTED_FORWARD_VARS = {
    "TERM": "xterm-256color",
    "COLORTERM": "truecolor",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "LC_CTYPE": "C.UTF-8",
    "LC_MESSAGES": "C.UTF-8",
    "LC_COLLATE": "C.UTF-8",
    "LC_NUMERIC": "C.UTF-8",
    "LC_TIME": "C.UTF-8",
    "TZ": "UTC",
    "http_proxy": "http://proxy.example",
    "https_proxy": "http://proxy.example",
    "no_proxy": "localhost",
    "HTTP_PROXY": "http://proxy.example",
    "HTTPS_PROXY": "http://proxy.example",
    "NO_PROXY": "localhost",
}
EXPECTED_API_KEY_VARS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENCODE_API_KEY",
    "GEMINI_API_KEY",
)
EXPECTED_FORWARD_PATH_VARS = (
    "TERMINFO",
    "SSL_CERT_FILE",
    "NODE_EXTRA_CA_CERTS",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
)
EXPECTED_SSH_PUBKEY_TYPES = (
    "ssh-ed25519",
    "ssh-rsa",
    "ecdsa-sha2-nistp256",
    "ecdsa-sha2-nistp384",
    "ecdsa-sha2-nistp521",
    "sk-ssh-ed25519@openssh.com",
    "sk-ecdsa-sha2-nistp256@openssh.com",
)
EXPECTED_PACKAGE_RC_FILES = (".npmrc", ".bunfig.toml")
EXPECTED_USERNS_POLICY = {"pi": "1", "omp": "1", "opencode": "1", "claude": "0"}
EXPECTED_INDEXED_POLICIES = (
    ("DENY_PREFIXES", EXPECTED_DENY_PREFIXES),
    ("HOME_RO_PATHS", EXPECTED_HOME_RO_PATHS),
    ("FORWARD_VARS", tuple(EXPECTED_FORWARD_VARS)),
    ("API_KEY_VARS", EXPECTED_API_KEY_VARS),
    ("FORWARD_PATH_VARS", EXPECTED_FORWARD_PATH_VARS),
    ("SSH_PUBKEY_TYPES", EXPECTED_SSH_PUBKEY_TYPES),
    ("PACKAGE_RC_FILES", EXPECTED_PACKAGE_RC_FILES),
)
EXPECTED_AGENT_STATE_CASES = tuple(
    (agent, relative_path)
    for agent, relative_paths in EXPECTED_AGENT_STATE_DIRS.items()
    for relative_path in relative_paths
)
EXPECTED_AGENT_RO_CASES = tuple(
    (agent, relative_path)
    for agent, relative_paths in EXPECTED_AGENT_RO_PATHS.items()
    for relative_path in relative_paths
)
EXPECTED_STATE_PIN_CASES = tuple(
    (agent, relative_path, relative_path.split("/", maxsplit=1)[0])
    for agent, relative_path in EXPECTED_AGENT_RO_CASES
    if relative_path != ".config/opencode"
)
EXPECTED_PINNED_JSON_CASES = tuple(
    (agent, relative_path)
    for agent, relative_path in EXPECTED_AGENT_RO_CASES
    if relative_path.endswith(".json")
)
EXPECTED_PINNED_DIRECTORY_CASES = tuple(
    (agent, relative_path)
    for agent, relative_path in EXPECTED_AGENT_RO_CASES
    if "." not in Path(relative_path).name
)
EXPECTED_PINNED_OTHER_FILE_CASES = tuple(
    (agent, relative_path)
    for agent, relative_path in EXPECTED_AGENT_RO_CASES
    if "." in Path(relative_path).name and not relative_path.endswith(".json")
)


def tiocsti_ok() -> bool:
    """
    Report whether ``check_tiocsti`` accepts this kernel.

    :return: True when the sysctl exists and reads ``0``.
    """
    return TIOCSTI.is_file() and TIOCSTI.read_text().strip() == "0"


needs_tiocsti = pytest.mark.skipif(
    not tiocsti_ok(),
    reason="check_tiocsti refuses this kernel before the argv is printed",
)


def base_env(home: Path) -> dict[str, str]:
    """
    Build the minimal environment the script runs under.

    Nothing else is inherited, so the developer shell's API keys, locale and
    ``AGENT_SANDBOX_ACTIVE`` cannot leak into a test.

    :param home: Fake ``$HOME``; the script reads its ``.gitconfig``.
    :return: The environment mapping.
    """
    return {"PATH": os.environ["PATH"], "HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1"}


def run_dry(
    home: Path, cwd: Path, agent: str = "pi", env_extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """
    Run ``agent-sandbox --dry-run <agent>`` with ``/bin/sh`` as the agent executable.

    :param home: Fake ``$HOME``.
    :param cwd: Working directory, inside a fixture repository.
    :param agent: Agent name.
    :param env_extra: Extra environment variables.
    :return: The completed process.
    """
    env = {**base_env(home), "AGENT_SANDBOX_BIN": "/bin/sh", **(env_extra or {})}
    return subprocess.run(
        [str(SCRIPT), "--dry-run", agent],
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def argv_of(proc: subprocess.CompletedProcess[str]) -> list[str]:
    """
    Split the shell-quoted argv a dry run prints.

    :param proc: The completed dry run.
    :return: The argv words.
    """
    assert proc.returncode == 0, proc.stderr
    return shlex.split(proc.stdout)


def seq_index(argv: list[str], *words: str) -> int | None:
    """
    Locate ``words`` as consecutive elements of ``argv``.

    :param argv: The argv words.
    :param words: The sequence to find.
    :return: Index of the first match, or None.
    """
    size = len(words)
    for i in range(len(argv) - size + 1):
        if tuple(argv[i : i + size]) == words:
            return i
    return None


def position(argv: list[str], *words: str) -> int:
    """
    Locate ``words`` in ``argv``, failing the test when absent.

    :param argv: The argv words.
    :param words: The sequence to find.
    :return: Index of the first match.
    """
    index = seq_index(argv, *words)
    assert index is not None, f"{words} not in argv"
    return index


def assert_ordered(argv: list[str], *sequences: tuple[str, ...]) -> None:
    """
    Assert that argument subsequences appear in the specified order.

    :param argv: The argv words.
    :param sequences: Consecutive argument groups in required order.
    """
    indices = [position(argv, *words) for words in sequences]
    assert all(left < right for left, right in pairwise(indices))


@pytest.mark.parametrize("flag", ("-h", "--help"))
def test_cli_help(home: Path, flag: str) -> None:
    proc = subprocess.run(
        [str(SCRIPT), flag], env=base_env(home), capture_output=True, text=True
    )

    assert proc.returncode == 0
    assert proc.stdout.startswith("Usage: agent-sandbox ")
    assert "Agents: pi, omp, opencode, claude" in proc.stdout
    assert proc.stderr == ""


def test_script_parses_with_python_312_syntax() -> None:
    tree = ast.parse(source=SCRIPT.read_text(), feature_version=(3, 12))

    assert isinstance(tree, ast.Module)


def test_cli_missing_home_reports_error_without_traceback() -> None:
    proc = subprocess.run(
        args=[str(SCRIPT), "pi"],
        env={"PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr == "agent-sandbox: error: HOME is unset\n"


def test_main_missing_passwd_entry_reports_error_without_traceback(
    home: Path, monkeypatch, capsys
) -> None:
    def missing_account(uid: int):
        raise KeyError(uid)

    monkeypatch.setenv(name="HOME", value=str(home))
    monkeypatch.setenv(name="LC_CTYPE", value=os.environ.get("LC_CTYPE", ""))
    monkeypatch.setattr(target=pwd, name="getpwuid", value=missing_account)

    result = sandbox.main(["pi"])

    assert result == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        f"agent-sandbox: error: no passwd entry for uid {os.getuid()}\n"
    )


@pytest.mark.parametrize(
    ("args", "message"),
    (
        ((), "missing <agent>"),
        (("",), "missing <agent>"),
        (("unknown",), "unknown agent: unknown"),
        (("--unknown",), "unknown flag: --unknown"),
    ),
)
def test_cli_argument_errors(home: Path, args: tuple[str, ...], message: str) -> None:
    proc = subprocess.run(
        [str(SCRIPT), *args], env=base_env(home), capture_output=True, text=True
    )

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "Usage: agent-sandbox " in proc.stderr
    assert f"agent-sandbox: error: {message}\n" in proc.stderr


@pytest.mark.parametrize("exists", (False, True))
def test_cli_override_requires_executable(home: Path, exists: bool) -> None:
    executable = home / "agent"
    if exists:
        executable.write_text("not executable\n")
    proc = subprocess.run(
        [str(SCRIPT), "pi"],
        env={**base_env(home), "AGENT_SANDBOX_BIN": str(executable)},
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 1
    assert proc.stderr == (
        "agent-sandbox: error: agent executable missing or not executable: "
        f"{executable}\n"
    )


@pytest.mark.parametrize("variable", ("AGENT_SANDBOX_DISABLE", "AGENT_SANDBOX_ACTIVE"))
@pytest.mark.parametrize("value", ("1", "0"))
def test_cli_direct_exec_preserves_arguments_and_exit_status(
    home: Path, variable: str, value: str
) -> None:
    args = ("", "two words", "a'b", "$(literal)", "--debug", "--dry-run", "-v")
    proc = subprocess.run(
        [
            str(SCRIPT),
            "--dry-run",
            "--",
            "pi",
            "-c",
            'printf "%s\\0" "$@"; exit 23',
            "agent",
            *args,
        ],
        env={**base_env(home), "AGENT_SANDBOX_BIN": "/bin/sh", variable: value},
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 23
    assert proc.stdout.split("\0") == [*args, ""]
    assert proc.stderr == ""
    assert list(home.iterdir()) == []


@needs_tiocsti
def test_cli_dry_run_preserves_agent_flags_and_warning_prefix(scratch: Path) -> None:
    home = scratch / "home"
    repo = make_repo(home / "project")
    args = (
        "",
        "two words",
        "a'b",
        "$(literal)",
        "--help",
        "--debug",
        "--dry-run",
        "-v",
    )
    proc = subprocess.run(
        [str(SCRIPT), "--dry-run", "pi", *args],
        env={**base_env(home), "AGENT_SANDBOX_BIN": "/bin/sh"},
        cwd=repo,
        capture_output=True,
        text=True,
    )

    assert argv_of(proc)[-len(args) - 1 :] == ["/bin/sh", *args]
    assert (
        proc.stderr
        == "agent-sandbox: warning: SSH_AUTH_SOCK unset: ssh-agent not forwarded\n"
    )


def make_repo(path: Path) -> Path:
    """
    Create ``path`` and turn it into a repository with one commit.

    :param path: Repository root to create.
    :return: The same path.
    """
    path.mkdir(parents=True)
    commit_repo(path)
    return path


# --- declared policy contracts


@pytest.mark.parametrize(("array_name", "expected"), EXPECTED_INDEXED_POLICIES)
def test_indexed_policy_array_matches_the_complete_expected_contract(
    home: Path, array_name: str, expected: tuple[str, ...]
) -> None:
    assert getattr(sandbox, array_name) == expected


@pytest.mark.parametrize(("agent", "expected"), EXPECTED_AGENT_STATE_DIRS.items())
def test_agent_state_policy_matches_the_complete_expected_contract(
    home: Path, agent: str, expected: tuple[str, ...]
) -> None:
    assert sandbox.POLICIES[agent].state_dirs == expected


@pytest.mark.parametrize(("agent", "expected"), EXPECTED_AGENT_RO_PATHS.items())
def test_agent_read_only_policy_matches_the_complete_expected_contract(
    home: Path, agent: str, expected: tuple[str, ...]
) -> None:
    assert sandbox.POLICIES[agent].ro_paths == expected


@pytest.mark.parametrize(("agent", "expected"), EXPECTED_USERNS_POLICY.items())
def test_agent_user_namespace_policy_matches_the_complete_expected_contract(
    home: Path, agent: str, expected: str
) -> None:
    assert sandbox.POLICIES[agent].disable_userns == (expected == "1")


def test_agent_executable_policy_names_every_supported_agent(home: Path) -> None:
    assert tuple(sandbox.POLICIES) == EXPECTED_AGENTS


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """
    An empty fake ``$HOME`` for function-level calls.

    :param tmp_path: Pytest temporary directory root.
    :return: The resolved directory.
    """
    path = tmp_path.resolve() / "home"
    path.mkdir()
    return path


@pytest.fixture
def scratch() -> Iterator[Path]:
    """
    A temporary directory inside the checkout's gitignored ``ignore/``.

    ``/tmp`` is a denied workspace prefix, so dry-run fixtures live here.

    :return: The resolved directory, removed on teardown.
    """
    ignore = REPO_ROOT / "ignore"
    ignore.mkdir(exist_ok=True)
    path = Path(tempfile.mkdtemp(dir=ignore)).resolve()
    yield path
    shutil.rmtree(path)


@pytest.fixture
def ssh_agent() -> Iterator[str]:
    """
    A throwaway ``ssh-agent`` holding no keys.

    :return: Its socket path, under a short ``/tmp`` directory.
    """
    directory = tempfile.mkdtemp(prefix="agt")
    sock = f"{directory}/s"
    proc = subprocess.Popen(
        ["ssh-agent", "-D", "-a", sock],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 5
    while not Path(sock).exists():
        if time.monotonic() > deadline:
            proc.terminate()
            raise RuntimeError("ssh-agent did not create its socket")
        time.sleep(0.05)
    yield sock
    proc.terminate()
    proc.wait()
    shutil.rmtree(directory)


# --- refuse_denied_path


@pytest.mark.parametrize(
    ("path", "message"),
    [
        ("/", "is /"),
        ("/home/tester", "is $HOME"),
        ("/home", "ancestor of $HOME"),
        ("/home/tester/.ssh", "hidden entry"),
        ("/home/tester/.config/x", "hidden entry"),
    ],
)
def test_refuse_denied_path_dies_with_the_matching_reason(
    path: str, message: str
) -> None:
    with pytest.raises(sandbox.SandboxError, match=re.escape(message)):
        sandbox.refuse_denied_path(
            path=Path(path), home=TESTER_HOME, label="workspace root"
        )


@pytest.mark.parametrize("path", ["/home/tester/proj", "/data/proj"])
def test_refuse_denied_path_accepts_ordinary_paths(path: str) -> None:
    assert (
        sandbox.refuse_denied_path(
            path=Path(path), home=TESTER_HOME, label="workspace root"
        )
        is None
    )


@pytest.mark.parametrize("prefix", EXPECTED_DENY_PREFIXES)
def test_refuse_denied_path_rejects_every_system_prefix(
    home: Path, prefix: str
) -> None:
    with pytest.raises(sandbox.SandboxError, match=f"at/under {prefix}"):
        sandbox.refuse_denied_path(
            path=Path(prefix) / "x", home=home, label="workspace root"
        )


# --- resolve_workspace


def resolved(home: Path, cwd: Path) -> tuple[str, str]:
    """Resolve the project and optional Git common directory using real Git."""
    result = sandbox.resolve_workspace(runtime(home=home, cwd=cwd))
    return str(result.root), str(
        result.common_dir
    ) if result.common_dir is not None else ""


def test_resolve_workspace_plain_repo_is_toplevel(home: Path, plain_repo: Path) -> None:
    assert resolved(home, plain_repo / "sub") == (str(plain_repo), "")


def test_resolve_workspace_linked_worktree_records_common_dir(
    home: Path, plain_repo: Path
) -> None:
    worktree = plain_repo.parent / "wt"
    git("-C", str(plain_repo), "worktree", "add", "-q", str(worktree), "-b", "wt")

    assert resolved(home, worktree) == (str(worktree), str(plain_repo / ".git"))


def test_resolve_workspace_bare_layout_worktree_maps_to_container(
    home: Path, bare_layout: Path
) -> None:
    assert resolved(home, bare_layout / "main" / "sub") == (str(bare_layout), "")


def test_resolve_workspace_bare_layout_container_is_itself(
    home: Path, bare_layout: Path
) -> None:
    assert resolved(home, bare_layout) == (str(bare_layout), "")


def test_resolve_workspace_outside_git_is_cwd(home: Path, tmp_path: Path) -> None:
    nogit = tmp_path.resolve() / "nogit"
    nogit.mkdir()

    assert resolved(home, nogit) == (str(nogit), "")


# --- print_redacted_argv


@pytest.mark.parametrize("variable", EXPECTED_API_KEY_VARS)
def test_print_redacted_argv_masks_every_api_key_value(
    home: Path, variable: str
) -> None:
    result = sandbox.redacted_argv(
        ("--setenv", variable, "secret", "--setenv", "HOME", "/x")
    )

    assert shlex.split(result) == [
        "--setenv",
        variable,
        "***",
        "--setenv",
        "HOME",
        "/x",
    ]
    assert "secret" not in result


# --- parse_args


def test_parse_args_splits_flags_agent_and_verbatim_args(home: Path) -> None:
    assert sandbox.parse_args(("-v", "pi", "--dry-run")) == sandbox.Options(
        agent="pi", agent_args=("--dry-run",), verbose=True
    )


def test_parse_args_rejects_unknown_flag(home: Path) -> None:
    with pytest.raises(sandbox.SandboxError, match="unknown flag"):
        sandbox.parse_args(("--bogus", "pi"))


def test_parse_args_requires_an_agent(home: Path) -> None:
    with pytest.raises(sandbox.SandboxError, match="missing <agent>"):
        sandbox.parse_args(())


# --- dry run


@needs_tiocsti
def test_dry_run_smoke_prints_the_sandbox_argv(scratch: Path) -> None:
    home = scratch / "home"
    repo = make_repo(home / "lsq" / "proj")

    proc = run_dry(home, repo)

    assert proc.returncode == 0, proc.stderr
    argv = argv_of(proc)
    assert argv[:2] == ["unshare", "--user"]
    assert "bwrap" in argv
    assert seq_index(argv, "--bind", str(repo), str(repo)) is not None
    assert seq_index(argv, "--chdir", str(repo)) is not None
    assert seq_index(argv, "--setenv", "AGENT_SANDBOX_ACTIVE", "1") is not None
    assert argv[-1] == "/bin/sh"


# --- check_home_canonical


@needs_tiocsti
def test_home_canonical_refuses_a_symlinked_home(scratch: Path) -> None:
    home = scratch / "home"
    repo = make_repo(home / "lsq" / "proj")
    link = scratch / "link"
    link.symlink_to(home)

    proc = run_dry(link, repo)

    assert proc.returncode == 1
    assert "HOME is not canonical" in proc.stderr


# --- resolve_workspace without a work tree


def test_resolve_workspace_without_work_tree_dies_inside_git_dir(
    home: Path, plain_repo: Path
) -> None:
    hooks = plain_repo / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)

    with pytest.raises(sandbox.SandboxError, match="without a work tree"):
        sandbox.resolve_workspace(runtime(home=home, cwd=hooks))


def test_resolve_workspace_inside_bare_dir_maps_to_container(
    home: Path, bare_layout: Path
) -> None:
    hooks = bare_layout / ".bare" / "hooks"
    hooks.mkdir(exist_ok=True)

    assert resolved(home, hooks) == (str(bare_layout), "")


def test_resolve_workspace_dies_when_cwd_is_outside_the_workspace(
    home: Path, bare_layout: Path
) -> None:
    with pytest.raises(sandbox.SandboxError, match="outside the workspace"):
        sandbox.resolve_workspace(
            runtime(home=home, cwd=bare_layout.parent / "outside")
        )


# --- add_workspace_args parent chain


@needs_tiocsti
def test_parent_chain_under_home_is_tmpfs_remounted_read_only(scratch: Path) -> None:
    home = scratch / "home"
    repo = make_repo(home / "lsq" / "proj")
    lsq = str(home / "lsq")

    argv = argv_of(run_dry(home, repo))

    assert_ordered(
        argv, ("--tmpfs", lsq), ("--bind", str(repo), str(repo)), ("--remount-ro", lsq)
    )
    assert seq_index(argv, "--dir", lsq) is None


@needs_tiocsti
def test_parent_chain_home_ancestors_are_tmpfs_before_the_home_tmpfs(
    scratch: Path,
) -> None:
    home = scratch / "home" / "user"
    home.mkdir(parents=True)
    repo = make_repo(scratch / "home" / "cameron" / "proj")
    ancestor = str(scratch / "home")
    sibling = str(scratch / "home" / "cameron")

    argv = argv_of(run_dry(home, repo))

    ancestor_tmpfs = position(argv, "--tmpfs", ancestor)
    home_tmpfs = position(argv, "--perms", "0700", "--tmpfs", str(home))
    sibling_tmpfs = position(argv, "--tmpfs", sibling)
    bind = position(argv, "--bind", str(repo), str(repo))
    assert ancestor_tmpfs < home_tmpfs < sibling_tmpfs < bind
    assert bind < position(argv, "--remount-ro", ancestor)
    assert bind < position(argv, "--remount-ro", sibling)
    assert seq_index(argv, "--dir", ancestor) is None


@needs_tiocsti
def test_parent_chain_remounts_are_the_last_mount_ops(scratch: Path) -> None:
    home = scratch / "home"
    repo = make_repo(home / "lsq" / "proj")

    argv = argv_of(run_dry(home, repo))

    remounts = [i for i, word in enumerate(argv) if word == "--remount-ro"]
    assert remounts
    assert argv.index("--chdir") == remounts[-1] + 2


# --- add_home_args allowlist


@pytest.mark.parametrize("relative_path", EXPECTED_HOME_RO_PATHS)
@needs_tiocsti
def test_allowlist_binds_every_shared_read_only_home_path(
    scratch: Path, relative_path: str
) -> None:
    home = scratch / "home"
    repo = make_repo(home / "lsq" / "proj")

    argv = argv_of(run_dry(home, repo))

    path = str(home / relative_path)
    assert seq_index(argv, "--ro-bind-try", path, path) is not None


@pytest.mark.parametrize("relative_path", [".config", ".local"])
@needs_tiocsti
def test_allowlist_does_not_bind_whole_shared_home_directories(
    scratch: Path, relative_path: str
) -> None:
    home = scratch / "home"
    repo = make_repo(home / "lsq" / "proj")

    argv = argv_of(run_dry(home, repo))

    path = str(home / relative_path)
    assert seq_index(argv, "--ro-bind", path, path) is None


@pytest.mark.parametrize(("agent", "relative_path"), EXPECTED_AGENT_STATE_CASES)
@needs_tiocsti
def test_allowlist_binds_every_agent_state_directory_read_write(
    scratch: Path, agent: str, relative_path: str
) -> None:
    home = scratch / "home"
    repo = make_repo(home / "lsq" / "proj")

    argv = argv_of(run_dry(home, repo, agent=agent))

    path = str(home / relative_path)
    assert seq_index(argv, "--bind", path, path) is not None


@pytest.mark.parametrize(
    ("agent", "relative_path", "state_path"), EXPECTED_STATE_PIN_CASES
)
@needs_tiocsti
def test_allowlist_places_every_state_pin_after_its_writable_bind(
    scratch: Path, agent: str, relative_path: str, state_path: str
) -> None:
    home = scratch / "home"
    repo = make_repo(home / "lsq" / "proj")

    argv = argv_of(run_dry(home, repo, agent=agent))

    state = str(home / state_path)
    path = str(home / relative_path)
    assert position(argv, "--bind", state, state) < position(
        argv, "--ro-bind-try", path, path
    )


@needs_tiocsti
def test_opencode_config_is_read_only_not_writable(scratch: Path) -> None:
    home = scratch / "home"
    repo = make_repo(home / "lsq" / "proj")
    config = str(home / ".config" / "opencode")

    argv = argv_of(run_dry(home, repo, agent="opencode"))

    assert seq_index(argv, "--ro-bind-try", config, config) is not None
    assert seq_index(argv, "--bind", config, config) is None


# --- resolve_npmrc


@needs_tiocsti
def test_npmrc_with_credentials_is_not_bound(scratch: Path) -> None:
    home = scratch / "home"
    repo = make_repo(home / "lsq" / "proj")
    (home / ".npmrc").write_text("//registry.npmjs.org/:_authToken=x\n")

    proc = run_dry(home, repo)

    assert proc.returncode == 0, proc.stderr
    assert str(home / ".npmrc") not in argv_of(proc)
    assert "contains credentials: not bound" in proc.stderr


@needs_tiocsti
def test_npmrc_without_credentials_is_bound(scratch: Path) -> None:
    home = scratch / "home"
    repo = make_repo(home / "lsq" / "proj")
    (home / ".npmrc").write_text("ignore-scripts=true\n")
    npmrc = str(home / ".npmrc")

    argv = argv_of(run_dry(home, repo))

    assert seq_index(argv, "--ro-bind-try", npmrc, npmrc) is not None


# --- check_exe_visible


@needs_tiocsti
def test_exe_visible_refuses_an_executable_the_sandbox_does_not_expose(
    scratch: Path,
) -> None:
    home = scratch / "home"
    repo = make_repo(home / "lsq" / "proj")
    hidden_sh = scratch / "sh"
    shutil.copy("/bin/sh", hidden_sh)
    hidden_sh.chmod(0o755)

    proc = run_dry(home, repo, env_extra={"AGENT_SANDBOX_BIN": str(hidden_sh)})

    assert proc.returncode == 1
    assert "does not expose" in proc.stderr


@needs_tiocsti
def test_exe_visible_accepts_a_system_executable(scratch: Path) -> None:
    home = scratch / "home"
    repo = make_repo(home / "lsq" / "proj")

    proc = run_dry(home, repo)

    assert proc.returncode == 0, proc.stderr


# --- resolve_signing_key


def keygen(directory: Path, name: str) -> str:
    """
    Generate an ed25519 key pair.

    :param directory: Directory for ``name`` and ``name.pub``.
    :param name: Key file name.
    :return: The public key's type and blob, space-separated.
    """
    directory.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(directory / name)],
        check=True,
        capture_output=True,
    )
    return " ".join((directory / f"{name}.pub").read_text().split()[:2])


def write_gitconfig(home: Path, signingkey: str, gpg_format: str = "ssh") -> None:
    """
    Write a ``.gitconfig`` selecting a signing key.

    :param home: Fake ``$HOME``.
    :param signingkey: Value for ``user.signingkey``.
    :param gpg_format: Value for ``gpg.format``.
    """
    (home / ".gitconfig").write_text(
        f"[gpg]\n\tformat = {gpg_format}\n[user]\n\tsigningkey = {signingkey}\n"
    )


def signing(home: Path):
    """Resolve global signing configuration using real Git."""
    return sandbox.resolve_signing_key(runtime(home))


@pytest.mark.parametrize("key_type", EXPECTED_SSH_PUBKEY_TYPES)
def test_signing_key_file_accepts_every_recognized_public_key_type(
    home: Path, key_type: str
) -> None:
    (home / ".ssh").mkdir()
    pubkey = f"{key_type} fixture"
    (home / ".ssh" / "k.pub").write_text(f"{pubkey}\n")
    write_gitconfig(home, "~/.ssh/k.pub")

    result = signing(home)

    assert result == sandbox.Signing(key_file=home / ".ssh/k.pub", pubkey=pubkey)


def test_signing_key_private_key_path_is_not_exposed(home: Path, capsys) -> None:
    keygen(home / ".ssh", "k")
    write_gitconfig(home, "~/.ssh/k")

    result = signing(home)

    assert result == sandbox.Signing()
    assert "not a public key file" in capsys.readouterr().err


def test_signing_key_literal_with_comment_sets_only_the_pubkey(home: Path) -> None:
    pubkey = keygen(home / ".ssh", "k")
    write_gitconfig(home, f"{pubkey} c")

    result = signing(home)

    assert result == sandbox.Signing(pubkey=pubkey)


def test_signing_key_key_prefixed_literal_sets_only_the_pubkey(home: Path) -> None:
    pubkey = keygen(home / ".ssh", "k")
    write_gitconfig(home, f"key::{pubkey}")

    result = signing(home)

    assert result == sandbox.Signing(pubkey=pubkey)


def test_signing_key_is_ignored_unless_gpg_format_is_ssh(home: Path) -> None:
    keygen(home / ".ssh", "k")
    write_gitconfig(home, "~/.ssh/k.pub", gpg_format="openpgp")

    result = signing(home)

    assert result == sandbox.Signing()


# --- resolve_ssh_sock


def ssh_add(sock: str, key: Path) -> None:
    """
    Load a private key into an agent.

    :param sock: Agent socket path.
    :param key: Private key file.
    """
    subprocess.run(
        ["ssh-add", str(key)],
        check=True,
        env={**os.environ, "SSH_AUTH_SOCK": sock},
        capture_output=True,
    )


def resolved_ssh_sock(home: Path, sock: str) -> Path | None:
    """Resolve an owned socket against the global signing configuration."""
    context = runtime(home=home, env_extra={"SSH_AUTH_SOCK": sock})
    return sandbox.resolve_ssh_sock(
        runtime=context, signing=sandbox.resolve_signing_key(context)
    )


def test_ssh_sock_is_forwarded_when_the_agent_holds_exactly_the_signing_key(
    home: Path, ssh_agent: str
) -> None:
    keygen(home / ".ssh", "k1")
    write_gitconfig(home, "~/.ssh/k1.pub")
    ssh_add(ssh_agent, home / ".ssh" / "k1")

    result = resolved_ssh_sock(home, ssh_agent)

    assert result == Path(ssh_agent).resolve()


def test_ssh_sock_is_not_forwarded_when_the_agent_holds_extra_keys(
    home: Path, ssh_agent: str, capsys
) -> None:
    keygen(home / ".ssh", "k1")
    keygen(home / ".ssh", "k2")
    write_gitconfig(home, "~/.ssh/k1.pub")
    ssh_add(ssh_agent, home / ".ssh" / "k1")
    ssh_add(ssh_agent, home / ".ssh" / "k2")

    result = resolved_ssh_sock(home, ssh_agent)

    assert result is None
    assert "must hold exactly the signing key" in capsys.readouterr().err


def test_ssh_sock_is_not_forwarded_when_the_agent_holds_a_different_key(
    home: Path, ssh_agent: str
) -> None:
    keygen(home / ".ssh", "k1")
    keygen(home / ".ssh", "k2")
    write_gitconfig(home, "~/.ssh/k1.pub")
    ssh_add(ssh_agent, home / ".ssh" / "k2")

    result = resolved_ssh_sock(home, ssh_agent)

    assert result is None


def test_ssh_sock_is_not_forwarded_without_a_signing_key(
    home: Path, ssh_agent: str, capsys
) -> None:
    keygen(home / ".ssh", "k1")
    ssh_add(ssh_agent, home / ".ssh" / "k1")

    result = resolved_ssh_sock(home, ssh_agent)

    assert result is None
    assert "no ssh signing key configured" in capsys.readouterr().err


# --- add_env_args forwarding

CA_BUNDLE = Path("/etc/ssl/certs/ca-certificates.crt")


@pytest.mark.parametrize(
    ("env_extra", "expected"),
    (({}, "dumb"), ({"TERM": ""}, None), ({"TERM": "xterm"}, "xterm")),
    ids=("unset", "empty", "nonempty"),
)
@needs_tiocsti
def test_cli_term_default_and_forwarding(
    scratch: Path, env_extra: dict[str, str], expected: str | None
) -> None:
    home = scratch / "home"
    repo = make_repo(home / "project")

    argv = argv_of(run_dry(home=home, cwd=repo, env_extra=env_extra))

    values = {
        argv[index + 1]: argv[index + 2]
        for index, word in enumerate(argv)
        if word == "--setenv"
    }
    assert values.get("TERM") == expected


@pytest.mark.parametrize(("variable", "value"), EXPECTED_FORWARD_VARS.items())
@needs_tiocsti
def test_forward_vars_pass_every_nonempty_allowlisted_value(
    scratch: Path, variable: str, value: str
) -> None:
    home = scratch / "home"
    repo = make_repo(home / "lsq" / "proj")

    argv = argv_of(run_dry(home, repo, env_extra={variable: value}))

    assert seq_index(argv, "--setenv", variable, value) is not None


@pytest.mark.parametrize("variable", EXPECTED_FORWARD_VARS)
@needs_tiocsti
def test_forward_vars_omit_every_empty_allowlisted_value(
    scratch: Path, variable: str
) -> None:
    home = scratch / "home"
    repo = make_repo(home / "lsq" / "proj")

    argv = argv_of(run_dry(home, repo, env_extra={variable: ""}))

    assert seq_index(argv, "--setenv", variable) is None


@pytest.mark.parametrize("variable", EXPECTED_API_KEY_VARS)
@needs_tiocsti
def test_api_key_vars_forward_and_redact_every_allowlisted_key(
    scratch: Path, variable: str
) -> None:
    home = scratch / "home"
    repo = make_repo(home / "lsq" / "proj")

    proc = run_dry(home, repo, env_extra={variable: "fixture-secret"})

    assert proc.returncode == 0, proc.stderr
    assert seq_index(argv_of(proc), "--setenv", variable, "***") is not None
    assert "fixture-secret" not in proc.stdout + proc.stderr


@pytest.mark.skipif(not CA_BUNDLE.is_file(), reason="no system CA bundle on this host")
@needs_tiocsti
def test_forward_path_vars_pass_a_file_the_sandbox_exposes(scratch: Path) -> None:
    home = scratch / "home"
    repo = make_repo(home / "lsq" / "proj")

    argv = argv_of(run_dry(home, repo, env_extra={"SSL_CERT_FILE": str(CA_BUNDLE)}))

    assert seq_index(argv, "--setenv", "SSL_CERT_FILE", str(CA_BUNDLE)) is not None


@pytest.mark.parametrize("variable", EXPECTED_FORWARD_PATH_VARS)
def test_forward_path_vars_forward_canonical_symlink_target(
    home: Path, variable: str
) -> None:
    workspace = home / "workspace"
    workspace.mkdir()
    target = workspace / "cert.pem"
    target.write_text("fixture CA bundle\n")
    link = home / "custom-ca.pem"
    link.symlink_to(target)

    result = sandbox.resolve_forwarded_env(
        runtime=runtime(home=home, env_extra={variable: str(link)}),
        workspace=sandbox.Workspace(root=workspace),
        policy=sandbox.POLICIES["pi"],
    )

    assert result == (("TERM", "dumb"), (variable, str(target)))


@pytest.mark.parametrize(
    ("target_name", "warning"),
    [
        ("private-ca.pem", "points outside the sandbox"),
        ("missing.pem", "does not exist"),
    ],
    ids=["unexposed-target", "dangling-symlink"],
)
def test_forward_path_vars_drop_symlink_to_unavailable_target(
    home: Path, target_name: str, warning: str, capsys
) -> None:
    (home / "private-ca.pem").write_text("fixture CA bundle\n")
    link = home / "custom-ca.pem"
    link.symlink_to(home / target_name)

    result = sandbox.resolve_forwarded_env(
        runtime=runtime(home=home, env_extra={"SSL_CERT_FILE": str(link)}),
        workspace=sandbox.Workspace(root=home / "workspace"),
        policy=sandbox.POLICIES["pi"],
    )

    assert result == (("TERM", "dumb"),)
    assert warning in capsys.readouterr().err


@needs_tiocsti
def test_forward_path_vars_drop_a_file_outside_the_sandbox(scratch: Path) -> None:
    home = scratch / "home"
    repo = make_repo(home / "lsq" / "proj")
    ca = scratch / "ca.pem"
    ca.write_text("")

    proc = run_dry(home, repo, env_extra={"NODE_EXTRA_CA_CERTS": str(ca)})

    assert proc.returncode == 0, proc.stderr
    assert seq_index(argv_of(proc), "--setenv", "NODE_EXTRA_CA_CERTS") is None
    assert "points outside the sandbox" in proc.stderr


# --- print_redacted_argv membership


def test_print_redacted_argv_does_not_mask_an_unlisted_variable(home: Path) -> None:
    assert shlex.split(sandbox.redacted_argv(("--setenv", "FOO_API_KEY", "y"))) == [
        "--setenv",
        "FOO_API_KEY",
        "y",
    ]


# --- add_system_args resolv.conf


@needs_tiocsti
def test_resolv_conf_target_under_run_is_bound(scratch: Path) -> None:
    try:
        target = str(Path("/etc/resolv.conf").resolve(strict=True))
    except OSError:
        target = ""
    if not target.startswith("/run/"):
        pytest.skip("resolv.conf not under /run")
    home = scratch / "home"
    repo = make_repo(home / "lsq" / "proj")

    argv = argv_of(run_dry(home, repo))

    assert seq_index(argv, "--ro-bind-try", target, target) is not None


# --- parse_args separator and empty agent


def test_parse_args_double_dash_ends_the_script_flags(home: Path) -> None:
    assert sandbox.parse_args(("--", "pi", "-v")) == sandbox.Options(
        agent="pi", agent_args=("-v",)
    )


def test_parse_args_empty_agent_word_is_a_missing_agent(home: Path) -> None:
    with pytest.raises(sandbox.SandboxError, match="missing <agent>"):
        sandbox.parse_args(("",))


# --- ensure_state_dirs seeding


@pytest.mark.parametrize(("agent", "relative_path"), EXPECTED_PINNED_JSON_CASES)
def test_ensure_state_dirs_seeds_every_absent_pinned_json_file(
    home: Path, agent: str, relative_path: str
) -> None:
    sandbox.ensure_state_dirs(runtime=runtime(home), agent=agent)
    assert (home / relative_path).read_text() == "{}\n"


@pytest.mark.parametrize(("agent", "relative_path"), EXPECTED_PINNED_DIRECTORY_CASES)
def test_ensure_state_dirs_seeds_every_absent_pinned_directory(
    home: Path, agent: str, relative_path: str
) -> None:
    sandbox.ensure_state_dirs(runtime=runtime(home), agent=agent)
    assert (home / relative_path).is_dir()


@pytest.mark.parametrize(("agent", "relative_path"), EXPECTED_PINNED_JSON_CASES)
def test_ensure_state_dirs_keeps_every_existing_pinned_json_file(
    home: Path, agent: str, relative_path: str
) -> None:
    path = home / relative_path
    path.parent.mkdir(parents=True)
    path.write_text('{"hooks": {}}\n')

    sandbox.ensure_state_dirs(runtime=runtime(home), agent=agent)
    assert path.read_text() == '{"hooks": {}}\n'


@pytest.mark.parametrize(("agent", "relative_path"), EXPECTED_PINNED_OTHER_FILE_CASES)
def test_ensure_state_dirs_does_not_seed_any_non_json_file(
    home: Path, agent: str, relative_path: str
) -> None:
    sandbox.ensure_state_dirs(runtime=runtime(home), agent=agent)
    assert not (home / relative_path).exists()


# --- resolve_package_rc bunfig


@needs_tiocsti
def test_bunfig_without_credentials_is_bound(scratch: Path) -> None:
    home = scratch / "home"
    repo = make_repo(home / "lsq" / "proj")
    (home / ".bunfig.toml").write_text("[install]\nminimumReleaseAge = 1728000\n")
    bunfig = str(home / ".bunfig.toml")

    argv = argv_of(run_dry(home, repo))

    assert seq_index(argv, "--ro-bind-try", bunfig, bunfig) is not None


@needs_tiocsti
def test_bunfig_with_a_token_is_not_bound(scratch: Path) -> None:
    home = scratch / "home"
    repo = make_repo(home / "lsq" / "proj")
    (home / ".bunfig.toml").write_text('[install.scopes]\nacme = { token = "x" }\n')

    proc = run_dry(home, repo)

    assert proc.returncode == 0, proc.stderr
    assert str(home / ".bunfig.toml") not in argv_of(proc)
    assert "contains credentials: not bound" in proc.stderr


# --- allowlist .config/git


@needs_tiocsti
def test_allowlist_exposes_git_config_by_file_not_directory(scratch: Path) -> None:
    home = scratch / "home"
    repo = make_repo(home / "lsq" / "proj")
    git_dir = str(home / ".config" / "git")
    git_config = str(home / ".config" / "git" / "config")

    argv = argv_of(run_dry(home, repo))

    assert seq_index(argv, "--ro-bind-try", git_config, git_config) is not None
    assert seq_index(argv, "--ro-bind-try", git_dir, git_dir) is None


# --- workspace visibility


@needs_tiocsti
def test_exe_visible_accepts_an_executable_inside_the_workspace(scratch: Path) -> None:
    home = scratch / "home"
    repo = make_repo(home / "lsq" / "proj")
    (repo / "dist").mkdir()
    workspace_sh = repo / "dist" / "sh"
    shutil.copy("/bin/sh", workspace_sh)
    workspace_sh.chmod(0o755)

    proc = run_dry(home, repo, env_extra={"AGENT_SANDBOX_BIN": str(workspace_sh)})

    assert proc.returncode == 0, proc.stderr
    assert argv_of(proc)[-1] == str(workspace_sh)


@needs_tiocsti
def test_forward_path_vars_pass_a_file_inside_the_workspace(scratch: Path) -> None:
    home = scratch / "home"
    repo = make_repo(home / "lsq" / "proj")
    ca = repo / "ca.pem"
    ca.write_text("")

    proc = run_dry(home, repo, env_extra={"NODE_EXTRA_CA_CERTS": str(ca)})

    assert proc.returncode == 0, proc.stderr
    assert (
        seq_index(argv_of(proc), "--setenv", "NODE_EXTRA_CA_CERTS", str(ca)) is not None
    )


@needs_tiocsti
def test_forward_path_vars_warn_when_the_file_does_not_exist(scratch: Path) -> None:
    home = scratch / "home"
    repo = make_repo(home / "lsq" / "proj")

    proc = run_dry(
        home, repo, env_extra={"NODE_EXTRA_CA_CERTS": str(scratch / "missing.pem")}
    )

    assert proc.returncode == 0, proc.stderr
    assert seq_index(argv_of(proc), "--setenv", "NODE_EXTRA_CA_CERTS") is None
    assert "does not exist" in proc.stderr
    assert "points outside" not in proc.stderr


# --- resolve_ssh_sock robustness


@needs_tiocsti
def test_ssh_sock_stalled_identity_probe_continues_without_forwarding(
    scratch: Path,
) -> None:
    home = scratch / "home"
    repo = make_repo(home / "project")
    write_gitconfig(home, "key::ssh-ed25519 fixture")
    with tempfile.TemporaryDirectory(prefix="agt") as directory:
        sock = str(Path(directory) / "s")
        env = {**base_env(home), "SSH_AUTH_SOCK": sock, "AGENT_SANDBOX_BIN": "/bin/sh"}
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(sock)
            server.listen(1)
            server.settimeout(5)
            with subprocess.Popen(
                [str(SCRIPT), "--dry-run", "pi"],
                env=env,
                cwd=repo,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ) as proc:
                try:
                    connection, _ = server.accept()
                    with connection:
                        connection.settimeout(5)
                        assert connection.recv(5) != b""
                        stdout, stderr = proc.communicate(timeout=6)
                finally:
                    proc.kill()
                    proc.communicate(timeout=5)

    assert proc.returncode == 0, stderr
    assert "not forwarded" in stderr
    assert "SSH_AUTH_SOCK" not in shlex.split(stdout)
    assert sock not in shlex.split(stdout)
    assert (
        seq_index(shlex.split(stdout), "--setenv", "AGENT_SANDBOX_ACTIVE", "1")
        is not None
    )


def test_ssh_sock_is_not_forwarded_when_ssh_add_cannot_run(
    home: Path, ssh_agent: str, monkeypatch, capsys
) -> None:
    write_gitconfig(home, "key::ssh-ed25519 fixture")
    context = runtime(home=home, env_extra={"SSH_AUTH_SOCK": ssh_agent})
    selected = sandbox.resolve_signing_key(context)

    def missing_executable(*args, **kwargs):
        raise FileNotFoundError("ssh-add")

    monkeypatch.setattr(subprocess, "Popen", missing_executable)
    result = sandbox.resolve_ssh_sock(runtime=context, signing=selected)

    assert result is None
    assert "not forwarded" in capsys.readouterr().err


def test_ssh_sock_is_not_forwarded_when_ssh_add_prints_nothing(
    home: Path, ssh_agent: str, capsys
) -> None:
    result = sandbox.resolve_ssh_sock(
        runtime=runtime(home=home, env_extra={"SSH_AUTH_SOCK": ssh_agent}),
        signing=sandbox.Signing(pubkey="ssh-ed25519 fixture"),
        probe=lambda **kwargs: "",
    )

    assert result is None
    assert "must hold exactly the signing key" in capsys.readouterr().err


# --- signing key bind ordering


@needs_tiocsti
def test_signing_key_bind_follows_the_workspace_parent_tmpfs(scratch: Path) -> None:
    home = scratch / "home" / "user"
    home.mkdir(parents=True)
    repo = make_repo(scratch / "home" / "cameron" / "proj")
    keygen(scratch / "home" / "cameron" / "keys", "k")
    key = str(scratch / "home" / "cameron" / "keys" / "k.pub")
    write_gitconfig(home, key)

    argv = argv_of(run_dry(home, repo))

    assert_ordered(
        argv,
        ("--tmpfs", str(scratch / "home" / "cameron")),
        ("--ro-bind-try", key, key),
        ("--remount-ro",),
    )


# --- ensure_state_dirs pinned-path canonicalization


def test_ensure_state_dirs_dies_when_a_pinned_path_escapes_the_state_dirs(
    home: Path,
) -> None:
    (home / ".ssh").mkdir()
    (home / ".ssh" / "id").write_text("secret\n")
    (home / ".pi" / "agent").mkdir(parents=True)
    (home / ".pi" / "agent" / "settings.json").symlink_to(home / ".ssh" / "id")

    with pytest.raises(
        sandbox.SandboxError, match="resolves outside the agent's state dirs"
    ):
        sandbox.ensure_state_dirs(runtime=runtime(home), agent="pi")


def test_ensure_state_dirs_dies_on_a_dangling_pinned_link(home: Path) -> None:
    (home / ".pi" / "agent").mkdir(parents=True)
    (home / ".pi" / "agent" / "settings.json").symlink_to(home / "nowhere")

    with pytest.raises(
        sandbox.SandboxError, match="resolves outside the agent's state dirs"
    ):
        sandbox.ensure_state_dirs(runtime=runtime(home), agent="pi")


@pytest.mark.parametrize(
    ("agent", "entry"),
    tuple((agent, entry) for agent in ("pi", "omp") for entry in ("skills", "prompts")),
)
def test_ensure_state_dirs_accepts_every_supported_link_into_the_shared_agent_dir(
    home: Path, agent: str, entry: str
) -> None:
    target = home / ".agent" / entry
    target.mkdir(parents=True)
    link = home / f".{agent}" / "agent" / entry
    link.parent.mkdir(parents=True)
    link.symlink_to(target)

    sandbox.ensure_state_dirs(runtime=runtime(home), agent=agent)
    assert link.is_symlink()


# --- signing key file content


def test_signing_key_file_with_extra_content_is_not_exposed(home: Path, capsys) -> None:
    pubkey = keygen(home / ".ssh", "k")
    key_file = home / ".ssh" / "k.pub"
    key_file.write_text(f"{pubkey} c\n-----BEGIN OPENSSH PRIVATE KEY-----\n")
    write_gitconfig(home, "~/.ssh/k.pub")

    result = signing(home)

    assert result == sandbox.Signing()
    assert "not a public key file" in capsys.readouterr().err


# --- registry URL credentials


@needs_tiocsti
def test_bunfig_with_registry_url_credentials_is_not_bound(scratch: Path) -> None:
    home = scratch / "home"
    repo = make_repo(home / "lsq" / "proj")
    (home / ".bunfig.toml").write_text(
        '[install]\nregistry = "https://alice:s3cr3t@registry.example.com/"\n'
    )

    proc = run_dry(home, repo)

    assert proc.returncode == 0, proc.stderr
    assert str(home / ".bunfig.toml") not in argv_of(proc)
    assert "contains credentials: not bound" in proc.stderr


@needs_tiocsti
def test_npmrc_scoped_registry_line_is_bound(scratch: Path) -> None:
    home = scratch / "home"
    repo = make_repo(home / "lsq" / "proj")
    (home / ".npmrc").write_text("@acme:registry=https://registry.example.com/@acme/\n")
    npmrc = str(home / ".npmrc")

    argv = argv_of(run_dry(home, repo))

    assert seq_index(argv, "--ro-bind-try", npmrc, npmrc) is not None


@pytest.mark.parametrize(
    "content",
    [
        '[install.scopes]\nacme = { username = "build#bot", password = "secret" }',
        '[install.scopes]\nacme = { url = "https://host/;", token = "secret" }',
        '[install.scopes]\nacme = { password = """multi\nline""" }',
        "[install.scopes]\nacme = { 'token' = 'secret' }",
    ],
    ids=[
        "quoted-hash",
        "quoted-semicolon",
        "multiline",
        "literal-string",
    ],
)
def test_package_rc_rejects_plaintext_toml_credentials(
    home: Path, content: str, capsys
) -> None:
    (home / ".bunfig.toml").write_text(content)

    result = sandbox.resolve_package_rc(runtime(home))

    assert result == ()
    stderr = capsys.readouterr().err
    assert "contains credentials: not bound" in stderr
    assert "secret" not in stderr


@pytest.mark.parametrize("filename", EXPECTED_PACKAGE_RC_FILES)
def test_package_rc_inspection_failure_omits_the_file(
    home: Path, filename: str, monkeypatch, capsys
) -> None:
    (home / filename).write_text("safe = true\n")

    def unreadable(*args, **kwargs):
        raise PermissionError("fixture read error")

    monkeypatch.setattr(Path, "open", unreadable)
    result = sandbox.resolve_package_rc(runtime(home))

    assert result == ()
    assert "cannot inspect" in capsys.readouterr().err


@pytest.mark.parametrize(
    "content",
    [
        'registry="https://build#bot:secret@registry.example/"\n',
        "//registry.example/:_AUTHTOKEN=secret\n",
        "# _authToken=secret\nignore-scripts=true\n",
    ],
    ids=["quoted-hash", "uppercase", "comment"],
)
def test_package_rc_conservatively_rejects_npm_credentials(
    home: Path, content: str, capsys
) -> None:
    (home / ".npmrc").write_text(content)

    result = sandbox.resolve_package_rc(runtime(home))

    assert result == ()
    stderr = capsys.readouterr().err
    assert "contains credentials: not bound" in stderr


@pytest.mark.parametrize(("agent", "relative_path"), EXPECTED_AGENT_STATE_CASES)
def test_ensure_state_dirs_rejects_every_symlinked_state_directory(
    home: Path, agent: str, relative_path: str
) -> None:
    outside = home.parent / "outside"
    outside.mkdir()
    link = home / relative_path
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(
        sandbox.SandboxError, match="state dir has symlinked components"
    ):
        sandbox.ensure_state_dirs(runtime=runtime(home), agent=agent)
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize(
    ("agent", "parent"),
    [("pi", ".pi/agent"), ("omp", ".omp/agent"), ("opencode", ".config")],
)
def test_ensure_state_dirs_rejects_pinned_parents_before_seeding(
    home: Path, agent: str, parent: str
) -> None:
    outside = home.parent / "outside"
    outside.mkdir()
    link = home / parent
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(
        sandbox.SandboxError, match="resolves outside the agent's state dirs"
    ):
        sandbox.ensure_state_dirs(runtime=runtime(home), agent=agent)
    assert list(outside.iterdir()) == []


def test_parent_chain_handles_root_children_and_deduplicates_ancestors(
    home: Path,
) -> None:
    result = sandbox.resolve_parent_chain(
        home=home,
        workspace=sandbox.Workspace(
            root=Path("/projects/team/work"), common_dir=Path("/projects/repo/.git")
        ),
    )

    assert result == (Path("/projects"), Path("/projects/team"), Path("/projects/repo"))


def test_print_redacted_argv_preserves_empty_and_quoted_arguments(home: Path) -> None:
    args = ("", "two words", "$(literal)", "a'b", "***")

    assert shlex.split(sandbox.redacted_argv(args)) == list(args)


def test_bunfig_scan_accepts_non_toml_release_settings(home: Path) -> None:
    path = home / ".bunfig.toml"
    path.write_text("[install]\nminimumReleaseAge = 1728000\ninvalid-toml [")

    assert sandbox.resolve_package_rc(runtime(home)) == (path,)


@pytest.mark.parametrize(("agent", "state_path"), EXPECTED_AGENT_STATE_CASES)
@needs_tiocsti
def test_debug_dry_run_redacts_all_api_keys_and_does_not_seed_any_state_directory(
    scratch: Path, agent: str, state_path: str
) -> None:
    home = scratch / "home"
    repo = make_repo(home / "lsq" / "proj")

    proc = subprocess.run(
        [str(SCRIPT), "--debug", "--dry-run", agent, "", "two words"],
        env={
            **base_env(home),
            "AGENT_SANDBOX_BIN": "/bin/sh",
            **{
                variable: f"fixture-{variable.lower()}-secret"
                for variable in EXPECTED_API_KEY_VARS
            },
        },
        cwd=repo,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, proc.stderr
    assert argv_of(proc)[-3:] == ["/bin/sh", "", "two words"]
    assert "fixture-" not in proc.stdout + proc.stderr
    assert not (home / state_path).exists()


@pytest.mark.parametrize("agent", EXPECTED_AGENTS)
@pytest.mark.parametrize("blockable", (False, True))
def test_userns_policy_controls_nested_namespace_flags(
    agent: str, blockable: bool
) -> None:
    args = sandbox.namespace_args(
        policy=sandbox.POLICIES[agent], userns_blockable=blockable
    )

    expected = ("--die-with-parent", "--unshare-ipc", "--unshare-uts")
    if blockable and agent != "claude":
        expected += ("--unshare-user", "--disable-userns")
    assert args == expected


@pytest.mark.parametrize("status", (0, 1))
def test_userns_probe_uses_outer_namespace_and_reports_result(
    home: Path, status: int, capsys
) -> None:
    commands = []

    def run(argv, *, runtime):
        commands.append(argv)
        return subprocess.CompletedProcess(argv, status, "", "fixture denial")

    result = sandbox.probe_userns_blockable(runtime(home), run=run)

    assert result == (status == 0)
    assert commands[0][:8] == (
        "unshare",
        "--user",
        f"--map-user={os.getuid()}",
        f"--map-group={os.getgid()}",
        "--fork",
        "--pid",
        "--",
        "bwrap",
    )
    assert commands[0][8:10] == ("--unshare-user", "--disable-userns")
    assert ("nested user namespaces stay possible" in capsys.readouterr().err) == (
        status != 0
    )


@pytest.mark.parametrize("suffix", ("/", "/./", "/../home"))
def test_home_canonical_rejects_noncanonical_lexical_spelling(
    home: Path, suffix: str
) -> None:
    with pytest.raises(sandbox.SandboxError, match="HOME is not canonical"):
        sandbox.check_home_canonical(f"{home}{suffix}")


def test_home_canonical_rejects_root() -> None:
    with pytest.raises(sandbox.SandboxError, match="HOME is /"):
        sandbox.check_home_canonical("/")


def test_state_root_requires_invoker_ownership(home: Path) -> None:
    with pytest.raises(sandbox.SandboxError, match="state dir not owned by invoker"):
        sandbox.ensure_state_dirs(
            runtime=replace(runtime(home), uid=os.getuid() + 1), agent="pi"
        )


@pytest.mark.parametrize(
    ("mode", "creation_umask", "expected_mode"),
    (
        (0o600, 0o000, 0o600),
        (0o600, 0o022, 0o600),
        (0o600, 0o077, 0o600),
        (0o640, 0o022, 0o640),
        (0o640, 0o077, 0o600),
        (0o644, 0o022, 0o644),
        (0o644, 0o027, 0o640),
        (0o644, 0o077, 0o600),
    ),
    ids=(
        "600-000",
        "600-022",
        "600-077",
        "640-022",
        "640-077",
        "644-022",
        "644-027",
        "644-077",
    ),
)
def test_state_claude_copy_respects_source_mode_and_umask(
    home: Path, mode: int, creation_umask: int, expected_mode: int
) -> None:
    original = home / ".claude.json"
    original.write_text('{"oauth": "fixture"}\n')
    original.chmod(mode)
    reference = home / "cp-reference"
    previous_umask = os.umask(creation_umask)

    try:
        subprocess.run(args=["cp", str(original), str(reference)], check=True)
        sandbox.ensure_state_dirs(runtime=runtime(home), agent="claude")
    finally:
        os.umask(previous_umask)

    copied = home / ".claude/.claude.json"
    assert copied.stat().st_mode & 0o777 == expected_mode
    assert copied.stat().st_mode & 0o777 == reference.stat().st_mode & 0o777
    assert copied.read_text() == '{"oauth": "fixture"}\n'


def test_state_claude_copies_host_config_only_once(home: Path) -> None:
    original = home / ".claude.json"
    original.write_text('{"first": true}\n')
    sandbox.ensure_state_dirs(runtime=runtime(home), agent="claude")
    copied = home / ".claude/.claude.json"
    assert copied.read_text() == '{"first": true}\n'
    original.write_text('{"second": true}\n')

    sandbox.ensure_state_dirs(runtime=runtime(home), agent="claude")

    assert copied.read_text() == '{"first": true}\n'


def test_signing_reads_global_config_without_accepting_repository_override(
    home: Path, plain_repo: Path
) -> None:
    write_gitconfig(home, "key::ssh-ed25519 global")
    git("-C", str(plain_repo), "config", "gpg.format", "ssh")
    git("-C", str(plain_repo), "config", "user.signingkey", "key::ssh-rsa repository")

    result = sandbox.resolve_signing_key(runtime(home=home, cwd=plain_repo))

    assert result == sandbox.Signing(pubkey="ssh-ed25519 global")


@pytest.mark.parametrize(
    "content", ("", "\nssh-ed25519 fixture\n", "unknown fixture\n")
)
def test_signing_rejects_empty_leading_blank_and_unknown_type_files(
    home: Path, content: str
) -> None:
    (home / "key.pub").write_text(content)
    write_gitconfig(home, "~/key.pub")

    assert sandbox.resolve_signing_key(runtime(home)) == sandbox.Signing()


def test_signing_accepts_public_key_without_final_newline(home: Path) -> None:
    path = home / "key.pub"
    path.write_text("ssh-ed25519 fixture comment")
    write_gitconfig(home, "~/key.pub")

    assert sandbox.resolve_signing_key(runtime(home)) == sandbox.Signing(
        key_file=path, pubkey="ssh-ed25519 fixture"
    )


def test_signing_read_error_omits_key_file(home: Path, monkeypatch, capsys) -> None:
    (home / "key.pub").write_text("ssh-ed25519 fixture\n")
    write_gitconfig(home, "~/key.pub")

    def unreadable(*args, **kwargs):
        raise PermissionError("fixture read failure")

    monkeypatch.setattr(Path, "open", unreadable)

    assert sandbox.resolve_signing_key(runtime(home)) == sandbox.Signing()
    assert "cannot be inspected: not exposed" in capsys.readouterr().err


def test_ssh_sock_requires_invoker_ownership(
    home: Path, ssh_agent: str, capsys
) -> None:
    context = runtime(home=home, env_extra={"SSH_AUTH_SOCK": ssh_agent})

    result = sandbox.resolve_ssh_sock(
        runtime=replace(context, uid=context.uid + 1),
        signing=sandbox.Signing(pubkey="ssh-ed25519 fixture"),
    )

    assert result is None
    assert "not an invoker-owned socket" in capsys.readouterr().err


@needs_tiocsti
def test_ssh_sock_probe_kills_an_identity_command_that_ignores_termination(
    scratch: Path, ssh_agent: str
) -> None:
    home = scratch / "home"
    repo = make_repo(home / "project")
    write_gitconfig(home, "key::ssh-ed25519 fixture")
    stub_dir = scratch / "bin"
    stub_dir.mkdir()
    executable = stub_dir / "ssh-add"
    executable.write_text(
        f"#!{sys.executable}\nimport signal\nimport time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\ntime.sleep(30)\n"
    )
    executable.chmod(0o755)

    proc = subprocess.run(
        [str(SCRIPT), "--dry-run", "pi"],
        cwd=repo,
        env={
            **base_env(home),
            "AGENT_SANDBOX_BIN": "/bin/sh",
            "SSH_AUTH_SOCK": ssh_agent,
            "PATH": f"{stub_dir}:{os.environ['PATH']}",
        },
        capture_output=True,
        text=True,
        timeout=6,
    )

    assert "must hold exactly the signing key" in proc.stderr
    assert "SSH_AUTH_SOCK" not in argv_of(proc)


@pytest.mark.parametrize(
    ("error", "status"), ((errno.ENOENT, 127), (errno.EACCES, 126))
)
def test_exec_reports_shell_failure_status(
    error: int, status: int, monkeypatch
) -> None:
    def cannot_exec(*args, **kwargs):
        raise OSError(error, "fixture exec failure")

    monkeypatch.setattr(os, "execvp", cannot_exec)

    with pytest.raises(sandbox.SandboxError, match="fixture exec failure") as exc:
        sandbox.exec_process(("fixture-agent",))
    assert exc.value.exit_code == status


def test_direct_exec_preserves_signal_status(home: Path) -> None:
    proc = subprocess.run(
        [str(SCRIPT), "pi", "-c", "kill -TERM $$"],
        env={
            **base_env(home),
            "AGENT_SANDBOX_BIN": "/bin/sh",
            "AGENT_SANDBOX_DISABLE": "1",
        },
        capture_output=True,
        text=True,
    )

    assert proc.returncode == -15


@needs_tiocsti
def test_debug_redacts_secret_before_quoting_agent_arguments(scratch: Path) -> None:
    home = scratch / "home"
    repo = make_repo(home / "project")
    secret = "fixture'quoted-secret"

    proc = subprocess.run(
        [str(SCRIPT), "--debug", "--dry-run", "pi", secret],
        cwd=repo,
        env={
            **base_env(home),
            "AGENT_SANDBOX_BIN": "/bin/sh",
            "OPENAI_API_KEY": secret,
        },
        capture_output=True,
        text=True,
    )

    assert argv_of(proc)[-1] == "***"
    assert "quoted-secret" not in proc.stdout + proc.stderr
    debug_lines = tuple(
        line for line in proc.stderr.splitlines() if "agent-sandbox: debug:" in line
    )
    assert len(debug_lines) == 2
    assert debug_lines[0].startswith("agent-sandbox: debug: resolving agent=pi ")
    assert debug_lines[1].startswith("agent-sandbox: debug: launch argv: ")
    assert f"agent-sandbox: workspace: {repo}\n" in proc.stderr


def test_debug_argument_error_redacts_api_key_value(home: Path) -> None:
    secret = "fixture-secret"
    proc = subprocess.run(
        [str(SCRIPT), "--debug", secret],
        env={**base_env(home), "OPENAI_API_KEY": secret},
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 1
    assert "agent-sandbox: error: unknown agent: ***" in proc.stderr
    assert secret not in proc.stdout + proc.stderr


@needs_tiocsti
def test_filesystem_error_redacts_quoted_api_key_in_filename(scratch: Path) -> None:
    secret = "fixture'\"secret"
    home = scratch / secret
    repo = make_repo(home / "project")
    (home / ".agent").write_text("not a directory\n")

    proc = subprocess.run(
        [str(SCRIPT), "pi"],
        cwd=repo,
        env={
            **base_env(home),
            "AGENT_SANDBOX_BIN": "/bin/sh",
            "OPENAI_API_KEY": secret,
        },
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 1
    assert "agent-sandbox: error:" in proc.stderr
    assert "fixture" not in proc.stdout + proc.stderr


@needs_tiocsti
def test_integration_sandbox_environment_and_filesystem(scratch: Path) -> None:
    for executable in ("unshare", "bwrap"):
        if shutil.which(executable) is None:
            pytest.skip(
                f"required namespace runtime unavailable: {executable} not installed"
            )
    if not Path("/opt/mamba").is_dir():
        pytest.skip("required sandbox runtime tree /opt/mamba is unavailable")
    probe = subprocess.run(
        [
            "unshare",
            "--user",
            f"--map-user={os.getuid()}",
            f"--map-group={os.getgid()}",
            "--fork",
            "--pid",
            "--",
            "bwrap",
            "--unshare-ipc",
            "--unshare-uts",
            "--ro-bind",
            "/",
            "/",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--",
            "/usr/bin/true",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if probe.returncode != 0:
        pytest.skip(f"required namespace/mount probe failed: {probe.stderr.strip()}")

    home = scratch / "home"
    repo = make_repo(home / "project")
    cwd = repo / "sub"
    cwd.mkdir()
    (home / ".gitconfig").write_text("")
    (home / "private-marker").write_text("hidden\n")
    command = (
        'set -eu; test "${UNRELATED_SECRET+x}" = ""; '
        'test "$AGENT_SANDBOX_ACTIVE" = 1; test "$PWD" = "$1"; '
        'test "$(pwd -P)" = "$1"; test ! -e "$HOME/private-marker"; '
        "printf workspace > ../workspace-marker; "
        'printf ephemeral > "$HOME/ephemeral-marker"; '
        'test -f "$HOME/ephemeral-marker"; printf sandbox-ok'
    )

    proc = subprocess.run(
        [str(SCRIPT), "pi", "-c", command, "agent", str(cwd)],
        cwd=cwd,
        env={
            **base_env(home),
            "AGENT_SANDBOX_BIN": "/bin/sh",
            "UNRELATED_SECRET": "fixture",
        },
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "sandbox-ok"
    assert (repo / "workspace-marker").read_text() == "workspace"
    assert (home / "private-marker").read_text() == "hidden\n"
    assert not (home / "ephemeral-marker").exists()
