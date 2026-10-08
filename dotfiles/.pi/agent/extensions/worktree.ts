/**
 * Worktree Extension
 *
 * Git worktree management for pi. Worktrees live in a sibling folder
 * (default `../.worktrees/<repo>/<name>`) so the main checkout stays clean.
 *
 * `.bare`-style repos are also supported: a bare clone in `.bare/` (optionally
 * with a `.git` file pointing at it) and worktrees as siblings of `.bare`, e.g.
 * `main/`, `some-feature/`. There the directory containing `.bare` counts as
 * the main worktree and, with the default root, new worktrees are created next
 * to `.bare`.
 *
 * - /worktree create <name> [base]  — create (or attach to) branch <name> in a new worktree
 * - /worktree list                   — worktrees with branch, dirty state and ahead/behind vs base
 * - /worktree remove <name>          — remove the worktree; offer to delete the branch if merged
 * - /worktree open <name>            — tmux window running pi in the worktree, or print the cd command
 * - pi --gwt <name>                   — ensure the worktree exists, then re-exec pi inside it
 *
 * Config: ~/.pi/agent/worktree.json (global), <main-worktree>/.pi/worktree.json (repo, trust-gated).
 * Keys: root (string), copyFiles (string[]), setupCommand (string[] argv).
 * The base ref of each branch is stored in `git config branch.<name>.worktreeBase`.
 *
 * Sessions are shared: each worktree's default session directory
 * (~/.pi/agent/sessions/--<encoded-cwd>--) is symlinked to the main worktree's
 * session directory, so /resume lists sessions from the main checkout and all
 * worktrees alike, and new sessions land in the shared directory.
 *
 * The extension never prunes: entries git reports as prunable (directory
 * missing, possibly just not mounted here) are shown by /worktree list and
 * removed only one at a time, after confirmation, by create, --gwt and remove.
 */

import { spawn } from "node:child_process";
import {
	copyFileSync,
	existsSync,
	lstatSync,
	mkdirSync,
	readFileSync,
	readdirSync,
	readlinkSync,
	realpathSync,
	renameSync,
	rmdirSync,
	statSync,
	symlinkSync,
	unlinkSync,
} from "node:fs";
import { basename, dirname, isAbsolute, join, resolve } from "node:path";
import { homedir } from "node:os";
import { createInterface } from "node:readline/promises";
import { type ExtensionAPI, type ExtensionContext, getAgentDir } from "@earendil-works/pi-coding-agent";

// =============================================================================
// Constants
// =============================================================================

const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
const SUBCOMMANDS = ["create", "list", "remove", "open"] as const;
const ENV_ACTIVE = "PI_GWT_ACTIVE";

interface Config {
	root: string;
	copyFiles: string[];
	setupCommand?: string[];
}

const DEFAULT_CONFIG: Config = { root: "../.worktrees/<repo>", copyFiles: [] };

interface Worktree {
	path: string;
	head: string;
	branch?: string; // short name
	bare?: boolean; // bare gitdir entry (`.bare`-style repos)
	prunable?: string; // git's reason when the directory is missing
}

type Confirm = (title: string, message: string) => Promise<boolean>;

// =============================================================================
// Helpers
// =============================================================================

function validateName(name: string): void {
	if (!NAME_RE.test(name) || name === "." || name === "..") {
		throw new Error(`invalid worktree name '${name}': use letters, digits, . _ - (max 64), not . or ..`);
	}
}

async function git(pi: ExtensionAPI, args: string[], cwd?: string): Promise<string> {
	const result = await pi.exec("git", args, cwd ? { cwd } : undefined);
	if (result.code !== 0) {
		throw new Error(result.stderr.trim() || `git ${args.join(" ")} failed with exit code ${result.code}`);
	}
	return result.stdout.trim();
}

async function gitOk(pi: ExtensionAPI, args: string[], cwd?: string): Promise<boolean> {
	return (await pi.exec("git", args, cwd ? { cwd } : undefined)).code === 0;
}

