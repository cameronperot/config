#!/usr/bin/env python3
"""Compare dependency lockfiles and look up known-malicious packages in OSV.

    deps.py diff OLD_LOCK NEW_LOCK [--osv]
    deps.py osv ECOSYSTEM NAME VERSION [NAME VERSION]...

`diff` reads two uv.lock or two package-lock.json (lockfileVersion 2 or 3)
files without resolving or installing anything, and prints Markdown: packages
added, removed and re-versioned, changed sources, and new non-registry
sources (git, URL, path). With `--osv`, every added or re-versioned package
from the public registry (pypi.org, registry.npmjs.org) is queried at OSV.dev,
and `MAL-` records (the OpenSSF malicious-packages feed) are reported apart
from ordinary vulnerability advisories. Packages from any other source are
never sent to OSV. `osv` queries packages given on the command line;
ECOSYSTEM is an OSV ecosystem such as PyPI or npm.

An OSV match is a report about the package and version, not proof about any
particular downloaded file; an empty result means no record was returned, not
that the package is safe. Exit status 0 on success, 1 when a lockfile cannot
be read or OSV cannot be queried, 2 on a usage error. Standard library only.
"""

import argparse
import json
import sys
import tomllib
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

OSV_BATCH_URL = "https://api.osv.dev/v1/querybatch"
OSV_BATCH_SIZE = 1000
TIMEOUT = 30.0
PUBLIC_PYPI = "https://pypi.org/simple"
PUBLIC_NPM = "https://registry.npmjs.org/"


class DepsError(Exception):
    """A failure to report and exit on."""


@dataclass(frozen=True, order=True)
class Locked:
    """One locked package version and where it comes from."""

    name: str
    version: str
    source: str
    public: bool


def uv_source(source: dict) -> tuple[str, bool]:
    """Describe a uv.lock source table and whether it is the public PyPI index."""
    kind, value = next(iter(source.items()), ("unknown", ""))
    return f"{kind} {value}", kind == "registry" and value.rstrip("/") == PUBLIC_PYPI


def read_uv_lock(path: Path) -> tuple[str, set[Locked]]:
    """Read the packages of a uv.lock file."""
    document = tomllib.loads(path.read_text())
    packages = set()
    for package in document.get("package", []):
        source, public = uv_source(package.get("source", {}))
        packages.add(
            Locked(
                package["name"],
                version=package.get("version", ""),
                source=source,
                public=public,
            )
        )
    return "PyPI", packages


def read_package_lock(path: Path) -> tuple[str, set[Locked]]:
    """Read the installed packages of a package-lock.json file.

    Raises:
        DepsError: For lockfileVersion 1, which has no `packages` map.
    """
    document = json.loads(path.read_text())
    if "packages" not in document:
        raise DepsError(
            f"{path}: lockfileVersion {document.get('lockfileVersion')} "
            "is not supported; need 2 or 3"
        )
    packages = set()
    for location, entry in document["packages"].items():
        if not location or entry.get("link"):
            continue
        name = entry.get("name") or location.rsplit("node_modules/", 1)[-1]
        resolved = entry.get("resolved", "")
        source = resolved or "unknown (no resolved URL)"
        packages.add(
            Locked(
                name,
                version=entry.get("version", ""),
                source=source,
                public=resolved.startswith(PUBLIC_NPM),
            )
        )
    return "npm", packages


def read_lock(path: Path) -> tuple[str, set[Locked]]:
    """Read a lockfile by its name.

    Raises:
        DepsError: For an unsupported file name.
    """
    if path.name == "uv.lock":
        return read_uv_lock(path)
    if path.name == "package-lock.json":
        return read_package_lock(path)
    raise DepsError(f"{path}: expected uv.lock or package-lock.json")


