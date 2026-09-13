/**
 * Guard policy — rule loading and path matching.
 *
 * The three guard extensions (`protected-paths.ts`, `protected-paths-bash.ts`,
 * `permission-gate.ts`) and the `read` guard in `built-in-tool-renderer.ts` are
 * the *mechanism*. Global `~/.pi/agent/guard-rules.json` defines the policy;
 * `<cwd>/.pi/guard-rules.json` may add restrictions but cannot weaken it.
 *
 * Rule classes:
 *
 * | Class                  | Effect                                              |
 * |------------------------|-----------------------------------------------------|
 * | `zeroAccessPaths`      | No read, no write, no bash reference.               |
 * | `zeroAccessAllowPaths` | Exceptions to the above (`.env.example`).           |
 * | `readOnlyPaths`        | Reads fine; write/edit and bash writes blocked.     |
 * | `noDeletePaths`        | Deletion and move-away blocked.                     |
 * | `bashPatterns`         | Regex over the bash command; `ask: true` confirms.  |
 *
 * JSON rather than YAML deliberately: Pi loads extensions through jiti with an
 * alias map covering only `@earendil-works/*` and `typebox`, and `~/.pi/agent`
 * has no `node_modules`. A bare `yaml` import resolves only by accident through
 * Pi's own nested copy, and would disappear the day Pi drops the dependency —
 * taking every guard with it. `JSON.parse` cannot fail to resolve, and it
 * matches `settings.json` / `presets.json` / `models.json` alongside it.
 *
 * This directory has no index.ts and no package.json, so Pi's extension
 * discovery (extensions/*.ts and extensions/*\/index.ts, one level, no
 * recursion) does not try to load it as an extension.
 */