async function getMainWorktree(pi: ExtensionAPI, cwd?: string): Promise<string> {
	let commonDir: string;
	try {
		commonDir = await git(pi, ["rev-parse", "--git-common-dir"], cwd);
	} catch {
		throw new Error("not a git repository");
	}
	return dirname(resolve(cwd ?? process.cwd(), commonDir));
}

async function listWorktrees(pi: ExtensionAPI, mainWorktree: string): Promise<Worktree[]> {
	const out = await git(pi, ["worktree", "list", "--porcelain"], mainWorktree);
	const worktrees: Worktree[] = [];
	for (const block of out.split("\n\n")) {
		let wt: Worktree | undefined;
		for (const line of block.split("\n")) {
			if (line.startsWith("worktree ")) wt = { path: line.slice(9), head: "" };
			else if (wt && line.startsWith("HEAD ")) wt.head = line.slice(5);
			else if (wt && line.startsWith("branch refs/heads/")) wt.branch = line.slice(18);
			else if (wt && line === "bare") wt.bare = true;
			else if (wt && line.startsWith("prunable ")) wt.prunable = line.slice(9);
		}
		if (wt) worktrees.push(wt);
	}
	return worktrees;
}

function samePath(a: string, b: string): boolean {
	const real = (p: string) => {
		try {
			return realpathSync(p);
		} catch {
			return resolve(p);
		}
	};
	return real(a) === real(b);
}

function findWorktree(worktrees: Worktree[], name: string, root: string): Worktree | undefined {
	return (
		worktrees.find((w) => w.branch === name) ??
		worktrees.slice(1).find((w) => samePath(w.path, join(root, name)))
	);
}

async function isDirty(pi: ExtensionAPI, path: string): Promise<number> {
	// Untracked files count: remove() deletes them with --force. The explicit mode
	// also overrides status.showUntrackedFiles=no.
	const out = await git(pi, ["status", "--porcelain", "--untracked-files=normal"], path);
	return out ? out.split("\n").length : 0;
}

async function getBase(pi: ExtensionAPI, mainWorktree: string, branch: string): Promise<string | undefined> {
	const result = await pi.exec("git", ["config", "--get", `branch.${branch}.worktreeBase`], { cwd: mainWorktree });
	return result.code === 0 ? result.stdout.trim() || undefined : undefined;
}

async function aheadBehind(pi: ExtensionAPI, path: string, base: string): Promise<string> {
	const out = await git(pi, ["rev-list", "--left-right", "--count", `${base}...HEAD`], path);
	const [behind, ahead] = out.split(/\s+/);
	return `↑${ahead} ↓${behind}`;
}

// =============================================================================
// Config
// =============================================================================

function expandTilde(p: string): string {
	return p === "~" || p.startsWith("~/") ? join(homedir(), p.slice(1)) : p;
}

/** Parse one config file. Returns the valid subset plus a list of problems. */
function readConfigFile(file: string): { config: Partial<Config>; errors: string[] } {
	const errors: string[] = [];
	const config: Partial<Config> = {};
	if (!existsSync(file)) return { config, errors };

	let raw: unknown;
	try {
		raw = JSON.parse(readFileSync(file, "utf-8"));
	} catch (e) {
		return { config, errors: [`${file}: invalid JSON (${e instanceof Error ? e.message : String(e)})`] };
	}
	if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
		return { config, errors: [`${file}: expected an object`] };
	}
	const obj = raw as Record<string, unknown>;
	const isStringArray = (v: unknown): v is string[] => Array.isArray(v) && v.every((s) => typeof s === "string");

	if ("root" in obj) {
		if (typeof obj.root === "string" && obj.root) config.root = obj.root;
		else errors.push(`${file}: "root" must be a non-empty string`);
	}
	if ("copyFiles" in obj) {
		if (!isStringArray(obj.copyFiles)) {
			errors.push(`${file}: "copyFiles" must be an array of strings`);
		} else {
			const bad = obj.copyFiles.filter((f) => isAbsolute(f) || f.split(/[\\/]/).includes(".."));
			if (bad.length) errors.push(`${file}: "copyFiles" entries must be relative without "..": ${bad.join(", ")}`);
			else config.copyFiles = obj.copyFiles;
		}
	}
	if ("setupCommand" in obj) {
		if (isStringArray(obj.setupCommand)) config.setupCommand = obj.setupCommand;
		else errors.push(`${file}: "setupCommand" must be an array of strings (argv)`);
	}
	return { config, errors };
}

