#!/usr/bin/env python3
"""Inventory a staged review directory for the malware reviewer.

    inventory.py REVIEW_DIR [--manifest FILE]

REVIEW_DIR holds `target/` and optionally `baseline/` (the previously accepted
version). Prints Markdown to stdout: totals, execution surfaces (files that
run on install, build, import, startup or in CI), flagged files (binaries,
nested archives, minified code, long encoded literals, files too large to scan
in full) and, with a baseline, the files added, removed and changed.
`--manifest` also writes a SHA-256 manifest as TSV. Reads files only; never
imports or runs them. Exit status 0 on success, 2 on a usage error. Standard
library only.
"""

import argparse
import hashlib
import json
import re
import sys
import tomllib
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

SCAN_BYTES = 5 * 1024 * 1024
LIST_LIMIT = 200
MINIFIED_LINE = 2000
ENCODED_RUN = re.compile(rb"[A-Za-z0-9+/=_-]{200,}|(?:\\x[0-9a-fA-F]{2}){50,}")
NPM_LIFECYCLE = (
    "preinstall",
    "install",
    "postinstall",
    "prepare",
    "prepack",
    "postpack",
)
MAGIC = (
    (b"\x7fELF", "ELF binary"),
    (b"MZ", "Windows executable"),
    (b"\xcf\xfa\xed\xfe", "Mach-O binary"),
    (b"\xca\xfe\xba\xbe", "Mach-O universal or Java class"),
    (b"\x00asm", "WebAssembly"),
    (b"PK\x03\x04", "zip archive"),
    (b"\x1f\x8b", "gzip archive"),
    (b"\xfd7zXZ\x00", "xz archive"),
    (b"BZh", "bzip2 archive"),
    (b"7z\xbc\xaf\x27\x1c", "7z archive"),
)
SURFACE_NAMES = {
    "setup.py": "Python build script",
    "setup.cfg": "Python build config",
    "pyproject.toml": "Python build config",
    "sitecustomize.py": "Python startup hook",
    "usercustomize.py": "Python startup hook",
    "conftest.py": "pytest import-time code",
    "entry_points.txt": "Python entry points",
    "package.json": "npm manifest",
    "binding.gyp": "native addon build",
    ".npmrc": "npm config",
    ".yarnrc": "yarn config",
    ".yarnrc.yml": "yarn config",
    "Makefile": "Makefile",
    "GNUmakefile": "Makefile",
    "build.rs": "Cargo build script",
    "Cargo.toml": "Cargo manifest",
    "build.gradle": "Gradle build",
    "build.gradle.kts": "Gradle build",
    "pom.xml": "Maven build",
    "extconf.rb": "Ruby native extension build",
    "Rakefile": "Rake build",
    ".envrc": "direnv script",
    ".pre-commit-config.yaml": "pre-commit hooks",
    ".gitattributes": "git filters",
    "action.yml": "GitHub Action",
    "action.yaml": "GitHub Action",
    "tasks.json": "editor task config",
}
SURFACE_SUFFIXES = {
    ".pth": "Python path hook",
    ".sh": "shell script",
    ".bash": "shell script",
    ".zsh": "shell script",
    ".ps1": "PowerShell script",
    ".bat": "Windows batch script",
    ".cmd": "Windows batch script",
    ".mk": "Makefile",
    ".gemspec": "Ruby gem spec",
    ".csproj": "MSBuild project",
    ".targets": "MSBuild targets",
    ".props": "MSBuild props",
    ".so": "native library",
    ".pyd": "native library",
    ".dylib": "native library",
    ".dll": "native library",
    ".node": "native addon",
}


@dataclass
class FileFacts:
    """What the inventory records about one file."""

    path: PurePosixPath
    size: int
    sha256: str
    surfaces: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