import { existsSync, lstatSync, readFileSync, realpathSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { getAgentDir } from "@earendil-works/pi-coding-agent";

const HOME = homedir();
// This is the launcher's mode indicator, not independent proof of isolation.
const SANDBOX_ACTIVE = process.env.AGENT_SANDBOX_ACTIVE === "1" && !process.env.AGENT_SANDBOX_DISABLE;

export interface BashPattern {
	pattern: string;
	reason: string;
	ask?: boolean;
	sandboxExemption?: "host" | "tmp-cleanup" | "tmp-permissions";
	commandExemption?: "git-index" | "git-dry-run";
}

export interface Rules {
	zeroAccessPaths: string[];
	zeroAccessAllowPaths: string[];
	readOnlyPaths: string[];
	noDeletePaths: string[];
	bashPatterns: BashPattern[];
}

/** Shape of a `guard-block` session entry, appended on every block or confirmation. */
export interface GuardAudit {
	tool: string;
	rule: string;
	action: "blocked" | "blocked_by_user" | "allowed_by_user";
	detail?: string;
}

/**
 * Minimum protection that applies when `guard-rules.json` is missing, malformed,
 * or omits a class. Deliberately much smaller than the shipped policy — it is a
 * floor, not a second copy to keep in sync. Its purpose is that a typo in the
 * policy file degrades protection rather than removing it: a guard that silently
 * allows everything is worse than one that is merely coarse.
 */
const SAFETY_FLOOR: Rules = {
	zeroAccessPaths: [".env", ".env.*", "*.env", "~/.ssh/", "~/.aws/", "~/.gnupg/"],
	zeroAccessAllowPaths: [".env.example", ".env-example"],
	readOnlyPaths: [".git/"],
	noDeletePaths: [".git/"],
	bashPatterns: [
		{
			pattern: "\\brm\\s+(-[^\\s]*)*-[rRf]",
			reason: "rm with recursive or force flags",
			ask: true,
			sandboxExemption: "tmp-cleanup",
		},
		{ pattern: "\\bsudo\\b", reason: "sudo (runs as root)", ask: true, sandboxExemption: "host" },
	],
};

export interface LoadedRules {
	rules: Rules;
	/** Absolute path the policy came from, or "built-in safety floor". */
	source: string;
	/** Set when the policy could not be used as written; surfaced once per cwd. */
	error?: string;
}

const cache = new Map<string, LoadedRules>();
const reported = new Set<string>();

function isStringArray(value: unknown): value is string[] {
	return Array.isArray(value) && value.every((entry) => typeof entry === "string");
}

function isBashPatternArray(value: unknown): value is BashPattern[] {
	return (
		Array.isArray(value) &&
		value.every(
			(entry) =>
				!!entry &&
				typeof entry === "object" &&
				typeof (entry as BashPattern).pattern === "string" &&
				typeof (entry as BashPattern).reason === "string" &&
				((entry as BashPattern).ask === undefined || typeof (entry as BashPattern).ask === "boolean") &&
				((entry as BashPattern).sandboxExemption === undefined ||
					(entry as BashPattern).sandboxExemption === "host" ||
					(entry as BashPattern).sandboxExemption === "tmp-cleanup" ||
					(entry as BashPattern).sandboxExemption === "tmp-permissions") &&
				((entry as BashPattern).commandExemption === undefined ||
					(entry as BashPattern).commandExemption === "git-index" ||
					(entry as BashPattern).commandExemption === "git-dry-run"),
		)
	);
}

/**
 * Merge a parsed policy over the floor. A class the file omits keeps the floor's
 * value, so leaving one out cannot silently disable it; a class the file states
 * replaces the floor's entirely, so it can be narrowed on purpose.
 */
function coerce(parsed: unknown, defaults: Rules = SAFETY_FLOOR): { rules: Rules; problems: string[] } {
	const problems: string[] = [];
	if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
		return { rules: defaults, problems: ["policy is not a JSON object"] };
	}
	const raw = parsed as Record<string, unknown>;
	const rules: Rules = { ...defaults };

	for (const key of ["zeroAccessPaths", "zeroAccessAllowPaths", "readOnlyPaths", "noDeletePaths"] as const) {
		if (raw[key] === undefined) continue;
		if (isStringArray(raw[key])) {
			rules[key] = raw[key];
		} else {
			problems.push(`${key} is not an array of strings`);
		}
	}

	if (raw.bashPatterns !== undefined) {
		if (isBashPatternArray(raw.bashPatterns)) {
			const valid: BashPattern[] = [];
			for (const entry of raw.bashPatterns) {
				try {
					new RegExp(entry.pattern);
					valid.push(entry);
				} catch {
					problems.push(`bashPatterns entry is not a valid regex: ${entry.pattern}`);
				}
			}
			rules.bashPatterns = problems.length > 0 ? [...defaults.bashPatterns, ...valid] : valid;
		} else {
			problems.push("bashPatterns is not an array of {pattern, reason}");
		}
	}

	return { rules, problems };
}

export function getRules(cwd: string): LoadedRules {
	const cached = cache.get(cwd);
	if (cached) return cached;

	const globalFile = join(getAgentDir(), "guard-rules.json");
	const found = existsSync(globalFile) ? globalFile : undefined;

	let loaded: LoadedRules;
	if (!found) {
		loaded = {
			rules: SAFETY_FLOOR,
			source: "built-in safety floor",
			error: `No guard-rules.json at ${globalFile} — falling back to the built-in safety floor.`,
		};
	} else {
		try {
			const { rules, problems } = coerce(JSON.parse(readFileSync(found, "utf-8")));
			loaded = {
				rules,
				source: found,
				error: problems.length > 0 ? `${found}: ${problems.join("; ")}` : undefined,
			};
		} catch (err) {
			loaded = {
				rules: SAFETY_FLOOR,
				source: "built-in safety floor",
				error: `${found} could not be parsed (${err instanceof Error ? err.message : String(err)}) — falling back to the built-in safety floor.`,
			};
		}
	}

	const projectFile = join(cwd, ".pi", "guard-rules.json");
	if (existsSync(projectFile)) {
		try {
			const { rules: extra, problems } = coerce(JSON.parse(readFileSync(projectFile, "utf-8")), {
				zeroAccessPaths: [],
				zeroAccessAllowPaths: [],
				readOnlyPaths: [],
				noDeletePaths: [],
				bashPatterns: [],
			});
			if (extra.zeroAccessAllowPaths.length > 0) problems.push("zeroAccessAllowPaths may only be set in global policy");
			for (const key of ["zeroAccessPaths", "readOnlyPaths", "noDeletePaths", "bashPatterns"] as const) {
				loaded.rules = { ...loaded.rules, [key]: [...loaded.rules[key], ...extra[key]] };
			}
			loaded.source += ` + ${projectFile}`;
			if (problems.length > 0) {
				loaded.error = [loaded.error, `${projectFile}: ${problems.join("; ")}`].filter(Boolean).join("; ");
			}
		} catch (err) {
			loaded.error = [
				loaded.error,
				`${projectFile} could not be parsed (${err instanceof Error ? err.message : String(err)}). Global policy remains active.`,
			].filter(Boolean).join("; ");
		}
	}

	cache.set(cwd, loaded);
	return loaded;
}