/** Merge global + repo config. Repo file is read only when `trusted`. */
function loadConfig(
	mainWorktree: string,
	trusted: boolean,
): { config: Config; errors: string[]; notices: string[] } {
	const errors: string[] = [];
	const notices: string[] = [];
	const globalFile = join(getAgentDir(), "worktree.json");
	const repoFile = join(mainWorktree, ".pi", "worktree.json");

	const g = readConfigFile(globalFile);
	errors.push(...g.errors);
	let merged: Config = { ...DEFAULT_CONFIG, ...g.config };

	if (existsSync(repoFile)) {
		if (trusted) {
			const r = readConfigFile(repoFile);
			errors.push(...r.errors);
			merged = { ...merged, ...r.config };
		} else {
			notices.push(`ignoring ${repoFile}: project is not trusted (run /trust)`);
		}
	}

	// Reject directories in copyFiles (checked against the main worktree).
	const dirs = merged.copyFiles.filter((f) => {
		try {
			return statSync(join(mainWorktree, f)).isDirectory();
		} catch {
			return false;
		}
	});
	if (dirs.length) {
		errors.push(`"copyFiles" entries must be files, not directories: ${dirs.join(", ")}`);
		merged.copyFiles = merged.copyFiles.filter((f) => !dirs.includes(f));
	}
	return { config: merged, errors, notices };
}

/**
 * True when mainWorktree is the container of a `.bare`-style worktree repo:
 * a bare gitdir in `.bare/` (with HEAD), and no normal `.git` directory.
 */
function isBareStyle(mainWorktree: string): boolean {
	try {
		if (!statSync(join(mainWorktree, ".bare")).isDirectory()) return false;
	} catch {
		return false;
	}
	try {
		if (lstatSync(join(mainWorktree, ".git")).isDirectory()) return false;
	} catch {
		// no .git entry: bare clones without the .git pointer file still qualify
	}
	return existsSync(join(mainWorktree, ".bare", "HEAD"));
}

function worktreeRoot(config: Config, mainWorktree: string): string {
	// With the default root in a `.bare`-style repo, worktrees live next to `.bare`.
	if (config.root === DEFAULT_CONFIG.root && isBareStyle(mainWorktree)) return mainWorktree;
	const root = expandTilde(config.root.replaceAll("<repo>", basename(mainWorktree)));
	return resolve(mainWorktree, root);
}

/** Trust lookup without an ExtensionContext (factory path). Mirrors trust-manager.ts ancestor walk. */
function isTrustedFromFile(cwd: string): boolean {
	let data: Record<string, unknown>;
	try {
		data = JSON.parse(readFileSync(join(getAgentDir(), "trust.json"), "utf-8"));
	} catch {
		return false;
	}
	let dir = realpathSync(resolve(cwd));
	while (true) {
		const v = data[dir];
		if (v === true || v === false) return v;
		const parent = dirname(dir);
		if (parent === dir) return false;
		dir = parent;
	}
}

// =============================================================================
// Shared sessions
// =============================================================================

/**
 * Default pi session directory for a cwd. Mirrors pi's getDefaultSessionDirPath
 * encoding (~/.pi/agent/sessions/--<cwd with /, \, : as - >--).
 */
function sessionDirFor(cwd: string): string {
	const safePath = `--${resolve(cwd).replace(/^[/\\]/, "").replace(/[/\\:]/g, "-")}--`;
	return join(getAgentDir(), "sessions", safePath);
}