def surface_kinds(path: PurePosixPath) -> list[str]:
    """Classify a path as zero or more execution surfaces by name and location."""
    kinds = []
    parts = path.parts
    if path.name in SURFACE_NAMES:
        kinds.append(SURFACE_NAMES[path.name])
    if path.suffix in SURFACE_SUFFIXES:
        kinds.append(SURFACE_SUFFIXES[path.suffix])
    if path.name.startswith("Dockerfile") or path.name == "Containerfile":
        kinds.append("container build")
    if ".github" in parts and "workflows" in parts and path.suffix in (".yml", ".yaml"):
        kinds.append("GitHub workflow")
    if ".git" in parts and ("hooks" in parts or path.name == "config"):
        kinds.append("git hook or config")
    if ".devcontainer" in parts or ".vscode" in parts:
        kinds.append("editor or dev-container config")
    return kinds


def content_facts(
    path: PurePosixPath, head: bytes, complete: bool
) -> tuple[list[str], list[str]]:
    """Derive surface details and flags from a file's leading bytes.

    Args:
        path: The file's path relative to the tree.
        head: Up to SCAN_BYTES of the file's content.
        complete: Whether head is the whole file.

    Returns:
        Extra surface descriptions and flags.
    """
    surfaces: list[str] = []
    flags: list[str] = []
    label = next((label for magic, label in MAGIC if head.startswith(magic)), None)
    if label is None and b"\x00" in head[:8192]:
        label = "binary data"
    if label is not None:
        flags.append(label)
    if not complete:
        flags.append(f"larger than {SCAN_BYTES} bytes; only the start was scanned")
    if label is not None:
        return surfaces, flags

    longest_line = max((len(line) for line in head.splitlines()), default=0)
    if longest_line > MINIFIED_LINE:
        flags.append(f"line of {longest_line} characters (minified or embedded data)")
    encoded = max((len(m.group()) for m in ENCODED_RUN.finditer(head)), default=0)
    if encoded:
        flags.append(f"encoded-looking literal of {encoded} characters")

    text = head.decode("utf-8", errors="replace")
    if path.suffix == ".pth":
        executable = [
            line
            for line in text.splitlines()
            if line.startswith(("import ", "import\t"))
        ]
        if executable:
            surfaces.append(f"{len(executable)} executable .pth line(s)")
    elif path.name == "package.json" and complete:
        try:
            scripts = json.loads(text).get("scripts", {})
        except (json.JSONDecodeError, AttributeError):
            flags.append("package.json does not parse")
        else:
            hooks = (
                {k: v for k, v in scripts.items() if k in NPM_LIFECYCLE}
                if isinstance(scripts, dict)
                else {}
            )
            surfaces.extend(f"lifecycle {k}: {str(v)[:200]}" for k, v in hooks.items())
    elif path.name == "pyproject.toml" and complete:
        try:
            build = tomllib.loads(text).get("build-system", {})
        except tomllib.TOMLDecodeError:
            flags.append("pyproject.toml does not parse")
        else:
            if build.get("build-backend"):
                surfaces.append(f"build-backend {build['build-backend']}")
            if build.get("backend-path"):
                surfaces.append(f"in-tree backend-path {build['backend-path']}")
    return surfaces, flags


def scan_tree(root: Path) -> dict[PurePosixPath, FileFacts]:
    """Record facts about every regular file under a staged tree."""
    facts = {}
    for path in sorted(
        p for p in root.rglob("*") if p.is_file() and not p.is_symlink()
    ):
        relative = PurePosixPath(path.relative_to(root).as_posix())
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            head = handle.read(SCAN_BYTES)
            digest.update(head)
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        size = path.stat().st_size
        surfaces, flags = content_facts(
            relative, head=head, complete=size <= SCAN_BYTES
        )
        facts[relative] = FileFacts(
            path=relative,
            size=size,
            sha256=digest.hexdigest(),
            surfaces=surface_kinds(relative) + surfaces,
            flags=flags,
        )
    return facts


