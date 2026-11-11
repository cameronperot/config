#!/usr/bin/env python3
"""Download an artifact for malicious-code review without executing anything.

Sources:

    acquire.py github OWNER/REPO REF --out DIR
    acquire.py pypi NAME VERSION --out DIR [--file FILENAME]...
    acquire.py npm NAME VERSION --out DIR
    acquire.py url HTTPS_URL --out DIR

Artifacts come straight from the forge or registry over HTTPS: never through
git, pip or npm, whose download paths can run hooks or build backends. A
mutable GitHub ref is resolved to a commit first, registry digests are checked
against the downloaded bytes, and one JSON record per artifact is printed to
stdout. The exit status is 0 on success, 1 on a failed download or digest
mismatch, and 2 on a usage error. Standard library only; no credentials are
read or sent, so only public sources work.
"""

import argparse
import base64
import hashlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

TIMEOUT = 30.0
DEFAULT_MAX_BYTES = 200 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024
USER_AGENT = "malicious-code-review/1"


class AcquireError(Exception):
    """A download or verification failure to report and exit on."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects that would leave HTTPS."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise AcquireError(
                f"refusing redirect from {req.full_url} to non-HTTPS {newurl}"
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(HttpsOnlyRedirect)


def open_url(url: str, accept: str = "*/*"):
    """Open an HTTPS URL with the shared timeout and redirect policy.

    Args:
        url: The URL to open.
        accept: The Accept header to send.

    Returns:
        The open HTTP response.

    Raises:
        AcquireError: When the URL is not HTTPS or the request fails.
    """
    if urllib.parse.urlsplit(url).scheme != "https":
        raise AcquireError(f"refusing non-HTTPS URL {url}")
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": accept}
    )
    try:
        return OPENER.open(request, timeout=TIMEOUT)
    except urllib.error.HTTPError as err:
        raise AcquireError(f"{url}: HTTP {err.code}", status=err.code) from err
    except urllib.error.URLError as err:
        raise AcquireError(f"{url}: {err.reason}") from err


def fetch_json(url: str) -> dict:
    """Fetch and decode a JSON document.

    Args:
        url: The HTTPS URL of the document.

    Returns:
        The decoded JSON object.

    Raises:
        AcquireError: When the request fails or the body is not JSON.
    """
    with open_url(url, accept="application/json") as response:
        try:
            return json.load(response)
        except json.JSONDecodeError as err:
            raise AcquireError(f"{url}: response is not JSON ({err})") from err


def url_exists(url: str) -> bool:
    """Report whether an HTTPS URL answers 200, treating 404 as absent.

    Args:
        url: The HTTPS URL to probe.

    Returns:
        True for a successful response, False for 404.

    Raises:
        AcquireError: On any other failure.
    """
    try:
        with open_url(url):
            return True
    except AcquireError as err:
        if err.status == 404:
            return False
        raise


def download(url: str, destination: Path, max_bytes: int) -> tuple[str, str, int]:
    """Stream a URL to a new file, hashing as it goes.

    Args:
        url: The HTTPS URL to download.
        destination: The file to create; it must not exist.
        max_bytes: The size above which the download is abandoned.

    Returns:
        The SHA-256 hex digest, the SHA-512 hex digest and the size in bytes.

    Raises:
        AcquireError: When the request fails or the body exceeds max_bytes.
    """
    sha256 = hashlib.sha256()
    sha512 = hashlib.sha512()
    size = 0
    with open_url(url) as response, destination.open("xb") as out:
        while chunk := response.read(CHUNK_BYTES):
            size += len(chunk)
            if size > max_bytes:
                out.close()
                destination.unlink()
                raise AcquireError(f"{url}: larger than {max_bytes} bytes, abandoned")
            sha256.update(chunk)
            sha512.update(chunk)
            out.write(chunk)
    return sha256.hexdigest(), sha512.hexdigest(), size


def safe_filename(name: str) -> str:
    """Reduce a remote file name to one safe path component.

    Args:
        name: The name taken from a URL or registry record.

    Returns:
        The final component with anything outside a conservative character set replaced.

    Raises:
        AcquireError: When nothing usable remains.
    """
    leaf = name.rsplit("/", 1)[-1]
    cleaned = "".join(
        ch if ch.isalnum() or ch in "._-+" else "_" for ch in leaf
    ).lstrip(".")
    if not cleaned:
        raise AcquireError(f"cannot derive a file name from {name!r}")
    return cleaned


def now() -> str:
    """Return the current UTC time in ISO 8601 form."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def acquire_github(repo: str, ref: str, out: Path, max_bytes: int) -> list[dict]:
    """Resolve a GitHub ref to a commit and download that commit's tarball.

    Args:
        repo: The repository as OWNER/NAME.
        ref: A branch, tag or commit.
        out: The directory to download into.
        max_bytes: The size limit for the download.

    Returns:
        One artifact record.

    Raises:
        AcquireError: When the repository or ref cannot be resolved or downloaded.
    """
    owner, _, name = repo.partition("/")
    if not owner or not name or "/" in name:
        raise AcquireError(f"expected OWNER/REPO, got {repo!r}")
    quoted = f"{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}"
    quoted_ref = urllib.parse.quote(ref, safe="")
    commit_url = f"https://api.github.com/repos/{quoted}/commits/{quoted_ref}"
    with open_url(commit_url, accept="application/vnd.github.sha") as response:
        commit = response.read(100).decode("ascii", errors="replace").strip()
    if len(commit) != 40 or any(ch not in "0123456789abcdef" for ch in commit):
        raise AcquireError(f"{commit_url}: unexpected commit id {commit!r}")
    url = f"https://codeload.github.com/{quoted}/tar.gz/{commit}"
    path = out / safe_filename(f"{name}-{commit}.tar.gz")
    sha256, _, size = download(url, destination=path, max_bytes=max_bytes)
    return [
        {
            "source": "github",
            "repository": repo,
            "requested_ref": ref,
            "commit": commit,
            "url": url,
            "file": str(path),
            "sha256": sha256,
            "size": size,
            "acquired_at": now(),
        }
    ]