/**
 * Link the worktree's session directory to the main worktree's so sessions are
 * shared and visible from both. Migrates existing worktree sessions into the
 * main directory before linking. Returns a human-readable status message.
 */
function linkSessions(mainWorktree: string, worktreePath: string): string {
	const mainDir = sessionDirFor(mainWorktree);
	const wtDir = sessionDirFor(worktreePath);
	if (mainDir === wtDir) return "sessions already shared (main worktree)";
	mkdirSync(mainDir, { recursive: true });

	let stat;
	try {
		stat = lstatSync(wtDir);
	} catch (e) {
		if ((e as NodeJS.ErrnoException).code !== "ENOENT") throw e;
		symlinkSync(mainDir, wtDir, "dir");
		return "sessions linked to main worktree";
	}

	if (stat.isSymbolicLink()) {
		const target = resolve(dirname(wtDir), readlinkSync(wtDir));
		if (target === mainDir) return "sessions already shared";
		if (existsSync(target)) throw new Error(`session dir ${wtDir} is a symlink to ${target}, expected ${mainDir}`);
		// Dangling symlink: replace it.
		unlinkSync(wtDir);
		symlinkSync(mainDir, wtDir, "dir");
		return "sessions relinked to main worktree";
	}

	// wtDir is a real directory: migrate its sessions into mainDir, then link.
	// Validate everything before moving anything so a failure leaves both dirs untouched.
	const entries = readdirSync(wtDir);
	const other = entries.filter((f) => !f.endsWith(".jsonl"));
	if (other.length > 0) throw new Error(`session dir ${wtDir} has non-session files: ${other.join(", ")}`);
	const clashing = entries.filter((f) => existsSync(join(mainDir, f)));
	if (clashing.length > 0) throw new Error(`cannot migrate sessions, already exist in ${mainDir}: ${clashing.join(", ")}`);
	for (const file of entries) renameSync(join(wtDir, file), join(mainDir, file));
	rmdirSync(wtDir);
	symlinkSync(mainDir, wtDir, "dir");
	return entries.length > 0 ? `sessions shared (${entries.length} migrated to main worktree)` : "sessions linked to main worktree";
}

// =============================================================================
// Core ops
// =============================================================================

interface EnsureResult {
	path: string;
	branch: string;
	created: boolean;
	copied: string[];
	skipped: string[];
	sessionStatus: string;
	setupError?: string;
}

/**
 * Create the worktree for `name` (attaching to an existing branch if needed).
 * With `reuse`, an existing worktree for the branch is returned as-is.
 * A prunable entry is removed (that entry only) and recreated when `confirm`
 * agrees; otherwise the call fails, since the directory may just be unmounted.
 */