def strip_common_root(
    facts: dict[PurePosixPath, FileFacts],
) -> dict[PurePosixPath, FileFacts]:
    """Drop a top-level directory every path shares, such as `pkg-1.2.3/`."""
    tops = {path.parts[0] for path in facts if len(path.parts) > 1}
    if len(tops) != 1 or any(len(path.parts) == 1 for path in facts):
        return facts
    return {PurePosixPath(*path.parts[1:]): fact for path, fact in facts.items()}


def bullet_list(lines: Sequence[str]) -> list[str]:
    """Render lines as Markdown bullets, truncated to LIST_LIMIT."""
    rendered = [f"- {line}" for line in lines[:LIST_LIMIT]]
    if len(lines) > LIST_LIMIT:
        rendered.append(f"- … {len(lines) - LIST_LIMIT} more not listed")
    return rendered or ["- none"]


def tree_section(name: str, facts: dict[PurePosixPath, FileFacts]) -> list[str]:
    """Render totals, surfaces and flags for one tree."""
    suffixes = Counter(path.suffix or path.name for path in facts)
    out = [
        f"## {name}",
        "",
        f"{len(facts)} files, {sum(f.size for f in facts.values())} bytes.",
        "Most common types: "
        + ", ".join(f"`{s}` {n}" for s, n in suffixes.most_common(15))
        + ".",
        "",
        "### Execution surfaces",
        "",
        *bullet_list(
            [
                f"`{f.path}` — {'; '.join(f.surfaces)}"
                for f in facts.values()
                if f.surfaces
            ]
        ),
        "",
        "### Flagged files",
        "",
        *bullet_list(
            [f"`{f.path}` — {'; '.join(f.flags)}" for f in facts.values() if f.flags]
        ),
        "",
    ]
    return out


def diff_section(
    target: dict[PurePosixPath, FileFacts], baseline: dict[PurePosixPath, FileFacts]
) -> list[str]:
    """Render the files added, removed and changed relative to the baseline."""
    new, old = strip_common_root(target), strip_common_root(baseline)

    def describe(path: PurePosixPath) -> str:
        fact = new[path]
        notes = fact.surfaces + fact.flags
        return f"`{path}`" + (f" — {'; '.join(notes)}" if notes else "")

    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(p for p in set(new) & set(old) if new[p].sha256 != old[p].sha256)
    surface_first = sorted(
        added + changed,
        key=lambda p: (not new[p].surfaces and not new[p].flags, str(p)),
    )
    return [
        "## Changes from baseline",
        "",
        f"{len(added)} added, {len(removed)} removed, {len(changed)} changed.",
        "",
        "### Added or changed, surfaces and flagged files first",
        "",
        *bullet_list(
            [
                ("added " if p in added else "changed ") + describe(p)
                for p in surface_first
            ]
        ),
        "",
        "### Removed",
        "",
        *bullet_list([f"`{p}`" for p in removed]),
        "",
    ]


def main(argv: Sequence[str]) -> int:
    """Run the command line.

    Args:
        argv: The arguments after the program name.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("review_dir", type=Path)
    parser.add_argument(
        "--manifest", type=Path, help="write a SHA-256 manifest (TSV) here"
    )
    args = parser.parse_args(argv)
    target_dir, baseline_dir = args.review_dir / "target", args.review_dir / "baseline"
    if not target_dir.is_dir():
        print(f"inventory.py: {target_dir} is not a directory", file=sys.stderr)
        return 2

    target = scan_tree(target_dir)
    baseline = scan_tree(baseline_dir) if baseline_dir.is_dir() else None
    lines = ["# Inventory", "", *tree_section("target/", target)]
    if baseline is not None:
        lines += [*tree_section("baseline/", baseline), *diff_section(target, baseline)]
    print("\n".join(lines))

    if args.manifest is not None:
        with args.manifest.open("x") as manifest:
            for tree, facts in (("target", target), ("baseline", baseline or {})):
                for fact in facts.values():
                    manifest.write(f"{fact.sha256}\t{fact.size}\t{tree}/{fact.path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