/**
 * The load problem for this cwd, returned once. Guards call this so a broken
 * policy is announced rather than quietly degrading to the floor, without every
 * guard announcing it on every tool call.
 *
 * The report is one-shot, so only call it when you can actually deliver it —
 * every guard guards the call with `ctx.hasUI`. Calling it headless would burn
 * the single report on a run with nowhere to show it.
 */
export function takeLoadIssue(cwd: string): string | undefined {
	const { error } = getRules(cwd);
	if (!error || reported.has(cwd)) return undefined;
	reported.add(cwd);
	return error;
}

// --- Path matching ---------------------------------------------------------

function expandTilde(p: string): string {
	if (p === "~") return HOME;
	return p.startsWith("~/") ? join(HOME, p.slice(2)) : p;
}

/** One path segment, with `*` and `?` confined to that segment. */
function segmentRegex(segment: string): RegExp {
	const source = segment.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, "[^/]*").replace(/\?/g, "[^/]");
	return new RegExp(`^${source}$`);
}

function segmentsOf(p: string): string[] {
	return p.split("/").filter((segment) => segment.length > 0);
}

function runMatches(target: string[], pattern: RegExp[], start: number): boolean {
	if (start + pattern.length > target.length) return false;
	return pattern.every((regex, offset) => regex.test(target[start + offset]));
}

/**
 * Does `target` name the path `pattern` describes, or something beneath it?
 *
 * Matching is per path *segment*, which is the point: the old `String.includes`
 * check blocked `.env-example` and `environments/` on a `.env` rule, and would
 * have missed `.env` reached by a different spelling of the same directory. An
 * absolute pattern anchors at the root; a relative one matches a contiguous run
 * of segments anywhere in the path, so `node_modules/` catches it at any depth.
 */
export function matchesPath(target: string, pattern: string, cwd: string): boolean {
	const absoluteTarget = resolve(cwd, expandTilde(target));
	const expanded = expandTilde(pattern.endsWith("/") ? pattern.slice(0, -1) : pattern);
	const targetSegments = segmentsOf(absoluteTarget);
	const patternSegments = segmentsOf(expanded).map(segmentRegex);
	if (patternSegments.length === 0) return false;

	if (isAbsolute(expanded)) return runMatches(targetSegments, patternSegments, 0);

	for (let i = 0; i + patternSegments.length <= targetSegments.length; i++) {
		if (runMatches(targetSegments, patternSegments, i)) return true;
	}
	return false;
}

function firstMatch(target: string, patterns: string[], cwd: string): string | undefined {
	return patterns.find((pattern) => matchesPath(target, pattern, cwd));
}

/** True when an explicit allow rule exempts this path from the zero-access set. */
export function isAllowlisted(target: string, cwd: string): boolean {
	return firstMatch(target, getRules(cwd).rules.zeroAccessAllowPaths, cwd) !== undefined;
}

export function zeroAccessMatch(target: string, cwd: string): string | undefined {
	if (isAllowlisted(target, cwd)) return undefined;
	return firstMatch(target, getRules(cwd).rules.zeroAccessPaths, cwd);
}

export function readOnlyMatch(target: string, cwd: string): string | undefined {
	return firstMatch(target, getRules(cwd).rules.readOnlyPaths, cwd);
}

export function noDeleteMatch(target: string, cwd: string): string | undefined {
	return firstMatch(target, getRules(cwd).rules.noDeletePaths, cwd);
}

// --- Bash command inspection ----------------------------------------------