async function ensureWorktree(
	pi: ExtensionAPI,
	mainWorktree: string,
	config: Config,
	name: string,
	base: string | undefined,
	reuse: boolean,
	confirm: Confirm,
): Promise<EnsureResult> {
	const root = worktreeRoot(config, mainWorktree);
	const path = join(root, name);

	let existing = findWorktree(await listWorktrees(pi, mainWorktree), name, root);
	if (existing?.prunable) {
		const ok = await confirm(
			`Recreate worktree '${name}'?`,
			`registered at ${existing.path} but the directory is missing here (${existing.prunable}). ` +
				"Remove the stale entry and create it fresh? Choose No if it is only not mounted here.",
		);
		if (!ok) {
			throw new Error(`worktree '${name}' is registered at ${existing.path} but has no directory here (${existing.prunable})`);
		}
		await git(pi, ["worktree", "remove", existing.path], mainWorktree);
		existing = undefined;
	}
	if (existing) {
		if (reuse) {
			const sessionStatus = linkSessions(mainWorktree, existing.path);
			return { path: existing.path, branch: name, created: false, copied: [], skipped: [], sessionStatus };
		}
		throw new Error(`worktree '${name}' already exists at ${existing.path}; use /worktree open ${name}`);
	}

	let resolvedBase = base;
	if (!resolvedBase) {
		resolvedBase = await git(pi, ["rev-parse", "--abbrev-ref", "HEAD"], mainWorktree);
		if (resolvedBase === "HEAD") resolvedBase = await git(pi, ["rev-parse", "HEAD"], mainWorktree);
	}
	if (!(await gitOk(pi, ["rev-parse", "--verify", "--quiet", resolvedBase], mainWorktree))) {
		throw new Error(`base ref '${resolvedBase}' does not exist`);
	}
	if (existsSync(path)) throw new Error(`directory ${path} already exists`);

	const branchExists = await gitOk(pi, ["rev-parse", "--verify", "--quiet", `refs/heads/${name}`], mainWorktree);
	if (branchExists) {
		await git(pi, ["worktree", "add", path, name], mainWorktree);
		if (base) await git(pi, ["config", `branch.${name}.worktreeBase`, base], mainWorktree);
	} else {
		await git(pi, ["worktree", "add", path, "-b", name, resolvedBase], mainWorktree);
		await git(pi, ["config", `branch.${name}.worktreeBase`, resolvedBase], mainWorktree);
	}
	const sessionStatus = linkSessions(mainWorktree, path);

	const copied: string[] = [];
	const skipped: string[] = [];
	for (const file of config.copyFiles) {
		const src = join(mainWorktree, file);
		if (!existsSync(src)) {
			skipped.push(file);
			continue;
		}
		copyFileSync(src, join(path, file));
		copied.push(file);
	}

	let setupError: string | undefined;
	if (config.setupCommand && config.setupCommand.length > 0) {
		const [cmd, ...args] = config.setupCommand;
		const result = await pi.exec(cmd, args, { cwd: path });
		if (result.code !== 0) {
			const tail = result.stderr.trim().split("\n").slice(-5).join("\n");
			setupError = `setup command exited ${result.code}${tail ? `:\n${tail}` : ""}`;
		}
	}

	return { path, branch: name, created: true, copied, skipped, sessionStatus, setupError };
}

// =============================================================================
// --gwt re-exec (factory path)
// =============================================================================

const NON_INTERACTIVE_FLAGS = new Set(["-p", "--print", "--help", "-h", "--list-models"]);

function parseGwtArgv(argv: string[]): { present: boolean; name?: string; filtered: string[] } {
	const filtered: string[] = [];
	let present = false;
	let name: string | undefined;
	for (let i = 0; i < argv.length; i++) {
		const arg = argv[i];
		if (arg.startsWith("--gwt=")) {
			present = true;
			name = arg.slice(6);
		} else if (arg === "--gwt") {
			present = true;
			const next = argv[i + 1];
			if (next !== undefined && !next.startsWith("-") && !next.startsWith("@")) {
				name = next;
				i++;
			}
		} else {
			filtered.push(arg);
		}
	}
	return { present, name, filtered };
}

function isInteractiveArgv(argv: string[]): boolean {
	if (!process.stdin.isTTY || !process.stdout.isTTY) return false;
	for (let i = 0; i < argv.length; i++) {
		if (NON_INTERACTIVE_FLAGS.has(argv[i])) return false;
		if (argv[i] === "--mode" && ["json", "rpc", "text"].includes(argv[i + 1] ?? "")) return false;
		if (/^--mode=(json|rpc|text)$/.test(argv[i])) return false;
	}
	return true;
}

function fail(message: string): never {
	console.error(`pi-gwt: ${message}`);
	process.exit(1);
}

/** y/N prompt on the terminal; isInteractiveArgv has already guaranteed a TTY. */
async function confirmOnTerminal(title: string, message: string): Promise<boolean> {
	const rl = createInterface({ input: process.stdin, output: process.stderr });
	try {
		const answer = await rl.question(`pi-gwt: ${title}\n${message} [y/N] `);
		return ["y", "yes"].includes(answer.trim().toLowerCase());
	} finally {
		rl.close();
	}
}

