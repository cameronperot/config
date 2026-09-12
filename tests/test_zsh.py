"""Behavior checks for shell startup, history, and launcher widgets."""

import errno
import os
import pty
import select
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

DOTFILES = Path(__file__).resolve().parent.parent / "dotfiles"
PIN = "9bb69ab99c6f05d6e6ae237f7ce222eeeb5b4a14"
pytestmark = pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh is required")


@pytest.fixture
def shell_env(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    git = bin_dir / "git"
    git.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = clone ]; then\n'
        '    [ "${CLONE_FAIL:-0}" = 0 ] || exit 1\n'
        "    for target do :; done\n"
        '    mkdir -p "$target"\n'
        '    cp "$FAKE_ANTIDOTE" "$target/antidote.zsh"\n'
        "else\n"
        f'    printf "%s\\n" "${{ANTIDOTE_PIN:-{PIN}}}"\n'
        "fi\n"
    )
    git.chmod(0o755)
    antidote = tmp_path / "antidote-fixture.zsh"
    antidote.write_text(
        "antidote() { print -r -- 'bindkey -v; bindkey \"^A\" beginning-of-line'; }\n"
    )
    shutil.copyfile(src=DOTFILES / ".zshrc", dst=tmp_path / ".zshrc")
    shutil.copyfile(src=DOTFILES / ".zshenv", dst=tmp_path / ".zshenv")
    (tmp_path / ".zsh_plugins.txt").write_text("fixture\n")
    (tmp_path / ".local_exports").write_text("export LOCAL_EXPORT_LOADED=yes\n")
    return {
        "HOME": str(tmp_path),
        "ZDOTDIR": str(tmp_path),
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "FAKE_ANTIDOTE": str(antidote),
        "TERM": "xterm-256color",
        "LC_ALL": "C.UTF-8",
        "XDG_CACHE_HOME": str(tmp_path / ".cache"),
    }


def run_shell(*, env: dict[str, str], script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args=["zsh", "-di", "-c", script],
        env=env,
        cwd=env["HOME"],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )


def test_startup_incomplete_antidote_preserves_existing_files(shell_env):
    shell_env["CLONE_FAIL"] = "1"
    antidote = Path(shell_env["HOME"]) / ".antidote"
    antidote.mkdir()
    sentinel = antidote / "keep.txt"
    sentinel.write_text("existing data")

    result = run_shell(env=shell_env, script='print -r -- "$LOCAL_EXPORT_LOADED"')

    assert sentinel.read_text() == "existing data"
    assert result.stdout.strip() == "yes"
    assert "incomplete or differs from the pinned commit" in result.stderr


def test_startup_clone_failure_continues_and_cleans_temporary_directory(shell_env):
    shell_env["CLONE_FAIL"] = "1"

    result = run_shell(env=shell_env, script='print -r -- "$LOCAL_EXPORT_LOADED"')

    assert result.stdout.strip() == "yes"
    assert "plugins unavailable" in result.stderr
    assert list(Path(shell_env["HOME"]).glob(".antidote-bootstrap.*")) == []
    assert not (Path(shell_env["HOME"]) / ".antidote").exists()


def test_startup_wrong_download_pin_is_not_installed(shell_env):
    shell_env["ANTIDOTE_PIN"] = "wrong"

    result = run_shell(env=shell_env, script='print -r -- "$LOCAL_EXPORT_LOADED"')

    assert result.stdout.strip() == "yes"
    assert "downloaded antidote does not match" in result.stderr
    assert not (Path(shell_env["HOME"]) / ".antidote").exists()


def test_startup_valid_download_is_installed(shell_env):
    result = run_shell(env=shell_env, script='bindkey -M viins "^H"')

    assert result.stdout.strip() == '"^H" history-incremental-search-backward'
    assert result.stderr == ""
    assert (Path(shell_env["HOME"]) / ".antidote/antidote.zsh").is_file()
    assert list(Path(shell_env["HOME"]).glob(".antidote-bootstrap.*")) == []


def terminal_session(*, env: dict[str, str], script: str, input_bytes: bytes) -> str:
    """Run a shell in a terminal, feeding input once its setup is complete."""
    pid, master = pty.fork()
    if pid == 0:
        os.chdir(env["HOME"])
        os.execvpe("zsh", ["zsh", "-di", "-c", script], env)
    output = b""
    sent = False
    deadline = time.monotonic() + 10
    try:
        while time.monotonic() < deadline:
            if not select.select([master], [], [], 0.1)[0]:
                continue
            try:
                chunk = os.read(master, 65536)
            except OSError as error:
                if error.errno != errno.EIO:
                    raise
                break
            if not chunk:
                break
            output += chunk
            if b"READY" in output and not sent:
                os.write(master, input_bytes)
                sent = True
        else:
            os.kill(pid, signal.SIGKILL)
            pytest.fail("terminal session timed out")
    finally:
        os.close(master)
        _, wait_status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(wait_status) == 0, output.decode(errors="replace")
    return output.decode(errors="replace")


@pytest.mark.parametrize(
    ("program", "shortcut"), [("nvim", b"\x0e"), ("ranger", b"\x12")]
)
def test_launcher_preserves_buffer_and_cursor(shell_env, program, shortcut):
    launcher = Path(shell_env["HOME"]) / "bin" / program
    launcher.write_text('#!/bin/sh\nprintf "LAUNCHED\\n"\n')
    launcher.chmod(0o755)

    output = terminal_session(
        env=shell_env,
        script='line=""; print READY; vared line; print -r -- "CAPTURED=$line"',
        input_bytes=b"print unfinished\x01" + shortcut + b"X\r",
    )

    assert "LAUNCHED" in output
    assert "CAPTURED=Xprint unfinished" in output


def test_history_saves_completed_commands_and_excludes_filtered_commands(shell_env):
    result = subprocess.run(
        args=["zsh", "-di"],
        env=shell_env,
        cwd=shell_env["HOME"],
        input=(
            "print NORMAL_COMMAND\n"
            "print Password=example\n"
            "print SeCrEt=example\n"
            " print PRIVATE_COMMAND\n"
            "fc -l -20\n"
            "print DISK_HISTORY; /bin/cat $HISTFILE\n"
            "exit\n"
        ),
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )

    history_output = result.stdout.split("PRIVATE_COMMAND\n", maxsplit=1)[1]
    disk_history = history_output.split("DISK_HISTORY\n", maxsplit=1)[1]
    assert "print NORMAL_COMMAND" in disk_history
    assert "Password=example" not in history_output
    assert "SeCrEt=example" not in history_output
    assert "print PRIVATE_COMMAND" not in history_output