def select_pypi_files(files: Sequence[dict], wanted: Sequence[str]) -> list[dict]:
    """Choose which files of a PyPI release to download.

    Args:
        files: The release's file records from the PyPI JSON API.
        wanted: Explicit file names; empty selects the sdist and any pure-Python wheel.

    Returns:
        The selected file records.

    Raises:
        AcquireError: When a wanted file is missing or there is no default choice.
    """
    by_name = {record["filename"]: record for record in files}
    if wanted:
        missing = [name for name in wanted if name not in by_name]
        if missing:
            raise AcquireError(
                f"not in this release: {', '.join(missing)}; "
                f"available: {', '.join(by_name)}"
            )
        return [by_name[name] for name in wanted]
    selected = [
        record
        for record in files
        if record["packagetype"] == "sdist"
        or record["filename"].endswith("-none-any.whl")
    ]
    if not selected:
        raise AcquireError(
            "no sdist or pure-Python wheel; "
            f"choose with --file from: {', '.join(by_name)}"
        )
    return selected


def previous_release(releases: dict, version: str) -> tuple[str | None, str | None]:
    """Find the release uploaded most recently before a version.

    Args:
        releases: The project JSON's mapping of version to file records.
        version: The version under review.

    Returns:
        The previous version and its first upload time, or None for both.
    """

    def first_upload(records: list[dict]) -> str | None:
        times = [record["upload_time_iso_8601"] for record in records]
        return min(times) if times else None

    current = first_upload(releases.get(version, []))
    earlier = [
        (uploaded, candidate)
        for candidate, records in releases.items()
        if candidate != version
        and (uploaded := first_upload(records)) is not None
        and (current is None or uploaded < current)
    ]
    if not earlier:
        return None, None
    uploaded, candidate = max(earlier)
    return candidate, uploaded