/** Returns a warning message if the child could not be launched; never returns on success. */
async function handleGwt(pi: ExtensionAPI): Promise<string | undefined> {
	const { present, name, filtered } = parseGwtArgv(process.argv.slice(2));
	if (!present || process.env[ENV_ACTIVE]) return undefined;

	if (!name) fail("--gwt requires a worktree name");
	try {
		validateName(name);
	} catch (e) {
		fail(e instanceof Error ? e.message : String(e));
	}
	if (!isInteractiveArgv(filtered)) fail("--gwt is only supported in interactive mode");

	let result: EnsureResult;
	try {
		const mainWorktree = await getMainWorktree(pi);
		const { config, errors, notices } = loadConfig(mainWorktree, isTrustedFromFile(mainWorktree));
		for (const m of [...errors, ...notices]) console.error(`pi-gwt: ${m}`);
		result = await ensureWorktree(pi, mainWorktree, config, name, undefined, true, confirmOnTerminal);
	} catch (e) {
		fail(e instanceof Error ? e.message : String(e));
	}
	if (result.setupError) console.error(`pi-gwt: ${result.setupError}`);
	if (result.skipped.length) console.error(`pi-gwt: copyFiles missing in main worktree: ${result.skipped.join(", ")}`);
	console.error(`pi-gwt: ${result.sessionStatus}`);

	const entry = process.argv[1];
	const [cmd, args] =
		entry && existsSync(entry) ? [process.execPath, [entry, ...filtered]] : ["pi", filtered];

	return new Promise<string | undefined>((resolvePromise) => {
		const child = spawn(cmd, args, {
			cwd: result.path,
			stdio: "inherit",
			env: { ...process.env, [ENV_ACTIVE]: name },
		});
		child.on("error", (err) => {
			resolvePromise(`failed to launch pi in worktree ${result.path}: ${err.message}; continuing in main worktree`);
		});
		child.on("exit", (code) => process.exit(code ?? 1));
	});
}

// =============================================================================
// Extension
// =============================================================================

