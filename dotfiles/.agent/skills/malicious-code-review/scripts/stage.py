#!/usr/bin/env python3
"""Stage untrusted code as inert regular files for malicious-code review.

    stage.py ARCHIVE DEST     extract a .tar[.gz|.bz2|.xz], .tgz, .zip or .whl
    stage.py --dir SRC DEST   copy a local directory tree

DEST must not exist; it is created. Only regular files and directories are
staged. Links, devices and FIFOs are recorded and skipped, so nothing in DEST
points outside it. Members with absolute paths, `..` components or
backslashes, and duplicates of a path already staged, are recorded and
skipped. Staged files lose every execute bit. Git object stores are skipped
when copying a directory; hooks and config are kept as evidence. Nested
archives are staged as files, not unpacked.

Prints a JSON summary to stdout. The exit status is 0 when staging completed,
1 when it was abandoned (unreadable input, a size or count limit), and 2 on a
usage error. Standard library only.
"""

import argparse
import json
import os
import shutil
import stat
import sys
import tarfile
import zipfile
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath

DEFAULT_MAX_BYTES = 1024 * 1024 * 1024
DEFAULT_MAX_FILES = 100_000
FILE_MODE = 0o644
DIR_MODE = 0o755
GIT_OBJECT_STORES = frozenset({"objects", "lfs"})


class StageError(Exception):
    """A failure that abandons staging."""


@dataclass
class Summary:
    """What was staged and what was refused."""

    dest: str
    files: int = 0
    bytes: int = 0
    skipped: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class Member:
    """One entry of an archive or directory tree, before it is staged."""

    name: str
    kind: str
    size: int
    link_target: str | None = None


def member_path(name: str) -> PurePosixPath | str:
    """Validate a member name as a relative path inside the destination.

    Args:
        name: The name as recorded in the archive or tree.

    Returns:
        The relative path, or the reason it is refused.
    """
    if "\\" in name:
        return "backslash in name"
    path = PurePosixPath(name)
    if path.is_absolute():
        return "absolute path"
    if ".." in path.parts:
        return "parent-directory component"
    parts = tuple(part for part in path.parts if part != ".")
    if not parts:
        return "empty name"
    return PurePosixPath(*parts)


class Stager:
    """Write validated members into a fresh destination directory."""

    def __init__(self, dest: Path, max_bytes: int, max_files: int) -> None:
        self.dest = dest
        self.max_bytes = max_bytes
        self.max_files = max_files
        self.summary = Summary(dest=str(dest))
        self.staged: set[PurePosixPath] = set()
        dest.mkdir(mode=DIR_MODE)

    def skip(self, member: Member, reason: str) -> None:
        """Record a member that was not staged."""
        entry = {"path": member.name, "kind": member.kind, "reason": reason}
        if member.link_target is not None:
            entry["link_target"] = member.link_target
        self.summary.skipped.append(entry)

    def target(self, member: Member) -> Path | None:
        """Return where a member goes, or None after recording why it does not."""
        relative = member_path(member.name)
        if isinstance(relative, str):
            self.skip(member, reason=relative)
            return None
        if member.kind != "dir" and relative in self.staged:
            self.skip(member, reason="duplicate path")
            return None
        destination = self.dest.joinpath(*relative.parts)
        # A file staged earlier can occupy a later member's parent path
        for parent in reversed(destination.parents):
            if (
                parent.is_relative_to(self.dest)
                and parent != self.dest
                and parent.exists()
                and not parent.is_dir()
            ):
                self.skip(member, reason="parent path is a file")
                return None
        return destination

    def add_dir(self, member: Member) -> None:
        """Stage a directory."""
        destination = self.target(member)
        if destination is None:
            return
        if destination.exists() and not destination.is_dir():
            self.skip(member, reason="path is already a file")
            return
        destination.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)

    def add_file(self, member: Member, chunks: Iterator[bytes]) -> None:
        """Stage a regular file from its content chunks.

        Raises:
            StageError: When a size or count limit is exceeded.
        """
        destination = self.target(member)
        if destination is None:
            return
        if destination.exists():
            self.skip(member, reason="path is already a directory")
            return
        if self.summary.files + 1 > self.max_files:
            raise StageError(f"more than {self.max_files} files")
        destination.parent.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
        with destination.open("xb") as out:
            for chunk in chunks:
                self.summary.bytes += len(chunk)
                if self.summary.bytes > self.max_bytes:
                    raise StageError(f"more than {self.max_bytes} bytes uncompressed")
                out.write(chunk)
        destination.chmod(FILE_MODE)
        self.staged.add(PurePosixPath(*destination.relative_to(self.dest).parts))
        self.summary.files += 1


