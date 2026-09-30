"""Tests for install.py: dependency checks, Neovim install, and host adjustments."""

import logging
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest
from conftest import snapshot, write_tree

import install

PROTECTED_CONFIGS = (
    (".gitconfig", ".gitconfig"),
    (".config/sway", ".config/sway/config"),
    (".config/waybar", ".config/waybar/config"),
    (".config/Code", ".config/Code/User/settings.json"),
)


@pytest.fixture
def copy_env(tmp_path):
    """Build temporary home and repository trees for real rsync calls."""
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    (home / ".config").mkdir(parents=True)
    write_tree(
        root=repo / "dotfiles",
        files={
            relative_file: "repository defaults\n"
            for _, relative_file in PROTECTED_CONFIGS
        },
    )
    return home, repo


@pytest.mark.parametrize(("relative_path", "relative_file"), PROTECTED_CONFIGS)
def test_copy_dotfiles_preserves_existing_configuration(
    copy_env, relative_path, relative_file
):
    home, repo = copy_env
    write_tree(root=home, files={relative_file: "custom configuration\n"})
    target = home / relative_file
    target.chmod(0o600)
    before = snapshot(home)
    installer = install.EnvironmentInstaller(home_dir=home, repo_dir=repo)

    installer.copy_dotfiles()

    assert snapshot(home)[relative_file] == before[relative_file]


@pytest.mark.parametrize(
    "relative_path", (".config/sway", ".config/waybar", ".config/Code")
)
@pytest.mark.parametrize(
    "existing_files", ({}, {"custom.conf": "custom configuration\n"})
)
def test_copy_dotfiles_skips_entire_existing_directory(
    copy_env, relative_path, existing_files
):
    home, repo = copy_env
    target = home / relative_path
    target.mkdir()
    write_tree(root=target, files=existing_files)
    target.chmod(0o700)
    before = snapshot(target)
    before_stat = target.stat()
    installer = install.EnvironmentInstaller(home_dir=home, repo_dir=repo)

    installer.copy_dotfiles()

    assert snapshot(target) == before
    assert target.stat().st_mode == before_stat.st_mode
    assert target.stat().st_mtime_ns == before_stat.st_mtime_ns


@pytest.mark.parametrize(("relative_path", "relative_file"), PROTECTED_CONFIGS)
def test_copy_dotfiles_installs_missing_configuration(
    copy_env, relative_path, relative_file
):
    home, repo = copy_env
    installer = install.EnvironmentInstaller(home_dir=home, repo_dir=repo)

    installer.copy_dotfiles()

    assert (home / relative_file).read_text() == "repository defaults\n"


@pytest.mark.parametrize("relative_path", tuple(path for path, _ in PROTECTED_CONFIGS))
@pytest.mark.parametrize("target_root", ("repo/dotfiles", "missing"))
def test_copy_dotfiles_preserves_configuration_symlinks(
    copy_env, tmp_path, relative_path, target_root
):
    home, repo = copy_env
    target = tmp_path / target_root / relative_path
    link = home / relative_path
    link.symlink_to(target)
    before = snapshot(repo)
    installer = install.EnvironmentInstaller(home_dir=home, repo_dir=repo)

    installer.copy_dotfiles()

    assert link.is_symlink()
    assert link.readlink() == target
    assert snapshot(repo) == before
    assert not (tmp_path / "missing").exists()


@pytest.mark.parametrize(("relative_path", "relative_file"), PROTECTED_CONFIGS)
def test_copy_dotfiles_dry_run_skips_existing_configuration(
    copy_env, caplog, relative_path, relative_file
):
    home, repo = copy_env
    write_tree(root=home, files={relative_file: "custom configuration\n"})
    before = snapshot(home)
    installer = install.EnvironmentInstaller(home_dir=home, repo_dir=repo, dry_run=True)

    with caplog.at_level(logging.INFO):
        installer.copy_dotfiles()

    assert snapshot(home) == before
    assert f"Skipping existing configuration: {home / relative_path}" in caplog.text
    assert relative_file not in caplog.text.splitlines()


def test_copy_dotfiles_dry_run_previews_missing_configuration(copy_env, caplog):
    home, repo = copy_env
    before = snapshot(home)
    installer = install.EnvironmentInstaller(home_dir=home, repo_dir=repo, dry_run=True)

    with caplog.at_level(logging.INFO):
        installer.copy_dotfiles()

    assert snapshot(home) == before
    assert ".gitconfig" in caplog.text.splitlines()
    assert ".config/sway/config" in caplog.text.splitlines()
    assert ".config/waybar/config" in caplog.text.splitlines()
    assert ".config/Code/User/settings.json" in caplog.text.splitlines()