export default async function worktreeExtension(pi: ExtensionAPI): Promise<void> {
	pi.registerFlag("gwt", {
		type: "string",
		description: "Create/attach a git worktree and run pi inside it",
	});

	const launchWarning = await handleGwt(pi);

	/** Shared preamble: main worktree + config, with config problems surfaced. */
	async function prepare(ctx: ExtensionContext): Promise<{ mainWorktree: string; config: Config }> {
		const mainWorktree = await getMainWorktree(pi, ctx.cwd);
		const { config, errors, notices } = loadConfig(mainWorktree, ctx.isProjectTrusted());
		for (const m of errors) ctx.ui.notify(`worktree config: ${m}`, "error");
		for (const m of notices) ctx.ui.notify(`worktree config: ${m}`, "warning");
		return { mainWorktree, config };
	}

	async function resolveTarget(
		ctx: ExtensionContext,
		name: string,
	): Promise<{ mainWorktree: string; worktrees: Worktree[]; target: Worktree }> {
		const { mainWorktree, config } = await prepare(ctx);
		const worktrees = await listWorktrees(pi, mainWorktree);
		const target = findWorktree(worktrees, name, worktreeRoot(config, mainWorktree));
		if (!target) throw new Error(`no worktree named '${name}'`);
		return { mainWorktree, worktrees, target };
	}

	async function create(ctx: ExtensionContext, name: string, base?: string): Promise<void> {
		const { mainWorktree, config } = await prepare(ctx);
		const r = await ensureWorktree(pi, mainWorktree, config, name, base, false, (title, message) =>
			ctx.ui.confirm(title, message),
		);
		const lines = [`worktree '${name}' created at ${r.path}`];
		if (r.copied.length) lines.push(`copied: ${r.copied.join(", ")}`);
		if (r.skipped.length) lines.push(`skipped (missing): ${r.skipped.join(", ")}`);
		lines.push(r.sessionStatus);
		lines.push(`open with: /worktree open ${name}  or  cd ${r.path} && pi`);
		ctx.ui.notify(lines.join("\n"), "info");
		if (r.setupError) ctx.ui.notify(`worktree '${name}' kept but ${r.setupError}`, "warning");
	}

	async function list(ctx: ExtensionContext): Promise<void> {
		const { mainWorktree } = await prepare(ctx);
		const worktrees = await listWorktrees(pi, mainWorktree);
		const rows: string[][] = [];
		for (const [i, wt] of worktrees.entries()) {
			const marker = samePath(wt.path, ctx.cwd) ? "*" : " ";
			// Bare gitdir entry (`.bare`-style): no work tree, so skip dirty/sync
			// checks (git status fails there).
			if (wt.bare) {
				rows.push([marker, "(bare)", "-", "-", "-", wt.path]);
				continue;
			}
			const name = i === 0 ? "(main)" : basename(wt.path);
			const branch = wt.branch ?? `detached@${wt.head.slice(0, 8)}`;
			// Prunable entry: no directory here (deleted, or not mounted), so
			// there is nothing to run git status / rev-list in.
			if (wt.prunable) {
				rows.push([marker, name, branch, "missing", wt.prunable, wt.path]);
				continue;
			}
			const dirty = (await isDirty(pi, wt.path)) > 0 ? "dirty" : "clean";
			const base = wt.branch ? await getBase(pi, mainWorktree, wt.branch) : undefined;
			const sync = base ? `${await aheadBehind(pi, wt.path, base)} vs ${base}` : "base unknown";
			rows.push([marker, name, branch, dirty, sync, wt.path]);
		}
		const widths = rows[0].map((_, c) => Math.max(...rows.map((r) => r[c].length)));
		const table = rows.map((r) => r.map((cell, c) => cell.padEnd(widths[c])).join("  ").trimEnd());
		ctx.ui.notify(table.join("\n"), "info");
	}

	async function remove(ctx: ExtensionContext, name: string): Promise<void> {
		const { mainWorktree, worktrees, target } = await resolveTarget(ctx, name);
		if (target === worktrees[0] || samePath(target.path, ctx.cwd)) {
			throw new Error(`cannot remove the worktree pi is running in (${target.path})`);
		}

		if (target.prunable) {
			const ok = await ctx.ui.confirm(
				`Remove stale worktree entry '${name}'?`,
				`directory missing here (${target.prunable}); choose No if it is only not mounted here`,
			);
			if (!ok) return;
		} else {
			const dirtyCount = await isDirty(pi, target.path);
			if (dirtyCount > 0) {
				const ok = await ctx.ui.confirm(
					"Remove dirty worktree?",
					`${dirtyCount} modified or untracked files in ${target.path} will be deleted (an untracked directory counts as one)`,
				);
				if (!ok) return;
			}
		}
		await git(pi, ["worktree", "remove", "--force", target.path], mainWorktree);

		// Remove the shared-session symlink; sessions stay in the main session dir.
		const wtSessionDir = sessionDirFor(target.path);
		let sessionStat;
		try {
			sessionStat = lstatSync(wtSessionDir);
		} catch (e) {
			if ((e as NodeJS.ErrnoException).code !== "ENOENT") throw e;
		}
		if (sessionStat?.isSymbolicLink()) unlinkSync(wtSessionDir);

		ctx.ui.notify(`removed worktree ${target.path}`, "info");
		if (sessionStat && !sessionStat.isSymbolicLink()) {
			ctx.ui.notify(`session dir ${wtSessionDir} is a real directory; left in place`, "warning");
		}

		const branch = target.branch;
		if (!branch) return;
		const base = await getBase(pi, mainWorktree, branch);
		const merged = base
			? (await git(pi, ["branch", "--merged", base, "--format=%(refname:short)"], mainWorktree))
					.split("\n")
					.includes(branch)
			: false;
		if (merged && base) {
			const ok = await ctx.ui.confirm(`Delete branch ${branch}?`, `merged into ${base}`);
			if (ok) {
				await git(pi, ["branch", "-d", branch], mainWorktree);
				ctx.ui.notify(`deleted branch ${branch}`, "info");
				return;
			}
		}
		const unset = await pi.exec("git", ["config", "--unset", `branch.${branch}.worktreeBase`], { cwd: mainWorktree });
		if (unset.code !== 0 && unset.code !== 5) throw new Error(unset.stderr.trim());
		ctx.ui.notify(`branch ${branch} kept (${base ? (merged ? "not deleted" : `not merged into ${base}`) : "base unknown"})`, "info");
	}

	async function open(ctx: ExtensionContext, name: string): Promise<void> {
		const { target } = await resolveTarget(ctx, name);
		if (process.env.TMUX) {
			const result = await pi.exec("tmux", ["new-window", "-c", target.path, "pi"]);
			if (result.code !== 0) throw new Error(`tmux new-window failed: ${result.stderr.trim()}`);
			ctx.ui.notify(`opened pi in a new tmux window: ${target.path}`, "info");
		} else {
			ctx.ui.notify(`cd ${target.path} && pi`, "info");
		}
	}

	pi.registerCommand("worktree", {
		description: "Git worktrees: create <name> [base] | list | remove <name> | open <name>",
		getArgumentCompletions: async (text) => {
			const parts = text.split(/\s+/);
			if (parts.length <= 1) {
				const items = SUBCOMMANDS.filter((s) => s.startsWith(parts[0] ?? "")).map((s) => ({ value: s, label: s }));
				return items.length ? items : null;
			}
			if ((parts[0] === "remove" || parts[0] === "open") && parts.length === 2) {
				try {
					const mainWorktree = await getMainWorktree(pi);
					const names = (await listWorktrees(pi, mainWorktree))
						.slice(1)
						.map((w) => w.branch ?? basename(w.path))
						.filter((n) => n.startsWith(parts[1]));
					return names.length ? names.map((n) => ({ value: `${parts[0]} ${n}`, label: n })) : null;
				} catch {
					return null;
				}
			}
			return null;
		},
		handler: async (args, ctx) => {
			const [sub, name, base, ...rest] = args.trim().split(/\s+/).filter(Boolean);
			try {
				switch (sub) {
					case "create":
						if (!name || rest.length) throw new Error("usage: /worktree create <name> [base]");
						validateName(name);
						await create(ctx, name, base);
						break;
					case "list":
						if (name) throw new Error("usage: /worktree list");
						await list(ctx);
						break;
					case "remove":
					case "open":
						if (!name || base) throw new Error(`usage: /worktree ${sub} <name>`);
						validateName(name);
						await (sub === "remove" ? remove(ctx, name) : open(ctx, name));
						break;
					default:
						throw new Error("usage: /worktree create <name> [base] | list | remove <name> | open <name>");
				}
			} catch (e) {
				ctx.ui.notify(e instanceof Error ? e.message : String(e), "error");
			}
		},
	});

	pi.on("session_start", async (event, ctx) => {
		if (event.reason !== "startup") return;
		if (launchWarning) ctx.ui.notify(`pi-gwt: ${launchWarning}`, "warning");

		let mainWorktree: string;
		try {
			mainWorktree = await getMainWorktree(pi, ctx.cwd);
		} catch {
			return;
		}
		const active = process.env[ENV_ACTIVE];
		if (active) ctx.ui.notify(`worktree: ${active} (${ctx.cwd})`, "info");

		// Fallback for worktrees entered without --gwt: ensure sessions are shared.
		const sessionDir = sessionDirFor(ctx.cwd);
		let linked = false;
		try {
			linked = lstatSync(sessionDir).isSymbolicLink();
		} catch {
			linked = false;
		}
		if (!linked) {
			const mainDir = sessionDirFor(mainWorktree);
			if (sessionDir !== mainDir) {
				try {
					ctx.ui.notify(`worktree: ${linkSessions(mainWorktree, ctx.cwd)}`, "info");
				} catch (e) {
					ctx.ui.notify(`worktree sessions: ${e instanceof Error ? e.message : String(e)}`, "error");
				}
			}
		}
	});
}