def read_chunks(handle, size: int = 1024 * 1024) -> Iterator[bytes]:
    """Yield a binary file object's content in chunks."""
    with handle:
        while chunk := handle.read(size):
            yield chunk


def tar_kind(info: tarfile.TarInfo) -> str:
    """Name a tar member's type."""
    if info.isfile():
        return "file"
    if info.isdir():
        return "dir"
    if info.issym():
        return "symlink"
    if info.islnk():
        return "hardlink"
    return "device or fifo"


def stage_tar(archive: Path, stager: Stager) -> None:
    """Stage the members of a tar archive."""
    with tarfile.open(archive) as tar:
        for info in tar:
            kind = tar_kind(info)
            member = Member(
                name=info.name,
                kind=kind,
                size=info.size,
                link_target=info.linkname or None,
            )
            if kind == "file":
                extracted = tar.extractfile(info)
                if extracted is None:
                    stager.skip(member, reason="unreadable member")
                    continue
                stager.add_file(member, chunks=read_chunks(extracted))
            elif kind == "dir":
                stager.add_dir(member)
            else:
                stager.skip(member, reason=f"{kind} not staged")


def stage_zip(archive: Path, stager: Stager) -> None:
    """Stage the members of a zip archive, including wheels."""
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            unix_mode = info.external_attr >> 16
            if stat.S_ISLNK(unix_mode):
                with bundle.open(info) as link:
                    target = link.read(4096).decode("utf-8", errors="replace")
                stager.skip(
                    Member(
                        name=info.filename,
                        kind="symlink",
                        size=info.file_size,
                        link_target=target,
                    ),
                    reason="symlink not staged",
                )
            elif info.is_dir():
                stager.add_dir(Member(name=info.filename, kind="dir", size=0))
            else:
                member = Member(name=info.filename, kind="file", size=info.file_size)
                stager.add_file(member, chunks=read_chunks(bundle.open(info)))


def stage_tree(source: Path, stager: Stager) -> None:
    """Stage a local directory tree without following links."""
    for root, dirs, files in os.walk(source, followlinks=False):
        root_path = Path(root)
        relative_root = root_path.relative_to(source)
        if root_path.name == ".git":
            for name in sorted(GIT_OBJECT_STORES.intersection(dirs)):
                dirs.remove(name)
                stager.skip(
                    Member(name=(relative_root / name).as_posix(), kind="dir", size=0),
                    reason="git object store",
                )
        for name in sorted(dirs) + sorted(files):
            path = root_path / name
            relative = (relative_root / name).as_posix()
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                stager.skip(
                    Member(
                        name=relative,
                        kind="symlink",
                        size=0,
                        link_target=os.readlink(path),
                    ),
                    reason="symlink not staged",
                )
            elif stat.S_ISDIR(mode):
                stager.add_dir(Member(name=relative, kind="dir", size=0))
            elif stat.S_ISREG(mode):
                stager.add_file(
                    Member(name=relative, kind="file", size=path.lstat().st_size),
                    chunks=read_chunks(path.open("rb")),
                )
            else:
                stager.skip(
                    Member(name=relative, kind="device or fifo", size=0),
                    reason="special file not staged",
                )


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse the command line."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "source", type=Path, help="archive file, or directory with --dir"
    )
    parser.add_argument("dest", type=Path, help="destination directory to create")
    parser.add_argument(
        "--dir",
        action="store_true",
        help="copy a local directory instead of extracting",
    )
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    return parser.parse_args(argv)


def main(argv: Sequence[str]) -> int:
    """Run the command line.

    Args:
        argv: The arguments after the program name.

    Returns:
        The process exit status.
    """
    args = parse_args(argv)
    if args.dest.exists():
        print(f"stage.py: {args.dest} already exists", file=sys.stderr)
        return 2
    if args.dir and not args.source.is_dir():
        print(f"stage.py: {args.source} is not a directory", file=sys.stderr)
        return 2
    stager = Stager(args.dest, max_bytes=args.max_bytes, max_files=args.max_files)
    try:
        if args.dir:
            stage_tree(args.source, stager=stager)
        elif zipfile.is_zipfile(args.source):
            stage_zip(args.source, stager=stager)
        else:
            stage_tar(args.source, stager=stager)
    except (StageError, OSError, tarfile.TarError, zipfile.BadZipFile, EOFError) as err:
        shutil.rmtree(args.dest)
        print(f"stage.py: abandoned, {args.dest} removed: {err}", file=sys.stderr)
        return 1
    print(json.dumps(asdict(stager.summary)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