def osv_query(ecosystem: str, packages: Sequence[tuple[str, str]]) -> list[list[str]]:
    """Query OSV for the record IDs affecting each package version.

    Args:
        ecosystem: The OSV ecosystem name.
        packages: Pairs of package name and version.

    Returns:
        The record IDs for each pair, in order.

    Raises:
        DepsError: When OSV cannot be reached or answers unexpectedly.
    """
    results: list[list[str]] = []
    for start in range(0, len(packages), OSV_BATCH_SIZE):
        batch = packages[start : start + OSV_BATCH_SIZE]
        body = {
            "queries": [
                {"package": {"name": n, "ecosystem": ecosystem}, "version": v}
                for n, v in batch
            ]
        }
        request = urllib.request.Request(
            OSV_BATCH_URL,
            data=json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "malicious-code-review/1",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                answer = json.load(response)
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as err:
            raise DepsError(f"OSV query failed: {err}") from err
        batch_results = answer.get("results", [])
        if len(batch_results) != len(batch):
            raise DepsError(
                f"OSV returned {len(batch_results)} results for {len(batch)} queries"
            )
        for result in batch_results:
            ids = [vuln["id"] for vuln in result.get("vulns", [])]
            if result.get("next_page_token"):
                ids.append("(more records not fetched)")
            results.append(ids)
    return results


def osv_section(ecosystem: str, packages: Sequence[Locked]) -> list[str]:
    """Render OSV results for public packages, listing the ones not queried.

    Raises:
        DepsError: When OSV cannot be queried.
    """
    public = sorted(p for p in packages if p.public)
    private = sorted(p for p in packages if not p.public)
    ids = osv_query(ecosystem, [(p.name, p.version) for p in public])
    malicious = [
        f"**{p.name} {p.version}**: {', '.join(i for i in r if i.startswith('MAL-'))}"
        for p, r in zip(public, ids, strict=True)
        if any(i.startswith("MAL-") for i in r)
    ]
    advisories = [
        f"{p.name} {p.version}: {', '.join(i for i in r if not i.startswith('MAL-'))}"
        for p, r in zip(public, ids, strict=True)
        if any(not i.startswith("MAL-") for i in r)
    ]
    return [
        "## OSV",
        "",
        f"Queried {len(public)} public package versions.",
        "",
        "### Known-malicious records (MAL-)",
        "",
        *([f"- {line}" for line in malicious] or ["- no MAL- record returned"]),
        "",
        "### Vulnerability advisories",
        "",
        *([f"- {line}" for line in advisories] or ["- none returned"]),
        "",
        "### Not queried (non-public source)",
        "",
        *([f"- {p.name} {p.version} ({p.source})" for p in private] or ["- none"]),
        "",
    ]


def diff(old_path: Path, new_path: Path, with_osv: bool) -> list[str]:
    """Render the differences between two lockfiles.

    Raises:
        DepsError: For unreadable or mismatched lockfiles, or a failed OSV query.
    """
    old_ecosystem, old = read_lock(old_path)
    new_ecosystem, new = read_lock(new_path)
    if old_ecosystem != new_ecosystem:
        raise DepsError("both lockfiles must be the same kind")
    old_versions = {(p.name, p.version): p for p in old}
    old_names = {p.name for p in old}
    new_names = {p.name for p in new}

    added = sorted(p for p in new if p.name not in old_names)
    removed = sorted(p for p in old if p.name not in new_names)
    reversioned = sorted(
        p
        for p in new
        if p.name in old_names and (p.name, p.version) not in old_versions
    )
    resourced = sorted(
        p
        for p in new
        if (p.name, p.version) in old_versions
        and old_versions[p.name, p.version].source != p.source
    )
    nonpublic = sorted(p for p in added + reversioned + resourced if not p.public)
    previous = {}
    for p in old:
        previous.setdefault(p.name, []).append(p.version)

    lines = [
        f"# Dependency changes: `{old_path}` → `{new_path}`",
        "",
        f"{len(added)} added, {len(removed)} removed, {len(reversioned)} re-versioned, "
        f"{len(resourced)} with a changed source.",
        "",
        "## Added",
        "",
        *([f"- {p.name} {p.version} ({p.source})" for p in added] or ["- none"]),
        "",
        "## Re-versioned",
        "",
        *(
            [
                f"- {p.name} {', '.join(sorted(previous[p.name]))} → "
                f"{p.version} ({p.source})"
                for p in reversioned
            ]
            or ["- none"]
        ),
        "",
        "## Same version, changed source",
        "",
        *(
            [
                f"- {p.name} {p.version}: "
                f"{old_versions[p.name, p.version].source} → {p.source}"
                for p in resourced
            ]
            or ["- none"]
        ),
        "",
        "## Removed",
        "",
        *([f"- {p.name} {p.version}" for p in removed] or ["- none"]),
        "",
        "## New or changed entries from a non-public source",
        "",
        *([f"- {p.name} {p.version} ({p.source})" for p in nonpublic] or ["- none"]),
        "",
    ]
    if with_osv:
        lines += osv_section(new_ecosystem, packages=added + reversioned + resourced)
    return lines


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
    commands = parser.add_subparsers(dest="command", required=True)
    diff_parser = commands.add_parser("diff")
    diff_parser.add_argument("old", type=Path)
    diff_parser.add_argument("new", type=Path)
    diff_parser.add_argument(
        "--osv",
        action="store_true",
        help="query OSV for added and re-versioned public packages",
    )
    osv_parser = commands.add_parser("osv")
    osv_parser.add_argument("ecosystem")
    osv_parser.add_argument("packages", nargs="+", metavar="NAME VERSION")
    args = parser.parse_args(argv)

    try:
        if args.command == "diff":
            lines = diff(args.old, new_path=args.new, with_osv=args.osv)
        else:
            if len(args.packages) % 2:
                print("deps.py: osv takes NAME VERSION pairs", file=sys.stderr)
                return 2
            pairs = list(zip(args.packages[::2], args.packages[1::2], strict=True))
            packages = [
                Locked(name, version=version, source="command line", public=True)
                for name, version in pairs
            ]
            lines = osv_section(args.ecosystem, packages=packages)
    except (
        DepsError,
        OSError,
        tomllib.TOMLDecodeError,
        json.JSONDecodeError,
        KeyError,
    ) as err:
        print(f"deps.py: {err}", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