def test_copy_dotfiles_updates_unprotected_files(copy_env):
    home, repo = copy_env
    write_tree(root=home, files={".gitconfig": "custom git\n", ".zshrc": "old\n"})
    write_tree(
        root=repo / "dotfiles",
        files={
            ".zshrc": "updated shell\n",
            "nested/.gitconfig": "nested git\n",
            ".config/Code-extra/settings.json": "other editor\n",
            ".aider.history": "local history\n",
        },
    )
    installer = install.EnvironmentInstaller(home_dir=home, repo_dir=repo)

    installer.copy_dotfiles()

    assert (home / ".zshrc").read_text() == "updated shell\n"
    assert (home / "nested/.gitconfig").read_text() == "nested git\n"
    assert (home / ".config/Code-extra/settings.json").read_text() == "other editor\n"
    assert not (home / ".aider.history").exists()


class RecordingInstaller(install.EnvironmentInstaller):
    """Installer whose command runner records invocations instead of running them."""

    def __init__(self, recorder: list, **kwargs) -> None:
        """Store the recorder, then build a normal installer.

        Args:
            recorder: List that each run command is appended to as ``(command, cwd)``.
            **kwargs: Forwarded to ``EnvironmentInstaller``.
        """
        super().__init__(**kwargs)
        self._recorder = recorder

    def _run_command(
        self, command: Sequence[str | Path], cwd: Path | None = None
    ) -> subprocess.CompletedProcess:
        """Record the command and report success without running anything."""
        self._recorder.append((command, cwd))
        return subprocess.CompletedProcess(command, 0)


def make_installer(tmp_path, recorder, **kwargs):
    """Build an installer wired to fake home/repo directories and a fake runner.

    Args:
        tmp_path: Pytest temporary directory root.
        recorder: List that each run command is appended to as ``(command, cwd)``.
        **kwargs: Forwarded to ``EnvironmentInstaller``.

    Returns:
        The installer instance.
    """
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    (repo / "dotfiles").mkdir(parents=True, exist_ok=True)
    home.mkdir(exist_ok=True)
    ssh_rc = home / ".config/tmux/ssh_rc"
    ssh_rc.parent.mkdir(parents=True, exist_ok=True)
    ssh_rc.write_text("#!/bin/sh\nexit 0\n")

    return RecordingInstaller(recorder, home_dir=home, repo_dir=repo, **kwargs)


def test_parse_args_defaults():
    args = install.parse_args([])

    assert args.neovim_version == "none"
    assert args.extract_appimage is False
    assert args.dry_run is False


def test_parse_args_accepts_every_flag():
    args = install.parse_args(
        ["--neovim-version", "v0.11.0", "--extract-appimage", "--dry-run"]
    )

    assert args.neovim_version == "v0.11.0"
    assert args.extract_appimage is True
    assert args.dry_run is True


def test_parse_args_rejects_unknown_flags():
    with pytest.raises(SystemExit) as excinfo:
        install.parse_args(["--nope"])

    assert excinfo.value.code == 2


