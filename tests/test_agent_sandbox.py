"""
Tests for dotfiles/bin/agent-sandbox: path checks, resolution, argv and the CLI.

Dry-run tests assert the printed bwrap argv only.
"""

import os
import shlex
import shutil
import socket
import subprocess
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import test_c
from test_c import commit_repo, git

# Module attributes register these as fixtures of this module.
bare_layout = test_c.bare_layout
plain_repo = test_c.plain_repo

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "dotfiles" / "bin" / "agent-sandbox"
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
# Sourcing keeps ``main`` behind the script's BASH_SOURCE guard; ``$0`` is ``_``.
RUN_FN = (
    'source "$1"; shift; fn="$1"; shift; "${fn}" "$@"; '
    'for v in ${SHOW}; do printf "%s=%s\\n" "${v}" "${!v-}"; done'
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


def run_fn(
    home: Path,
    fn: str,
    *args: str,
    show: tuple[str, ...] = (),
    cwd: Path | None = None,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """
    Source the script and call one of its functions.

    :param home: Fake ``$HOME``.
    :param fn: Function name.
    :param args: Arguments passed to the function.
    :param show: Variable names printed as ``name=value`` lines after the call.
    :param cwd: Working directory for the call.
    :param env_extra: Extra environment variables.
    :return: The completed process; ``die`` output reads ``_: error: <message>``.
    """
    env = {**base_env(home), "SHOW": " ".join(show), **(env_extra or {})}
    return subprocess.run(
        ["bash", "-c", RUN_FN, "_", str(SCRIPT), fn, *args],
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def shown(proc: subprocess.CompletedProcess[str]) -> dict[str, str]:
    """
    Parse the ``name=value`` lines printed by :func:`run_fn`.

    :param proc: The completed process.
    :return: Variable values by name.
    """
    return dict(line.split("=", 1) for line in proc.stdout.splitlines())


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
    Split the ``%q``-quoted argv a dry run prints.

    :param proc: The completed dry run.
    :return: The argv words.
    """
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
    proc = run_fn(home, "eval", f'printf "%s\\n" "${{{array_name}[@]}}"')

    assert proc.returncode == 0, proc.stderr
    actual = proc.stdout.splitlines()
    assert len(actual) == len(expected)
    assert set(actual) == set(expected)


@pytest.mark.parametrize(("agent", "expected"), EXPECTED_AGENT_STATE_DIRS.items())
def test_agent_state_policy_matches_the_complete_expected_contract(
    home: Path, agent: str, expected: tuple[str, ...]
) -> None:
    proc = run_fn(home, "eval", f'printf "%s\\n" "${{AGENT_STATE_DIRS[{agent}]}}"')

    assert proc.returncode == 0, proc.stderr
    actual = proc.stdout.split()
    assert len(actual) == len(expected)
    assert set(actual) == set(expected)


@pytest.mark.parametrize(("agent", "expected"), EXPECTED_AGENT_RO_PATHS.items())
def test_agent_read_only_policy_matches_the_complete_expected_contract(
    home: Path, agent: str, expected: tuple[str, ...]
) -> None:
    proc = run_fn(home, "eval", f'printf "%s\\n" "${{AGENT_RO_PATHS[{agent}]}}"')

    assert proc.returncode == 0, proc.stderr
    actual = proc.stdout.split()
    assert len(actual) == len(expected)
    assert set(actual) == set(expected)


@pytest.mark.parametrize(("agent", "expected"), EXPECTED_USERNS_POLICY.items())
def test_agent_user_namespace_policy_matches_the_complete_expected_contract(
    home: Path, agent: str, expected: str
) -> None:
    proc = run_fn(home, "eval", f'printf "%s\\n" "${{AGENT_DISABLE_USERNS[{agent}]}}"')

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines() == [expected]


def test_agent_executable_policy_names_every_supported_agent(home: Path) -> None:
    proc = run_fn(home, "eval", 'printf "%s\\n" "${!AGENT_EXE[@]}"')

    assert proc.returncode == 0, proc.stderr
    assert set(proc.stdout.splitlines()) == set(EXPECTED_AGENTS)


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
    proc = run_fn(TESTER_HOME, "refuse_denied_path", path, "workspace root")

    assert proc.returncode == 1
    assert message in proc.stderr


@pytest.mark.parametrize("path", ["/home/tester/proj", "/data/proj"])
def test_refuse_denied_path_accepts_ordinary_paths(path: str) -> None:
    proc = run_fn(TESTER_HOME, "refuse_denied_path", path, "workspace root")

    assert proc.returncode == 0
    assert proc.stderr == ""


@pytest.mark.parametrize("prefix", EXPECTED_DENY_PREFIXES)
def test_refuse_denied_path_rejects_every_system_prefix(
    home: Path, prefix: str
) -> None:
    proc = run_fn(home, "refuse_denied_path", f"{prefix}/x", "workspace root")

    assert proc.returncode == 1
    assert f"at/under {prefix}" in proc.stderr


# --- resolve_workspace


def resolved(home: Path, cwd: Path) -> tuple[str, str]:
    """
    Run ``resolve_workspace`` from ``cwd``.

    :param home: Fake ``$HOME``.
    :param cwd: Working directory.
    :return: ``(workspace, git_common_dir)``.
    """
    proc = run_fn(
        home, "resolve_workspace", show=("workspace", "git_common_dir"), cwd=cwd
    )
    assert proc.returncode == 0, proc.stderr
    values = shown(proc)
    return values["workspace"], values["git_common_dir"]


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
    proc = run_fn(
        home,
        "print_redacted_argv",
        "--setenv",
        variable,
        "secret",
        "--setenv",
        "HOME",
        "/x",
    )

    assert proc.returncode == 0
    assert shlex.split(proc.stdout) == [
        "--setenv",
        variable,
        "***",
        "--setenv",
        "HOME",
        "/x",
    ]
    assert "secret" not in proc.stdout


# --- parse_args


def test_parse_args_splits_flags_agent_and_verbatim_args(home: Path) -> None:
    proc = run_fn(
        home,
        "parse_args",
        "-v",
        "pi",
        "--dry-run",
        show=("agent", "agent_args[*]", "verbose"),
    )

    assert proc.returncode == 0
    assert shown(proc) == {"agent": "pi", "agent_args[*]": "--dry-run", "verbose": "1"}


def test_parse_args_rejects_unknown_flag(home: Path) -> None:
    proc = run_fn(home, "parse_args", "--bogus", "pi")

    assert proc.returncode == 1
    assert "unknown flag" in proc.stderr


def test_parse_args_requires_an_agent(home: Path) -> None:
    proc = run_fn(home, "parse_args")

    assert proc.returncode == 1
    assert "missing <agent>" in proc.stderr


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

    proc = run_fn(home, "resolve_workspace", cwd=hooks)

    assert proc.returncode == 1
    assert "without a work tree" in proc.stderr


def test_resolve_workspace_inside_bare_dir_maps_to_container(
    home: Path, bare_layout: Path
) -> None:
    hooks = bare_layout / ".bare" / "hooks"
    hooks.mkdir(exist_ok=True)

    assert resolved(home, hooks) == (str(bare_layout), "")


def test_resolve_workspace_dies_when_cwd_is_outside_the_workspace(
    home: Path, bare_layout: Path
) -> None:
    proc = run_fn(home, "resolve_workspace", cwd=bare_layout.parent / "outside")

    assert proc.returncode == 1
    assert "outside the workspace" in proc.stderr


# --- add_workspace_args parent chain


@needs_tiocsti
def test_parent_chain_under_home_is_tmpfs_remounted_read_only(scratch: Path) -> None:
    home = scratch / "home"
    repo = make_repo(home / "lsq" / "proj")
    lsq = str(home / "lsq")

    argv = argv_of(run_dry(home, repo))

    tmpfs = seq_index(argv, "--tmpfs", lsq)
    bind = seq_index(argv, "--bind", str(repo), str(repo))
    remount = seq_index(argv, "--remount-ro", lsq)
    assert tmpfs is not None and bind is not None and remount is not None
    assert tmpfs < bind < remount
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


def signing(home: Path) -> subprocess.CompletedProcess[str]:
    """
    Run ``resolve_signing_key`` and show its outputs.

    :param home: Fake ``$HOME``.
    :return: The completed process.
    """
    return run_fn(
        home, "resolve_signing_key", show=("signing_key_file", "signing_pubkey")
    )


@pytest.mark.parametrize("key_type", EXPECTED_SSH_PUBKEY_TYPES)
def test_signing_key_file_accepts_every_recognized_public_key_type(
    home: Path, key_type: str
) -> None:
    (home / ".ssh").mkdir()
    pubkey = f"{key_type} fixture"
    (home / ".ssh" / "k.pub").write_text(f"{pubkey}\n")
    write_gitconfig(home, "~/.ssh/k.pub")

    proc = signing(home)

    assert proc.returncode == 0, proc.stderr
    assert shown(proc) == {
        "signing_key_file": str(home / ".ssh" / "k.pub"),
        "signing_pubkey": pubkey,
    }


def test_signing_key_private_key_path_is_not_exposed(home: Path) -> None:
    keygen(home / ".ssh", "k")
    write_gitconfig(home, "~/.ssh/k")

    proc = signing(home)

    assert proc.returncode == 0, proc.stderr
    assert shown(proc) == {"signing_key_file": "", "signing_pubkey": ""}
    assert "not a public key file" in proc.stderr


def test_signing_key_literal_with_comment_sets_only_the_pubkey(home: Path) -> None:
    pubkey = keygen(home / ".ssh", "k")
    write_gitconfig(home, f"{pubkey} c")

    proc = signing(home)

    assert proc.returncode == 0, proc.stderr
    assert shown(proc) == {"signing_key_file": "", "signing_pubkey": pubkey}


def test_signing_key_key_prefixed_literal_sets_only_the_pubkey(home: Path) -> None:
    pubkey = keygen(home / ".ssh", "k")
    write_gitconfig(home, f"key::{pubkey}")

    proc = signing(home)

    assert proc.returncode == 0, proc.stderr
    assert shown(proc) == {"signing_key_file": "", "signing_pubkey": pubkey}


def test_signing_key_is_ignored_unless_gpg_format_is_ssh(home: Path) -> None:
    keygen(home / ".ssh", "k")
    write_gitconfig(home, "~/.ssh/k.pub", gpg_format="openpgp")

    proc = signing(home)

    assert proc.returncode == 0, proc.stderr
    assert shown(proc) == {"signing_key_file": "", "signing_pubkey": ""}


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


def resolved_ssh_sock(home: Path, sock: str) -> subprocess.CompletedProcess[str]:
    """
    Run ``resolve_signing_key`` then ``resolve_ssh_sock`` against ``sock``.

    :param home: Fake ``$HOME``.
    :param sock: Value for ``SSH_AUTH_SOCK``.
    :return: The completed process showing ``ssh_sock``.
    """
    return run_fn(
        home,
        "eval",
        "resolve_signing_key; resolve_ssh_sock",
        show=("ssh_sock",),
        env_extra={"SSH_AUTH_SOCK": sock},
    )


def test_ssh_sock_is_forwarded_when_the_agent_holds_exactly_the_signing_key(
    home: Path, ssh_agent: str
) -> None:
    keygen(home / ".ssh", "k1")
    write_gitconfig(home, "~/.ssh/k1.pub")
    ssh_add(ssh_agent, home / ".ssh" / "k1")

    proc = resolved_ssh_sock(home, ssh_agent)

    assert proc.returncode == 0, proc.stderr
    assert shown(proc) == {"ssh_sock": os.path.realpath(ssh_agent)}


def test_ssh_sock_is_not_forwarded_when_the_agent_holds_extra_keys(
    home: Path, ssh_agent: str
) -> None:
    keygen(home / ".ssh", "k1")
    keygen(home / ".ssh", "k2")
    write_gitconfig(home, "~/.ssh/k1.pub")
    ssh_add(ssh_agent, home / ".ssh" / "k1")
    ssh_add(ssh_agent, home / ".ssh" / "k2")

    proc = resolved_ssh_sock(home, ssh_agent)

    assert proc.returncode == 0, proc.stderr
    assert shown(proc) == {"ssh_sock": ""}
    assert "must hold exactly the signing key" in proc.stderr


def test_ssh_sock_is_not_forwarded_when_the_agent_holds_a_different_key(
    home: Path, ssh_agent: str
) -> None:
    keygen(home / ".ssh", "k1")
    keygen(home / ".ssh", "k2")
    write_gitconfig(home, "~/.ssh/k1.pub")
    ssh_add(ssh_agent, home / ".ssh" / "k2")

    proc = resolved_ssh_sock(home, ssh_agent)

    assert proc.returncode == 0, proc.stderr
    assert shown(proc) == {"ssh_sock": ""}


def test_ssh_sock_is_not_forwarded_without_a_signing_key(
    home: Path, ssh_agent: str
) -> None:
    keygen(home / ".ssh", "k1")
    ssh_add(ssh_agent, home / ".ssh" / "k1")

    proc = resolved_ssh_sock(home, ssh_agent)

    assert proc.returncode == 0, proc.stderr
    assert shown(proc) == {"ssh_sock": ""}
    assert "no ssh signing key configured" in proc.stderr


# --- add_env_args forwarding

CA_BUNDLE = Path("/etc/ssl/certs/ca-certificates.crt")


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

    proc = run_fn(
        home,
        "eval",
        'agent=pi; workspace="$HOME/workspace"; add_env_args; '
        'print_redacted_argv "${bwrap_args[@]}"',
        env_extra={variable: str(link)},
    )

    assert proc.returncode == 0, proc.stderr
    assert seq_index(argv_of(proc), "--setenv", variable, str(target)) is not None
    assert str(link) not in argv_of(proc)


@pytest.mark.parametrize(
    ("target_name", "warning"),
    [
        ("private-ca.pem", "points outside the sandbox"),
        ("missing.pem", "does not exist"),
    ],
    ids=["unexposed-target", "dangling-symlink"],
)
def test_forward_path_vars_drop_symlink_to_unavailable_target(
    home: Path, target_name: str, warning: str
) -> None:
    (home / "private-ca.pem").write_text("fixture CA bundle\n")
    link = home / "custom-ca.pem"
    link.symlink_to(home / target_name)

    proc = run_fn(
        home,
        "eval",
        'agent=pi; workspace="$HOME/workspace"; add_env_args; '
        'print_redacted_argv "${bwrap_args[@]}"',
        env_extra={"SSL_CERT_FILE": str(link)},
    )

    assert proc.returncode == 0, proc.stderr
    assert "SSL_CERT_FILE" not in argv_of(proc)
    assert warning in proc.stderr


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
    proc = run_fn(
        home,
        "print_redacted_argv",
        "--setenv",
        "FOO_API_KEY",
        "y",
    )

    assert proc.returncode == 0
    assert shlex.split(proc.stdout) == [
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
    proc = run_fn(home, "parse_args", "--", "pi", "-v", show=("agent", "agent_args[*]"))

    assert proc.returncode == 0
    assert shown(proc) == {"agent": "pi", "agent_args[*]": "-v"}


def test_parse_args_empty_agent_word_is_a_missing_agent(home: Path) -> None:
    proc = run_fn(home, "parse_args", "")

    assert proc.returncode == 1
    assert "missing <agent>" in proc.stderr


# --- ensure_state_dirs seeding


def ensure_state_dirs(home: Path, agent: str) -> subprocess.CompletedProcess[str]:
    """
    Run ``validate_agent`` then ``ensure_state_dirs`` for ``agent`` against ``home``.

    :param home: Fake ``$HOME``.
    :param agent: Agent name.
    :return: The completed process.
    """
    return run_fn(
        home,
        "eval",
        f"agent={agent}; validate_agent; ensure_state_dirs",
        env_extra={"AGENT_SANDBOX_BIN": "/bin/sh"},
    )


@pytest.mark.parametrize(("agent", "relative_path"), EXPECTED_PINNED_JSON_CASES)
def test_ensure_state_dirs_seeds_every_absent_pinned_json_file(
    home: Path, agent: str, relative_path: str
) -> None:
    proc = ensure_state_dirs(home, agent)

    assert proc.returncode == 0, proc.stderr
    assert (home / relative_path).read_text() == "{}\n"


@pytest.mark.parametrize(("agent", "relative_path"), EXPECTED_PINNED_DIRECTORY_CASES)
def test_ensure_state_dirs_seeds_every_absent_pinned_directory(
    home: Path, agent: str, relative_path: str
) -> None:
    proc = ensure_state_dirs(home, agent)

    assert proc.returncode == 0, proc.stderr
    assert (home / relative_path).is_dir()


@pytest.mark.parametrize(("agent", "relative_path"), EXPECTED_PINNED_JSON_CASES)
def test_ensure_state_dirs_keeps_every_existing_pinned_json_file(
    home: Path, agent: str, relative_path: str
) -> None:
    path = home / relative_path
    path.parent.mkdir(parents=True)
    path.write_text('{"hooks": {}}\n')

    proc = ensure_state_dirs(home, agent)

    assert proc.returncode == 0, proc.stderr
    assert path.read_text() == '{"hooks": {}}\n'


@pytest.mark.parametrize(("agent", "relative_path"), EXPECTED_PINNED_OTHER_FILE_CASES)
def test_ensure_state_dirs_does_not_seed_any_non_json_file(
    home: Path, agent: str, relative_path: str
) -> None:
    proc = ensure_state_dirs(home, agent)

    assert proc.returncode == 0, proc.stderr
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


def test_ssh_sock_stalled_identity_probe_continues_without_forwarding(
    home: Path,
) -> None:
    write_gitconfig(home, "key::ssh-ed25519 fixture")
    sock = str(home.parent / "s")
    env = {**base_env(home), "SSH_AUTH_SOCK": sock}
    command = (
        'source "$1"; resolve_signing_key; resolve_ssh_sock; '
        "agent=pi; add_env_args; add_signing_args; "
        'print_redacted_argv "${bwrap_args[@]}"'
    )

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(sock)
        server.listen(1)
        server.settimeout(5)
        with subprocess.Popen(
            ["bash", "-c", command, "_", str(SCRIPT)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ) as proc:
            try:
                connection, _ = server.accept()
                with connection:
                    connection.settimeout(5)
                    assert connection.recv(5) != b""
                    # Keep the connection open without replying. An outer
                    # deadline catches regressions in the wrapper's timeout.
                    stdout, stderr = proc.communicate(timeout=6)
            finally:
                # Closing the connection also releases ssh-add if the wrapper
                # regresses; kill/reap the shell before leaving the fixture.
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


def test_ssh_sock_is_not_forwarded_when_timeout_cannot_run(
    home: Path, ssh_agent: str
) -> None:
    keygen(home / ".ssh", "k1")
    write_gitconfig(home, "~/.ssh/k1.pub")
    ssh_add(ssh_agent, home / ".ssh" / "k1")
    stub_dir = home / "bin"
    stub_dir.mkdir()
    stub = stub_dir / "timeout"
    stub.write_text("#!/bin/sh\nexit 127\n")
    stub.chmod(0o755)

    proc = run_fn(
        home,
        "eval",
        "resolve_signing_key; resolve_ssh_sock",
        show=("ssh_sock",),
        env_extra={
            "SSH_AUTH_SOCK": ssh_agent,
            "PATH": f"{stub_dir}:{os.environ['PATH']}",
        },
    )

    assert proc.returncode == 0, proc.stderr
    assert shown(proc) == {"ssh_sock": ""}
    assert "not forwarded" in proc.stderr


def test_ssh_sock_is_not_forwarded_when_ssh_add_prints_nothing(
    home: Path, ssh_agent: str
) -> None:
    keygen(home / ".ssh", "k1")
    write_gitconfig(home, "~/.ssh/k1.pub")
    stub_dir = home / "bin"
    stub_dir.mkdir()
    stub = stub_dir / "ssh-add"
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o755)

    proc = run_fn(
        home,
        "eval",
        "resolve_signing_key; resolve_ssh_sock",
        show=("ssh_sock",),
        env_extra={
            "SSH_AUTH_SOCK": ssh_agent,
            "PATH": f"{stub_dir}:{os.environ['PATH']}",
        },
    )

    assert proc.returncode == 0, proc.stderr
    assert shown(proc) == {"ssh_sock": ""}
    assert "must hold exactly the signing key" in proc.stderr


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

    sibling_tmpfs = position(argv, "--tmpfs", str(scratch / "home" / "cameron"))
    assert sibling_tmpfs < position(argv, "--ro-bind-try", key, key)
    assert position(argv, "--ro-bind-try", key, key) < argv.index("--remount-ro")


# --- ensure_state_dirs pinned-path canonicalization


def test_ensure_state_dirs_dies_when_a_pinned_path_escapes_the_state_dirs(
    home: Path,
) -> None:
    (home / ".ssh").mkdir()
    (home / ".ssh" / "id").write_text("secret\n")
    (home / ".pi" / "agent").mkdir(parents=True)
    (home / ".pi" / "agent" / "settings.json").symlink_to(home / ".ssh" / "id")

    proc = ensure_state_dirs(home, "pi")

    assert proc.returncode == 1
    assert "resolves outside the agent's state dirs" in proc.stderr


def test_ensure_state_dirs_dies_on_a_dangling_pinned_link(home: Path) -> None:
    (home / ".pi" / "agent").mkdir(parents=True)
    (home / ".pi" / "agent" / "settings.json").symlink_to(home / "nowhere")

    proc = ensure_state_dirs(home, "pi")

    assert proc.returncode == 1
    assert "resolves outside the agent's state dirs" in proc.stderr


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

    proc = ensure_state_dirs(home, agent)

    assert proc.returncode == 0, proc.stderr
    assert link.is_symlink()


# --- signing key file content


def test_signing_key_file_with_extra_content_is_not_exposed(home: Path) -> None:
    pubkey = keygen(home / ".ssh", "k")
    key_file = home / ".ssh" / "k.pub"
    key_file.write_text(f"{pubkey} c\n-----BEGIN OPENSSH PRIVATE KEY-----\n")
    write_gitconfig(home, "~/.ssh/k.pub")

    proc = signing(home)

    assert proc.returncode == 0, proc.stderr
    assert shown(proc) == {"signing_key_file": "", "signing_pubkey": ""}
    assert "not a public key file" in proc.stderr


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
    home: Path, content: str
) -> None:
    (home / ".bunfig.toml").write_text(content)

    proc = run_fn(home, "resolve_package_rc", show=("rc_files[*]",))

    assert proc.returncode == 0, proc.stderr
    assert shown(proc) == {"rc_files[*]": ""}
    assert "contains credentials: not bound" in proc.stderr
    assert "secret" not in proc.stderr


@pytest.mark.parametrize("filename", EXPECTED_PACKAGE_RC_FILES)
def test_package_rc_inspection_failure_omits_the_file(
    home: Path, filename: str
) -> None:
    (home / filename).write_text("safe = true\n")
    stub_dir = home / "bin"
    stub_dir.mkdir()
    stub = stub_dir / "grep"
    stub.write_text("#!/bin/sh\nexit 127\n")
    stub.chmod(0o755)

    proc = run_fn(
        home,
        "resolve_package_rc",
        show=("rc_files[*]",),
        env_extra={"PATH": f"{stub_dir}:{os.environ['PATH']}"},
    )

    assert proc.returncode == 0, proc.stderr
    assert shown(proc) == {"rc_files[*]": ""}
    assert "cannot inspect" in proc.stderr


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
    home: Path, content: str
) -> None:
    (home / ".npmrc").write_text(content)

    proc = run_fn(home, "resolve_package_rc", show=("rc_files[*]",))

    assert proc.returncode == 0, proc.stderr
    assert shown(proc) == {"rc_files[*]": ""}
    assert "contains credentials: not bound" in proc.stderr


@pytest.mark.parametrize(("agent", "relative_path"), EXPECTED_AGENT_STATE_CASES)
def test_ensure_state_dirs_rejects_every_symlinked_state_directory(
    home: Path, agent: str, relative_path: str
) -> None:
    outside = home.parent / "outside"
    outside.mkdir()
    link = home / relative_path
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside, target_is_directory=True)

    proc = ensure_state_dirs(home, agent)

    assert proc.returncode == 1
    assert "state dir has symlinked components" in proc.stderr
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

    proc = ensure_state_dirs(home, agent)

    assert proc.returncode == 1
    assert "resolves outside the agent's state dirs" in proc.stderr
    assert list(outside.iterdir()) == []


def test_parent_chain_handles_root_children_and_deduplicates_ancestors(
    home: Path,
) -> None:
    proc = run_fn(
        home,
        "eval",
        "workspace=/projects/team/work; git_common_dir=/projects/repo/.git; "
        'resolve_parent_chain; printf "%s\\n" "${parent_dirs[@]}"',
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines() == ["/projects", "/projects/team", "/projects/repo"]


def test_print_redacted_argv_preserves_empty_and_quoted_arguments(home: Path) -> None:
    proc = run_fn(
        home, "print_redacted_argv", "", "two words", "$(literal)", "a'b", "***"
    )

    assert proc.returncode == 0, proc.stderr
    assert shlex.split(proc.stdout) == ["", "two words", "$(literal)", "a'b", "***"]


def test_bunfig_is_bound_without_python(
    home: Path,
) -> None:
    (home / ".bunfig.toml").write_text("[install]\nminimumReleaseAge = 1728000\n")
    stub_dir = home / "bin"
    stub_dir.mkdir()
    stub = stub_dir / "python3"
    stub.write_text('#!/bin/sh\ntouch "$HOME/python-invoked"\nexit 127\n')
    stub.chmod(0o755)

    proc = run_fn(
        home,
        "resolve_package_rc",
        show=("rc_files[*]",),
        env_extra={"PATH": f"{stub_dir}:{os.environ['PATH']}"},
    )

    assert proc.returncode == 0, proc.stderr
    assert shown(proc) == {"rc_files[*]": str(home / ".bunfig.toml")}
    assert not (home / "python-invoked").exists()


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
