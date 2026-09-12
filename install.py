#!/usr/bin/env python3

"""Install the tracked dotfiles and optionally Neovim into the user's home directory."""

import argparse
import logging
import os
import platform
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

# mapping from ``platform.machine()`` values to the Neovim appimage architecture suffix
APPIMAGE_ARCHS = {
    "x86_64": "x86_64",
    "aarch64": "aarch64",
    "arm64": "aarch64",
}


class EnvironmentInstaller:
    """Orchestrate the environment installation."""

    def __init__(
        self,
        neovim_version: str = "stable",
        extract_appimage: bool = False,
        dry_run: bool = False,
        home_dir: Path | None = None,
        repo_dir: Path | None = None,
    ):
        """Initialize ``EnvironmentInstaller``.

        Args:
            neovim_version: Neovim release tag to install, e.g. ``v0.11.0``, ``stable``,
                or ``nightly``. Available versions can be found here:
                https://github.com/neovim/neovim/releases.
            extract_appimage: Extract the appimage (might be necessary if FUSE isn't
                available).
            dry_run: Preview the dotfile changes without modifying anything.
            home_dir: Directory to install into; defaults to the user's home.
            repo_dir: Directory holding ``dotfiles/``; defaults to this file's parent.
        """
        self._repo_dir = repo_dir if repo_dir is not None else Path(__file__).parent
        self._home_dir = home_dir if home_dir is not None else Path.home()
        self._logger = logging.getLogger(self.__class__.__name__)
        self._neovim_version = neovim_version
        self._extract_appimage = extract_appimage
        self._dry_run = dry_run

    def _run_command(
        self, command: Sequence[str | Path], cwd: Path | None = None
    ) -> subprocess.CompletedProcess:
        """Run the provided command, logging the command itself as well as the STDOUT.

        Args:
            command: Command to run.
            cwd: Working directory to run the command in.

        Returns:
            The completed process.

        Raises:
            subprocess.CalledProcessError: If the command exits with a non-zero code.
        """
        # log the command
        self._logger.info(f"⟩ {' '.join(str(x) for x in command)}")

        # run the command and log the STDOUT
        result = subprocess.run(
            command, check=True, capture_output=True, encoding="utf-8", cwd=cwd
        )
        if result.stdout:
            self._logger.info(result.stdout)

        return result

    def _check_dependencies(self) -> None:
        """Fail early if any command required by the installation is missing."""
        required = ["rsync"]
        if not self._dry_run and self._neovim_version.lower() not in ("0", "none"):
            required.append("wget")

        missing = [command for command in required if shutil.which(command) is None]
        if missing:
            self._logger.error(f"Missing required commands: {', '.join(missing)}")
            raise SystemExit(1)

    def _replace_line_prefix(
        self, file_path: Path, prefix: str, replacement: str
    ) -> None:
        """Replace any lines starting with ``prefix`` with ``replacement``."""
        with open(file_path, encoding="utf-8") as f:
            lines = f.readlines()

        lines = [
            f"{replacement}\n" if line.startswith(prefix) else line for line in lines
        ]

        with open(file_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

    def install_neovim(self) -> None:
        """Install Neovim to the user's home bin directory (~/bin/nvim)."""
        self._logger.info("Installing Neovim")

        machine = platform.machine()
        arch = APPIMAGE_ARCHS.get(machine)
        if arch is None:
            self._logger.error(
                f"Unsupported architecture for the Neovim appimage: {machine}"
            )
            raise SystemExit(1)

        # ensure the install path exists
        nvim_path = self._home_dir / "bin/nvim"
        if not nvim_path.parent.exists():
            nvim_path.parent.mkdir()

        # appimage url and commands to download and mark it as executable
        url = f"https://github.com/neovim/neovim/releases/download/{self._neovim_version}/nvim-linux-{arch}.appimage"
        commands = [
            ["wget", "-O", nvim_path, url],
            ["chmod", "u+x", nvim_path],
        ]

        # if extracting, then we have to run additional commands
        if self._extract_appimage:
            commands += [
                [nvim_path, "--appimage-extract"],
                ["rm", nvim_path],
                [
                    "ln",
                    "-s",
                    nvim_path.parent / "squashfs-root/usr/bin/nvim",
                    nvim_path,
                ],
            ]

        # run the commands
        for command in commands:
            self._run_command(command, cwd=nvim_path.parent)

        self._logger.info("Successfully installed Neovim")

    def copy_dotfiles(self) -> None:
        """Copy over the dotfiles to the user's home directory."""
        self._logger.info("Copying dotfiles")

        # source and destination directories to copy dotfiles from and to
        source_dir = self._repo_dir / "dotfiles"
        dest_dir = self._home_dir

        # run the command; never deploy local aider history
        command = [
            "rsync",
            "-av",
            "--exclude=.aider*",
            str(source_dir) + "/",
            str(dest_dir) + "/",
        ]
        if self._dry_run:
            command.append("--dry-run")
        self._run_command(command)

        self._logger.info("Successfully copied dotfiles")

    def apply_host_adjustments(self) -> None:
        """Adjust the deployed dotfiles to the current host.

        Edits the copies in the user's home directory, leaving the tracked files in
        the repository untouched.
        """
        self._logger.info("Applying host adjustments")

        # if MAMBA_ROOT_PREFIX is set on the host, use it in the deployed .mamba_init.sh
        mamba_root_prefix = os.environ.get("MAMBA_ROOT_PREFIX")
        if mamba_root_prefix:
            self._replace_line_prefix(
                self._home_dir / ".mamba_init.sh",
                "export MAMBA_ROOT_PREFIX=",
                f'export MAMBA_ROOT_PREFIX="{mamba_root_prefix}"',
            )

        self._logger.info("Successfully applied host adjustments")

    def run(self) -> None:
        """Run all install methods in sequence."""
        os.chdir(self._repo_dir)
        self._check_dependencies()

        try:
            if self._dry_run:
                self._logger.info("Dry run: no changes will be made")

            if not self._dry_run and self._neovim_version.lower() not in ("0", "none"):
                self.install_neovim()
            self.copy_dotfiles()
            if not self._dry_run:
                self.apply_host_adjustments()
        except subprocess.CalledProcessError as error:
            # surface the command's own error output instead of a bare traceback
            if error.stderr:
                self._logger.error(error.stderr.strip())
            self._logger.error(f"Command failed with exit code {error.returncode}")
            raise SystemExit(1) from error


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument list; defaults to ``sys.argv[1:]``.

    Returns:
        The parsed arguments.
    """
    parser = argparse.ArgumentParser(
        description="CLI for installing/configuring an Linux user environment.",
    )
    parser.add_argument(
        "--neovim-version",
        action="store",
        type=str,
        default="stable",
        metavar="<NVIM_VERSION>",
        help=(
            "Version of Neovim to install, e.g., v0.11.0, stable, or nightly. "
            "Use 'none' to skip."
        ),
    )
    parser.add_argument(
        "--extract-appimage",
        action="store_true",
        help="Extract the appimage (necessary on systems without FUSE).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the dotfile changes without modifying anything.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the CLI.

    Args:
        argv: Argument list; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code: 0 on success.
    """
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s %(asctime)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    installer = EnvironmentInstaller(
        neovim_version=args.neovim_version,
        extract_appimage=args.extract_appimage,
        dry_run=args.dry_run,
    )
    installer.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
