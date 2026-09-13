---
name: changelog
description: Maintains CHANGELOG.md files in Keep a Changelog format — creates changelogs, drafts entries, cuts releases. Use only when explicitly asked to update a changelog, write release notes, or cut a release. Do not invoke proactively after user-facing changes.
disable-model-invocation: true
---

# Changelog

Maintain `CHANGELOG.md` following [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Arguments

Trailing input after `/skill:changelog` selects the workflow:

- `init` → Initialize.
- `release`, optionally with a version (e.g. `release 2.0.0`) → Cut a release.
- Any other text → a description of changes for Add entries.

Conversational requests map the same way. With no input, default to Add entries. A request only to draft release notes produces notes in the requested destination or conversation; it does not implicitly modify CHANGELOG.md or cut a release.

## Format rules

- Changelogs are for humans: describe the user-facing impact of a change, not its implementation. Never paste commit messages or `git log` output as entries.
- Keep one `## [Unreleased]` section at the top; released versions follow in reverse chronological order.
- Version headings are `## [X.Y.Z] - YYYY-MM-DD`. Dates are ISO 8601; get today's date with `date +%F`, never from memory.
- Group entries under these headings in this order, omitting empty ones: `### Added`, `### Changed`, `### Deprecated`, `### Removed`, `### Fixed`, `### Security`.
- One change per bullet, verb-first sentence style ("Added retry logic to the order client"). Reference issue or PR numbers where they help readers.
- Prefix breaking changes with `**Breaking:**`; use the project's version policy, with a major bump for incompatible public API changes at or after 1.0.0.
- Version headings are markdown link references. Maintain the link block at the bottom of the file: `[Unreleased]` compares the latest tag to `HEAD`, each version compares to its predecessor, and the oldest version links to its release tag. Derive URLs from the repository's actual remote and tag naming convention, preserving existing links. Convert SSH remotes to the host's web URL; do not assume every host uses GitHub compare paths. If no valid link can be derived, omit that new link instead of inventing one. Before the first release, leave Unreleased unlinked if no comparison base exists.
- Keep yanked releases listed and mark them: `## [0.4.0] - 2026-01-10 [YANKED]`.
- Record every deprecation under `### Deprecated` — it is the warning users need before a removal.
- Never rewrite released sections except to fix factual errors or add `[YANKED]`.

## Add entries

1. Locate the changelog requested by the user or used by the project; default to root `CHANGELOG.md`. If it is missing and an update was requested, initialize it.
2. Determine changes from the user's description, session edits, or history and diffs since the relevant release. Resolve the baseline from the latest release for this package; the nearest tag from `git describe --tags --abbrev=0` may belong to another package or release line. If no release baseline exists, inspect available history and existing entries; ask only if the intended range remains material and unclear.
3. Merge each change into a user-facing entry under the correct category in `[Unreleased]`, avoiding duplicates. Skip internal-only noise (CI tweaks, refactors with no observable effect) unless the user asks to include it.

## Cut a release

1. Confirm `[Unreleased]` is non-empty and covers everything since the last tag; run Add entries for anything missing.
2. Use the version the user named, checking for duplicate or non-increasing versions and policy conflicts before editing. Otherwise derive the bump from compatibility impact, not category headings alone: incompatible public API changes → major, compatible additions or public deprecations → minor, compatible fixes → patch. Follow the project's pre-1.0 and prerelease policy; ask if an initial version or unresolved compatibility choice would change the release.
3. Rename `[Unreleased]` to `[X.Y.Z] - <today>` and insert a fresh `## [Unreleased]` heading above it.
4. Update the link block: add the new version's compare link and repoint `[Unreleased]` to compare from the new tag.
5. Do not tag, commit, or publish unless asked.

## Initialize

Create `CHANGELOG.md` at the repo root with the preamble and empty `[Unreleased]` section shown in the example.
Backfill releases only when requested. Use recorded release dates where available; an annotated tag date or tagged commit date is only a fallback, and `git log -1 --format=%as <tag>` is the commit author date, not necessarily the release date. Identify inferred dates rather than presenting them as verified.

## Example

```markdown
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.0] - 2026-08-19

### Added

- Added a `--dry-run` flag to `sync` that reports pending changes without applying them ([#42](https://github.com/acme/sync/pull/42)).

### Changed

- Changed the default sync interval from 60s to 30s.

### Fixed

- Fixed a crash when the config file contains unknown keys.

## [1.0.0] - 2026-07-02

### Added

- Initial release.

[Unreleased]: https://github.com/acme/sync/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/acme/sync/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/acme/sync/releases/tag/v1.0.0
```

Rewriting a commit into an entry:

| Commit message | Changelog entry |
|---|---|
| `fix(ws): reconnect on 1006, bump ping interval, refactor handler` | Fixed dropped websocket connections not reconnecting after abnormal closes. |

## Existing non-standard changelogs

If the repo already maintains its changelog in a different consistent format, follow that format and tell the user, instead of converting it unasked.

## Completion

Inspect the final diff: entries match the evidence and requested range, Unreleased appears once, categories and versions are ordered, links use the correct tags, and released history is preserved except for authorized corrections. Report the file or notes produced, release version if applicable, and any uncertain dates or missing history. This skill does not itself authorize tags, commits, or publication.
