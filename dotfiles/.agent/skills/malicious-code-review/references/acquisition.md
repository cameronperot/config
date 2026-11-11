# Acquisition

How to get each kind of target into `$WORK/review` with a pinned identity and without executing it.
`S` below is this skill's `scripts/` directory as an absolute path; every script runs as `python3 -I "$S/<script>.py"`.

## Contents

- [Per input type](#per-input-type)
- [Lockfile triage](#lockfile-triage)
- [Failures](#failures)

## Per input type

| Input | Target | Baseline |
|---|---|---|
| Local directory | `stage.py --dir PATH "$WORK/review/target"` | Optional: the previously reviewed copy, staged the same way into `baseline` |
| GitHub repo at a branch, tag or commit | `acquire.py --out "$WORK/downloads" github OWNER/REPO REF`, then stage the tarball | The previously accepted commit or tag, the same way |
| GitHub PR | Head: the PR's `head.repo.full_name` at `head.sha` | Base: `base.repo.full_name` at `base.sha` |
| PyPI release | `acquire.py --out "$WORK/downloads" pypi NAME VERSION`: the sdist and any pure-Python wheel; add `--file FILENAME` per platform wheel the user installs | The previous version (`previous_version` in the record) or the one the user had |
| npm version | `acquire.py --out "$WORK/downloads" npm NAME VERSION` | The previous version (`previous_version` in the record) or the one the user had |
| Lockfile bump | `deps.py diff OLD_LOCK NEW_LOCK --osv`, then each selected package as a PyPI or npm release | Each package's old version from the old lockfile |
| Installer URL or `curl ... \| sh` | `acquire.py --out "$WORK/downloads" url URL` on the literal URL only; then `mkdir "$WORK/single" && cp FILE "$WORK/single/"` and `stage.py --dir "$WORK/single" "$WORK/review/target"` | None |

Notes:

- A PR's numbers come from the public API: `curl -fsSL https://api.github.com/repos/OWNER/REPO/pulls/N | jq '{base: [.base.repo.full_name, .base.sha], head: [.head.repo.full_name, .head.sha]}'`. A fork PR's head lives in the fork.
- An installer command is text: read the URL out of it without evaluating `$(...)`, variables or redirects, and never pipe it anywhere. Payloads the installer downloads in turn are listed as gaps for the user to approve one by one.
- Prefer the artifact the user actually installs. A wheel and its sdist can differ, and so can a repository and its published package; reviewing the source repository does not cover the registry artifact.
- `acquire.py` sends no credentials, so private repositories, private registries and internal mirrors fail. Ask the user for a local copy or archive and stage it with `--dir` or as an archive; never put a token into a URL.
- A dependency the target pulls in is not reviewed unless it is staged too. Name new transitive and build dependencies as unreviewed scope when there is no budget for them.

## Lockfile triage

Review in depth, in this order, until the user's budget is used; five packages per request unless the user sets another limit:

1. Any package with a `MAL-` record: it is already established; review only to explain behavior when asked.
2. New or changed entries from a non-public source: git, URL, path, or a registry other than pypi.org or registry.npmjs.org.
3. Same version with a changed source.
4. New packages, especially names close to a popular package or with few releases (`release_count`, `published_at` in the acquire record).
5. Re-versioned packages whose new version adds install hooks (npm `install_scripts` versus `previous_install_scripts`), changes publisher (`publisher` versus `previous_publisher`), or loses attestations the previous release had.
6. Remaining re-versioned packages, patch releases before major ones: a patch release that adds a network call or hook is the classic hijack.

These signals prioritize; none is a finding by itself. List every package that was not reviewed in depth in the report.

## Failures

| Failure | Report it as |
|---|---|
| `acquire.py` digest or integrity mismatch | A finding: the registry's bytes and its recorded digest disagree; do not stage the file |
| HTTP 404 for a version | Unavailable artifact; check for yanking or deletion, which is itself worth reporting |
| Rate limit (GitHub HTTP 403) | Gap; retry later or ask for a local copy |
| `stage.py` abandoned at a size or count limit | Gap with the limit hit; raise `--max-bytes`/`--max-files` only with the user's agreement |
| OSV query failed | Gap: "no OSV result"; never "no known-malicious record" |
| Reviewer refused to start | The stated reason; usually a missing `cwd`, or the guard extension is not deployed |