def test_construction_has_no_global_side_effects(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(install.os, "chdir", lambda path: calls.append(path))
    monkeypatch.setattr(install.Path, "home", staticmethod(lambda: tmp_path / "unused"))

    install.EnvironmentInstaller()

    assert calls == []


def test_missing_rsync_exits_one(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(install.shutil, "which", lambda command: None)
    installer = make_installer(tmp_path, [])

    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as excinfo:
        installer._check_dependencies()

    assert excinfo.value.code == 1
    assert "Missing required commands: rsync" in caplog.text


def test_wget_is_required_only_when_neovim_is_installed(tmp_path, monkeypatch):
    present = {"rsync"}
    monkeypatch.setattr(
        install.shutil, "which", lambda command: command if command in present else None
    )

    make_installer(tmp_path, [])._check_dependencies()
    make_installer(tmp_path, [], neovim_version="none")._check_dependencies()
    make_installer(tmp_path, [], dry_run=True)._check_dependencies()

    with pytest.raises(SystemExit):
        make_installer(tmp_path, [], neovim_version="stable")._check_dependencies()


def test_unsupported_architecture_exits_one(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(install.platform, "machine", lambda: "riscv64")
    installer = make_installer(tmp_path, [])

    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as excinfo:
        installer.install_neovim()

    assert excinfo.value.code == 1
    assert "Unsupported architecture" in caplog.text


@pytest.mark.parametrize(
    ("machine", "arch"),
    [("x86_64", "x86_64"), ("aarch64", "aarch64"), ("arm64", "aarch64")],
)
def test_neovim_appimage_url_follows_the_architecture(
    tmp_path, monkeypatch, machine, arch
):
    monkeypatch.setattr(install.platform, "machine", lambda: machine)
    recorder = []
    installer = make_installer(tmp_path, recorder, neovim_version="v0.11.0")

    installer.install_neovim()

    url = recorder[0][0][-1]
    assert url.endswith(f"v0.11.0/nvim-linux-{arch}.appimage")
    assert (tmp_path / "home/bin").is_dir()


def test_neovim_install_downloads_and_marks_executable(tmp_path, monkeypatch):
    monkeypatch.setattr(install.platform, "machine", lambda: "x86_64")
    recorder = []
    installer = make_installer(tmp_path, recorder, neovim_version="stable")

    installer.install_neovim()

    nvim = tmp_path / "home/bin/nvim"
    assert [command[:2] for command, _ in recorder] == [
        ["wget", "-O"],
        ["chmod", "u+x"],
    ]
    assert all(cwd == nvim.parent for _, cwd in recorder)


def test_extract_appimage_adds_the_extraction_sequence(tmp_path, monkeypatch):
    monkeypatch.setattr(install.platform, "machine", lambda: "x86_64")
    recorder = []
    installer = make_installer(
        tmp_path, recorder, neovim_version="stable", extract_appimage=True
    )

    installer.install_neovim()

    nvim = tmp_path / "home/bin/nvim"
    assert [command[0] for command, _ in recorder] == [
        "wget",
        "chmod",
        nvim,
        "rm",
        "ln",
    ]
    assert recorder[-1][0][2] == nvim.parent / "squashfs-root/usr/bin/nvim"


def test_copy_dotfiles_rsyncs_with_the_aider_exclusion(tmp_path):
    recorder = []
    installer = make_installer(tmp_path, recorder)

    installer.copy_dotfiles()

    command, _ = recorder[0]
    assert command[:3] == ["rsync", "-av", "--exclude=.aider*"]
    assert command[3] == f"{tmp_path / 'repo/dotfiles'}/"
    assert command[4] == f"{tmp_path / 'home'}/"
    assert "--dry-run" not in command


def test_copy_dotfiles_previews_under_dry_run(tmp_path):
    recorder = []
    installer = make_installer(tmp_path, recorder, dry_run=True)

    installer.copy_dotfiles()

    assert recorder[0][0][-1] == "--dry-run"


def test_replace_line_prefix_rewrites_the_whole_line(tmp_path):
    target = tmp_path / "mamba_init.sh"
    target.write_text('export MAMBA_ROOT_PREFIX="/old"\nexport OTHER=1\n')
    installer = make_installer(tmp_path, [])

    installer._replace_line_prefix(
        target, "export MAMBA_ROOT_PREFIX=", 'export MAMBA_ROOT_PREFIX="/new"'
    )

    assert target.read_text() == 'export MAMBA_ROOT_PREFIX="/new"\nexport OTHER=1\n'


def test_host_adjustments_rewrite_mamba_prefix_when_set(tmp_path, monkeypatch):
    monkeypatch.setenv("MAMBA_ROOT_PREFIX", "/opt/mamba")
    installer = make_installer(tmp_path, [])
    home = tmp_path / "home"
    (home / ".mamba_init.sh").write_text('export MAMBA_ROOT_PREFIX="/old"\n')

    installer.apply_host_adjustments()

    assert (
        home / ".mamba_init.sh"
    ).read_text() == 'export MAMBA_ROOT_PREFIX="/opt/mamba"\n'


def test_host_adjustments_leave_mamba_init_alone_when_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("MAMBA_ROOT_PREFIX", raising=False)
    installer = make_installer(tmp_path, [])
    home = tmp_path / "home"
    (home / ".mamba_init.sh").write_text('export MAMBA_ROOT_PREFIX="/old"\n')

    installer.apply_host_adjustments()

    assert (home / ".mamba_init.sh").read_text() == 'export MAMBA_ROOT_PREFIX="/old"\n'


def test_host_adjustments_install_private_ssh_rc(tmp_path, monkeypatch):
    monkeypatch.delenv("MAMBA_ROOT_PREFIX", raising=False)
    installer = make_installer(tmp_path, [])
    ssh_dir = tmp_path / "home/.ssh"

    installer.apply_host_adjustments()

    assert (ssh_dir / "rc").read_text() == "#!/bin/sh\nexit 0\n"
    assert (ssh_dir / "rc").stat().st_mode & 0o777 == 0o600
    assert ssh_dir.stat().st_mode & 0o777 == 0o700


def test_host_adjustments_preserve_existing_ssh_rc_link(tmp_path, monkeypatch):
    monkeypatch.delenv("MAMBA_ROOT_PREFIX", raising=False)
    installer = make_installer(tmp_path, [])
    ssh_dir = tmp_path / "home/.ssh"
    ssh_dir.mkdir()
    ssh_rc = ssh_dir / "rc"
    ssh_rc.symlink_to("../.config/tmux/ssh_rc")

    installer.apply_host_adjustments()

    assert ssh_rc.is_symlink()
    assert ssh_rc.read_text() == "#!/bin/sh\nexit 0\n"


def test_run_skips_neovim_and_adjustments_under_dry_run(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(install.shutil, "which", lambda command: command)
    installer = make_installer(tmp_path, [], dry_run=True)
    performed = []
    installer.install_neovim = lambda: performed.append("neovim")
    installer.copy_dotfiles = lambda: performed.append("copy")
    installer.apply_host_adjustments = lambda: performed.append("adjust")

    with caplog.at_level(logging.INFO):
        installer.run()

    assert performed == ["copy"]
    assert "Dry run: no changes will be made" in caplog.text


def test_run_skips_neovim_when_the_version_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr(install.shutil, "which", lambda command: command)
    installer = make_installer(tmp_path, [], neovim_version="none")
    performed = []
    installer.install_neovim = lambda: performed.append("neovim")
    installer.copy_dotfiles = lambda: performed.append("copy")
    installer.apply_host_adjustments = lambda: performed.append("adjust")

    installer.run()

    assert performed == ["copy", "adjust"]


def test_run_surfaces_a_failed_command_and_exits_one(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(install.shutil, "which", lambda command: command)
    installer = make_installer(tmp_path, [], neovim_version="none")

    def boom():
        raise subprocess.CalledProcessError(2, "rsync", stderr="rsync: boom\n")

    installer.copy_dotfiles = boom

    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as excinfo:
        installer.run()

    assert excinfo.value.code == 1
    assert "rsync: boom" in caplog.text
    assert "Command failed with exit code 2" in caplog.text


def test_main_forwards_parsed_arguments_and_returns_zero(tmp_path, monkeypatch):
    recorded = {}

    def record(self):
        recorded["neovim_version"] = self._neovim_version
        recorded["extract_appimage"] = self._extract_appimage
        recorded["dry_run"] = self._dry_run

    monkeypatch.setattr(install.EnvironmentInstaller, "run", record)

    exit_code = install.main(["--neovim-version", "none", "--dry-run"])

    assert exit_code == 0
    assert recorded == {
        "neovim_version": "none",
        "extract_appimage": False,
        "dry_run": True,
    }


def test_run_command_logs_the_command_and_its_output(tmp_path, monkeypatch, caplog):
    installer = install.EnvironmentInstaller(
        home_dir=tmp_path / "home", repo_dir=tmp_path / "repo"
    )
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="done\n", stderr="")

    monkeypatch.setattr(install.subprocess, "run", fake_run)

    with caplog.at_level(logging.INFO):
        result = installer._run_command(["echo", "hi"], cwd=tmp_path)

    assert result.returncode == 0
    assert calls[0][1]["cwd"] == tmp_path
    assert calls[0][1]["check"] is True
    assert "⟩ echo hi" in caplog.text
    assert "done" in caplog.text


def test_run_installs_neovim_when_the_version_is_a_release(tmp_path, monkeypatch):
    monkeypatch.setattr(install.shutil, "which", lambda command: command)
    installer = make_installer(tmp_path, [], neovim_version="v0.11.0")
    performed = []
    installer.install_neovim = lambda: performed.append("neovim")
    installer.copy_dotfiles = lambda: performed.append("copy")
    installer.apply_host_adjustments = lambda: performed.append("adjust")

    installer.run()

    assert performed == ["neovim", "copy", "adjust"]