/**
 * Split a bash command into path-like tokens.
 *
 * Shell metacharacters and quotes are separators, so `cat .env && ls` yields
 * `.env` and `cat "$HOME/.ssh/id_rsa"` yields `$HOME/.ssh/id_rsa`. Tokens are
 * matched individually because the path patterns are segment-anchored — testing
 * them against the whole command string would not line up on segment bounds.
 */
export function commandTokens(command: string): string[] {
	return command
		.split(/[\s;|&<>()"'`]+/)
		.map((token) => token.replace(/^@/, "").replace(/[,:]+$/, ""))
		.filter((token) => token.length > 0);
}

export interface TokenMatch {
	token: string;
	pattern: string;
}

/** First token in `command` that matches one of `patterns`, honouring the allowlist. */
export function commandPathMatch(command: string, patterns: string[], cwd: string): TokenMatch | undefined {
	for (const token of commandTokens(command)) {
		if (isAllowlisted(token, cwd)) continue;
		const pattern = firstMatch(token, patterns, cwd);
		if (pattern) return { token, pattern };
	}
	return undefined;
}

export interface CompiledBashPattern {
	regex: RegExp;
	reason: string;
	ask: boolean;
}

/** Parse only standalone literal words; shell expansion and operators stay on the conservative path. */
function literalWords(command: string): { value: string; quoted: boolean }[] | undefined {
	if (/[\r\n]/.test(command)) return undefined;
	const tokens = /(?:'[^']*'|"[^"$`\\]*"|[^\s'"\\$`|&;()<>{}*?!#\[\]])+/y;
	const words: { value: string; quoted: boolean }[] = [];
	let offset = 0;
	while (offset < command.length) {
		if (/[ \t]/.test(command[offset])) { offset++; continue; }
		tokens.lastIndex = offset;
		const match = tokens.exec(command);
		if (!match) return undefined;
		const raw = match[0];
		words.push({
			value: raw.replace(/'([^']*)'|"([^"]*)"/g, (_match, single, double) => single ?? double),
			quoted: /['"]/.test(raw),
		});
		offset = tokens.lastIndex;
	}
	return words;
}

/** Missing targets are safe only when their nearest existing ancestor resolves inside /tmp. */
function isTemporaryTarget(target: string): boolean {
	if (!target.startsWith("/tmp/") || target.split("/").includes("..") || resolve(target) === "/tmp") return false;
	let ancestor = target;
	while (!lstatSync(ancestor, { throwIfNoEntry: false })) ancestor = dirname(ancestor);
	try {
		const real = realpathSync(ancestor);
		return real === "/tmp" || real.startsWith("/tmp/");
	} catch (err) {
		if ((err as NodeJS.ErrnoException).code === "ENOENT") return false;
		throw err;
	}
}

/** Only exempt a standalone rm with literal targets beneath ephemeral /tmp. */
function isTemporaryCleanup(command: string): boolean {
	const parsed = literalWords(command);
	if (!parsed) return false;
	const words = parsed.map((word) => word.value);
	if (words.shift() !== "rm") return false;
	while (words.length > 0 && /^(?:-[rRf]+|--recursive|--force)$/.test(words[0])) words.shift();
	if (words[0] === "--") words.shift();
	return words.length > 0 && words.every(isTemporaryTarget);
}

/** Permission changes affect inodes, so exclude other filesystems, special files and shared hard links. */
function isTemporaryPermissionChange(command: string): boolean {
	const parsed = literalWords(command);
	if (!parsed) return false;
	const words = parsed.map((word) => word.value);
	if (!["chmod", "chown"].includes(words.shift() ?? "")) return false;
	while (words.length > 0 && /^(?:-[vcf]+|--verbose|--changes|--silent|--quiet)$/.test(words[0])) words.shift();
	if (words[0] === "--") words.shift();
	const modeOrOwner = words.shift();
	if (!modeOrOwner || modeOrOwner.startsWith("-")) return false;
	if (words[0] === "--") words.shift();
	return words.length > 0 && words.every((target) => {
		if (!isTemporaryTarget(target)) return false;
		const stat = statSync(target, { throwIfNoEntry: false });
		return stat !== undefined && stat.dev === statSync("/tmp").dev &&
			(stat.isDirectory() || (stat.isFile() && stat.nlink === 1));
	});
}

function isHarmlessGitCommand(command: string, exemption: BashPattern["commandExemption"]): boolean {
	const words = literalWords(command)?.map((word) => word.value);
	if (!words || words[0] !== "git") return false;
	const separator = words.indexOf("--");
	const options = separator < 0 ? words : words.slice(0, separator);
	if (exemption === "git-index" && words[1] === "restore") {
		const flags = options.slice(2).filter((word) => word.startsWith("-"));
		return flags.some((flag) => flag === "--staged" || flag === "-S") &&
			flags.every((flag) => ["--staged", "-S", "--quiet", "-q"].includes(flag));
	}
	if (exemption !== "git-dry-run") return false;
	const offset = words[1] === "clean" ? 2 : words[1] === "worktree" && words[2] === "prune" ? 3 : 0;
	if (!offset) return false;
	const flags = options.slice(offset).filter((word) => word.startsWith("-"));
	return flags.some((flag) => flag === "--dry-run" || /^-[ndfxXv]*n[ndfxXv]*$/.test(flag)) &&
		flags.every((flag) => ["--dry-run", "--verbose"].includes(flag) || /^-[ndfxXv]+$/.test(flag));
}

/** Match both the original command and common Git global-option spellings. */
export function matchingBashPatterns(command: string, cwd: string): CompiledBashPattern[] {
	const words = literalWords(command);
	// Quoted search/print arguments are data. Keep raw inspection for pipelines,
	// substitutions, interpreters and rg's executable preprocessor option.
	const textOnly = words && ["echo", "printf", "rg", "grep"].includes(words[0]?.value) &&
		!words.some((word) => word.value === "--pre" || word.value.startsWith("--pre="));
	const inspected = textOnly
		? words.map((word, index) => index > 0 && word.quoted ? "__quoted_data__" : word.value).join(" ")
		: command;
	const normalized = inspected.replace(
		/\bgit\s+(?:(?:-C|-c|--git-dir|--work-tree)\s+(?:"[^"\n]*"|'[^'\n]*'|[^\s|;&]+)\s+|--(?:git-dir|work-tree)=[^\s|;&]+\s+|--(?:no-pager|paginate|bare|no-optional-locks)\s+)*/g,
		"git ",
	);
	return getRules(cwd).rules.bashPatterns.flatMap((entry) => {
		const regex = new RegExp(entry.pattern);
		if (!regex.test(inspected) && !regex.test(normalized)) return [];
		if (entry.commandExemption && isHarmlessGitCommand(normalized, entry.commandExemption)) return [];
		if (
			SANDBOX_ACTIVE && (entry.sandboxExemption === "host" ||
				(entry.sandboxExemption === "tmp-cleanup" && isTemporaryCleanup(command)) ||
				(entry.sandboxExemption === "tmp-permissions" && isTemporaryPermissionChange(command)))
		) return [];
		return [{ regex, reason: entry.reason, ask: entry.ask === true }];
	});
}

/** Commands that can remove or move a path away from where it is. */
export const DELETE_INDICATORS = [
	/\brm\b/,
	/\bunlink\b/,
	/\bshred\b/,
	/\bmv\b/,
	/\btruncate\b/,
	/\bgit\s+(rm|mv)\b/,
];

/** Commands that can modify a path in place. */
export const WRITE_INDICATORS = [
	/>>?/,
	/\btee\b/,
	/\b(cp|mv|rm|ln|install|truncate|dd)\b/,
	/\bsed\b[^|;]*\s-i/,
	/\b(chmod|chown)\b/,
];

// --- Block text ------------------------------------------------------------

/**
 * Wrap a block reason with an explicit instruction not to route around it.
 *
 * Without this a model treats a block as a failed attempt and retries the same
 * intent by another road — `cat` becomes `head` becomes `python -c`. The guards
 * are a speed bump; the speed bump only works if the driver stops.
 */
export function blockReason(detail: string): string {
	return `${detail}\n\nDo not work around this restriction. Do not retry with a different command, path, tool or encoding to reach the same result. Report this block to the user as stated and ask how they want to proceed.`;
}