def acquire_pypi(
    name: str, version: str, out: Path, wanted: Sequence[str], max_bytes: int
) -> list[dict]:
    """Download files of one PyPI release and check them against PyPI's digests.

    Args:
        name: The project name.
        version: The exact version.
        out: The directory to download into.
        wanted: Explicit file names, or empty for the default selection.
        max_bytes: The size limit per download.

    Returns:
        One artifact record per file.

    Raises:
        AcquireError: When the release or a file cannot be fetched or fails its digest.
    """
    quoted = urllib.parse.quote(name, safe="")
    project = fetch_json(f"https://pypi.org/pypi/{quoted}/json")
    quoted_version = urllib.parse.quote(version, safe="")
    release = fetch_json(f"https://pypi.org/pypi/{quoted}/{quoted_version}/json")
    previous_version, previous_upload = previous_release(
        project.get("releases", {}), version
    )
    records = []
    for record in select_pypi_files(release["urls"], wanted=wanted):
        path = out / safe_filename(record["filename"])
        sha256, _, size = download(record["url"], destination=path, max_bytes=max_bytes)
        if sha256 != record["digests"]["sha256"]:
            raise AcquireError(
                f"{record['filename']}: sha256 {sha256} does not match "
                f"PyPI's {record['digests']['sha256']}"
            )
        quoted_file = urllib.parse.quote(record["filename"], safe="")
        provenance_url = f"https://pypi.org/integrity/{quoted}/{quoted_version}/{quoted_file}/provenance"
        records.append(
            {
                "source": "pypi",
                "name": name,
                "version": version,
                "file": str(path),
                "url": record["url"],
                "packagetype": record["packagetype"],
                "sha256": sha256,
                "sha256_matches_registry": True,
                "size": size,
                "uploaded_at": record["upload_time_iso_8601"],
                "yanked": record.get("yanked", False),
                "attestations": url_exists(provenance_url),
                "previous_version": previous_version,
                "previous_uploaded_at": previous_upload,
                "release_count": len(project.get("releases", {})),
                "declared_project_urls": release["info"].get("project_urls"),
                "acquired_at": now(),
            }
        )
    return records


def npm_integrity_matches(integrity: str | None, sha512_hex: str) -> bool | None:
    """Compare npm's SRI integrity string with a computed SHA-512 digest.

    Args:
        integrity: The registry's `dist.integrity` value, if any.
        sha512_hex: The SHA-512 hex digest of the downloaded bytes.

    Returns:
        True or False for a sha512 integrity value, None when there is none to compare.
    """
    if not integrity or not integrity.startswith("sha512-"):
        return None
    return base64.b64decode(integrity.removeprefix("sha512-")).hex() == sha512_hex


def acquire_npm(name: str, version: str, out: Path, max_bytes: int) -> list[dict]:
    """Download one npm package version's tarball and check its integrity.

    Args:
        name: The package name, scoped or not.
        version: The exact version.
        out: The directory to download into.
        max_bytes: The size limit for the download.

    Returns:
        One artifact record.

    Raises:
        AcquireError: When the version is missing, the download fails or the
            integrity check fails.
    """
    document = fetch_json(
        f"https://registry.npmjs.org/{urllib.parse.quote(name, safe='@')}"
    )
    manifest = document.get("versions", {}).get(version)
    if manifest is None:
        raise AcquireError(f"{name}@{version} is not in the registry")
    times = document.get("time", {})
    published = {v: t for v, t in times.items() if v in document["versions"]}
    earlier = sorted(
        (t, v) for v, t in published.items() if t < published.get(version, "")
    )
    previous_version = earlier[-1][1] if earlier else None
    previous_manifest = (
        document["versions"].get(previous_version, {}) if previous_version else {}
    )

    dist = manifest["dist"]
    path = out / safe_filename(dist["tarball"])
    sha256, sha512, size = download(
        dist["tarball"], destination=path, max_bytes=max_bytes
    )
    integrity_ok = npm_integrity_matches(dist.get("integrity"), sha512_hex=sha512)
    if integrity_ok is False:
        raise AcquireError(
            f"{dist['tarball']}: sha512 does not match the registry's integrity value"
        )
    lifecycle = (
        "preinstall",
        "install",
        "postinstall",
        "prepare",
        "prepack",
        "postpack",
    )
    return [
        {
            "source": "npm",
            "name": name,
            "version": version,
            "file": str(path),
            "url": dist["tarball"],
            "sha256": sha256,
            "integrity_matches_registry": integrity_ok,
            "size": size,
            "published_at": published.get(version),
            "publisher": (manifest.get("_npmUser") or {}).get("name"),
            "previous_version": previous_version,
            "previous_publisher": (previous_manifest.get("_npmUser") or {}).get("name"),
            "attestations": bool(dist.get("attestations")),
            "install_scripts": {
                k: v for k, v in manifest.get("scripts", {}).items() if k in lifecycle
            },
            "previous_install_scripts": {
                k: v
                for k, v in previous_manifest.get("scripts", {}).items()
                if k in lifecycle
            },
            "declared_repository": manifest.get("repository"),
            "acquired_at": now(),
        }
    ]


def acquire_url(url: str, out: Path, max_bytes: int) -> list[dict]:
    """Download a single file from an HTTPS URL.

    Args:
        url: The HTTPS URL.
        out: The directory to download into.
        max_bytes: The size limit for the download.

    Returns:
        One artifact record.

    Raises:
        AcquireError: When the download fails.
    """
    path = out / safe_filename(urllib.parse.urlsplit(url).path or "download")
    sha256, _, size = download(url, destination=path, max_bytes=max_bytes)
    return [
        {
            "source": "url",
            "url": url,
            "file": str(path),
            "sha256": sha256,
            "size": size,
            "acquired_at": now(),
        }
    ]


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse the command line.

    Args:
        argv: The arguments after the program name.

    Returns:
        The parsed arguments.
    """
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--out", type=Path, required=True, help="existing directory to download into"
    )
    parser.add_argument(
        "--max-bytes", type=int, default=DEFAULT_MAX_BYTES, help="per-file size limit"
    )
    sources = parser.add_subparsers(dest="source", required=True)
    github = sources.add_parser("github")
    github.add_argument("repo")
    github.add_argument("ref")
    pypi = sources.add_parser("pypi")
    pypi.add_argument("name")
    pypi.add_argument("version")
    pypi.add_argument(
        "--file", action="append", default=[], help="release file name; repeatable"
    )
    npm = sources.add_parser("npm")
    npm.add_argument("name")
    npm.add_argument("version")
    url = sources.add_parser("url")
    url.add_argument("url")
    return parser.parse_args(argv)


def main(argv: Sequence[str]) -> int:
    """Run the command line.

    Args:
        argv: The arguments after the program name.

    Returns:
        The process exit status.
    """
    args = parse_args(argv)
    if not args.out.is_dir():
        print(f"acquire.py: --out {args.out} is not a directory", file=sys.stderr)
        return 2
    try:
        match args.source:
            case "github":
                records = acquire_github(
                    args.repo, ref=args.ref, out=args.out, max_bytes=args.max_bytes
                )
            case "pypi":
                records = acquire_pypi(
                    args.name,
                    version=args.version,
                    out=args.out,
                    wanted=args.file,
                    max_bytes=args.max_bytes,
                )
            case "npm":
                records = acquire_npm(
                    args.name,
                    version=args.version,
                    out=args.out,
                    max_bytes=args.max_bytes,
                )
            case "url":
                records = acquire_url(args.url, out=args.out, max_bytes=args.max_bytes)
    except (AcquireError, OSError) as err:
        print(f"acquire.py: {err}", file=sys.stderr)
        return 1
    except KeyError as err:
        print(
            f"acquire.py: unexpected registry response, missing field {err}",
            file=sys.stderr,
        )
        return 1
    for record in records:
        print(json.dumps(record))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
