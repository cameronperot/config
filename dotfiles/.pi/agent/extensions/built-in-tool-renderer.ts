/**
 * Built-in Tool Renderer + Read Audit
 *
 * Merge of two shipped examples:
 * - built-in-tool-renderer.ts - compact renderCall/renderResult for read, bash,
 *   edit and write, delegating execution to the original implementations.
 * - tool-override.ts - access logging and zero-access blocking on `read`,
 *   plus the /read-log command. The paths it refuses come from the
 *   `zeroAccessPaths` policy in guard-rules.json, shared with the bash guard.
 *
 * They are merged rather than installed side by side because Pi keeps the
 * FIRST registration for a given tool name (runner.js getAllRegisteredTools)
 * and extension discovery is an unsorted readdir, so shipping both files would
 * drop one `read` registration nondeterministically.
 *
 * Difference from the shipped tool-override.ts: `read` delegates to
 * createReadTool() rather than reimplementing the read. The shipped example
 * returns its own details shape and does naive byte-slice truncation, which
 * loses image support, ReadToolDetails and the built-in truncation semantics.
 * Here the block check and the log entry wrap the real implementation, and a
 * block also notifies and appends the same `guard-block` session entry the other
 * three guards do, so the read path leaves the same trace they leave.
 *
 * All four render through `shared/render.ts`: a call row (glyph, tool name,
 * argument), a body bounded to a visual-row budget behind a gutter or a
 * line-number column, and a status row carrying outcome, size and elapsed time.
 * Diffs go through Pi's own `renderDiff` and previews through `highlightCode`,
 * so the colouring matches the rest of the TUI and costs no dependency.
 *
 * `bash` reads its outcome from `context.isError` plus the trailer Pi appends
 * when the command fails, not from the output text alone: a non-zero exit is
 * thrown, and the earlier `exit code:` pattern never matched what core emits.
 *
 * The base tools are built per-cwd, and `read`/`bash` are given the same
 * settings-derived options core passes in _buildRuntime (images.autoResize,
 * shellCommandPrefix, shellPath). Building them once from process.cwd() with no
 * options — as the shipped example does — silently discards those settings and
 * pins the tools to the startup directory. `edit` and `write` take no options.
 */

import type { ImageContent, TextContent } from "@earendil-works/pi-ai";
import type {
	BashToolDetails,
	EditToolDetails,
	ExtensionAPI,
	ReadToolDetails,
	Theme,
} from "@earendil-works/pi-coding-agent";
import {
	createBashTool,
	createEditTool,
	createReadTool,
	createWriteTool,
	getLanguageFromPath,
	highlightCode,
	renderDiff,
	SettingsManager,
} from "@earendil-works/pi-coding-agent";
import type { Component } from "@earendil-works/pi-tui";
import { Container, Text } from "@earendil-works/pi-tui";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { LOG_FILE, logAccess } from "./shared/access-log.ts";
import {
	BodyText,
	callRow,
	elapsed,
	elide,
	fileLink,
	langIcon,
	markSettled,
	markStarted,
	moreRow,
	numbered,
	plural,
	PREVIEW,
	shortPath,
	type StatusKind,
	statusRow,
	SYM,
	type TimedState,
} from "./shared/render.ts";
import { blockReason, type GuardAudit, takeLoadIssue, zeroAccessMatch } from "./shared/rules.ts";

const BLOCKED_PREFIX = "Access denied:";

/** Width budget for a path in a call row, before the middle ellipsis kicks in. */
const PATH_WIDTH = 72;

/** Unfiltered line count: what is shown and what is counted must agree. */
function countLines(text: string): number {
	const trimmed = text.replace(/\n+$/, "");
	return trimmed.length === 0 ? 0 : trimmed.split("\n").length;
}

function firstLine(content: TextContent | ImageContent | undefined, fallback: string): string {
	if (content?.type !== "text") return fallback;
	return content.text.split("\n")[0] ?? fallback;
}

/** Language icon plus a linked, shortened path — the argument shape edit and write share. */
function pathArg(theme: Theme, cwd: string, path: string): string {
	const icon = theme.fg("muted", langIcon(getLanguageFromPath(path)));
	const display = theme.fg("accent", elide(shortPath(cwd, path), PATH_WIDTH));
	return `${icon} ${fileLink(resolve(cwd, path), display)}`;
}

/** Reuse the row's previous container so a spinner tick repaints instead of reallocating. */
function reuseContainer(context: { lastComponent: Component | undefined }): Container {
	const container = context.lastComponent instanceof Container ? context.lastComponent : new Container();
	container.clear();
	return container;
}

/**
 * Pi's bash tool throws on a non-zero exit, appending the reason to the output
 * (core/tools/bash.js: `Command exited with code N`). Splitting that trailer off
 * gives both the status label and a body without a redundant last line.
 */
function splitBashOutput(
	output: string,
	isError: boolean,
): { body: string; kind: StatusKind; label: string } {
	const trim = (text: string) => text.replace(/\n+$/, "");
	if (!isError) return { body: trim(output), kind: "success", label: "ok" };

	const match = output.match(
		/(?:^|\n\n)(?:Command exited with code (\d+)|Command timed out after (\d+) seconds|Command aborted)$/,
	);
	if (!match) return { body: trim(output), kind: "error", label: "failed" };

	const body = trim(output.slice(0, output.length - match[0].length));
	if (match[1] !== undefined) return { body, kind: "error", label: `exit ${match[1]}` };
	if (match[2] !== undefined) return { body, kind: "warning", label: `timeout ${match[2]}s` };
	return { body, kind: "aborted", label: "aborted" };
}

function countPatch(patch: string | undefined): { added: number; removed: number } {
	let added = 0;
	let removed = 0;
	for (const line of (patch ?? "").split("\n")) {
		if (line.startsWith("+") && !line.startsWith("+++")) added++;
		else if (line.startsWith("-") && !line.startsWith("---")) removed++;
	}
	return { added, removed };
}

/**
 * Base tools for a working directory, built with the settings that apply there.
 * Memoized because a tool is rebuilt on every execute() otherwise, and the
 * settings read is filesystem work.
 */
function makeBaseTools() {
	const cache = new Map<string, ReturnType<typeof buildForCwd>>();

	function buildForCwd(cwd: string) {
		const settings = SettingsManager.create(cwd);
		return {
			read: createReadTool(cwd, { autoResizeImages: settings.getImageAutoResize() }),
			bash: createBashTool(cwd, {
				commandPrefix: settings.getShellCommandPrefix(),
				shellPath: settings.getShellPath(),
			}),
			edit: createEditTool(cwd),
			write: createWriteTool(cwd),
		};
	}

	return (cwd: string) => {
		let tools = cache.get(cwd);
		if (!tools) {
			tools = buildForCwd(cwd);
			cache.set(cwd, tools);
		}
		return tools;
	};
}

export default function (pi: ExtensionAPI) {
	const baseTools = makeBaseTools();

	// Registration needs a description and schema before any ctx exists. Both are
	// cwd- and option-independent, so the startup-cwd set supplies them; every
	// execute() resolves its own set from ctx.cwd.
	const template = baseTools(process.cwd());

	// --- Read tool: audit access, then show path and a highlighted preview ---
	pi.registerTool({
		name: "read",
		label: "read (audited)",
		description: template.read.description,
		parameters: template.read.parameters,

		async execute(toolCallId, params, signal, onUpdate, ctx) {
			const absolutePath = resolve(ctx.cwd, params.path);

			if (ctx.hasUI) {
				const issue = takeLoadIssue(ctx.cwd);
				if (issue) ctx.ui.notify(`Guard policy: ${issue}`, "warning");
			}

			const secret = zeroAccessMatch(params.path, ctx.cwd);
			if (secret) {
				const rule = `zero-access path "${secret}"`;
				await logAccess(absolutePath, false, `matches zero-access rule "${secret}"`);
				if (ctx.hasUI) {
					ctx.ui.notify(`Blocked read of ${rule}: ${params.path}`, "warning");
				}
				pi.appendEntry<GuardAudit>("guard-block", {
					tool: "read",
					rule,
					action: "blocked",
					detail: absolutePath,
				});
				return {
					content: [
						{
							type: "text",
							text: `${BLOCKED_PREFIX} ${blockReason(`"${params.path}" matches the ${rule} in guard-rules.json.`)}`,
						},
					],
					details: undefined,
				};
			}

			await logAccess(absolutePath, true);
			return baseTools(ctx.cwd).read.execute(toolCallId, params, signal, onUpdate);
		},

		renderCall(args, theme, context) {
			markStarted(context);
			const meta: string[] = [];
			if (args.offset) meta.push(theme.fg("dim", `offset ${args.offset}`));
			if (args.limit) meta.push(theme.fg("dim", `limit ${args.limit}`));
			return new Text(
				callRow(theme, {
					glyph: SYM.read,
					name: "read",
					arg: fileLink(
						resolve(context.cwd, args.path),
						theme.fg("accent", elide(shortPath(context.cwd, args.path), PATH_WIDTH)),
						args.offset,
					),
					meta,
				}),
				0,
				0,
			);
		},

		renderResult(result, { expanded, isPartial }, theme, context) {
			markSettled(context, isPartial);
			const state: TimedState = context.state;

			if (isPartial) {
				return new Text(statusRow(theme, "running", "reading", [], state.frame), 0, 0);
			}

			const details = result.details as ReadToolDetails | undefined;
			const content = result.content[0];

			if (content?.type === "image") {
				return new Text(statusRow(theme, "success", "image", [theme.fg("dim", elapsed(state))]), 0, 0);
			}
			if (content?.type !== "text") {
				return new Text(statusRow(theme, "error", "no content"), 0, 0);
			}
			if (content.text.startsWith(BLOCKED_PREFIX)) {
				return new Text(statusRow(theme, "error", "blocked (zero-access path)"), 0, 0);
			}

			const meta = [theme.fg("dim", plural(countLines(content.text), "line"))];
			if (details?.truncation?.truncated) {
				meta.push(theme.fg("warning", `truncated from ${details.truncation.totalLines}`));
			}
			meta.push(theme.fg("dim", elapsed(state)));

			const budget = expanded ? PREVIEW.EXPANDED : PREVIEW.READ;
			const container = reuseContainer(context);
			container.addChild(
				new BodyText({
					theme,
					mode: "indent",
					rows: numbered(
						theme,
						content.text,
						getLanguageFromPath(context.args.path),
						context.args.offset ?? 1,
						budget,
					),
					hidden: Math.max(0, countLines(content.text) - budget),
					more: (hidden) => moreRow(theme, hidden, "line"),
				}),
			);
			container.addChild(new Text(statusRow(theme, "success", "read", meta), 0, 0));
			return container;
		},
	});

	// --- Bash tool: show command, output tail and outcome ---
	pi.registerTool({
		name: "bash",
		label: "bash",
		description: template.bash.description,
		parameters: template.bash.parameters,

		async execute(toolCallId, params, signal, onUpdate, ctx) {
			return baseTools(ctx.cwd).bash.execute(toolCallId, params, signal, onUpdate);
		},

		renderCall(args, theme, context) {
			markStarted(context);
			const meta = args.timeout ? [theme.fg("dim", `timeout ${args.timeout}s`)] : [];
			const prefix =
				context.cwd === process.cwd()
					? ""
					: theme.fg("dim", `cd ${shortPath(process.cwd(), context.cwd)} && `);
			return new Text(
				callRow(theme, {
					glyph: SYM.bash,
					name: "bash",
					arg: prefix + highlightCode(args.command, "bash").join("\n"),
					meta,
				}),
				0,
				0,
			);
		},

		renderResult(result, { expanded, isPartial }, theme, context) {
			markSettled(context, isPartial);
			const state: TimedState = context.state;

			const content = result.content[0];
			const outcome = splitBashOutput(content?.type === "text" ? content.text : "", context.isError);
			const container = reuseContainer(context);

			if (outcome.body.length > 0) {
				container.addChild(
					new BodyText({
						theme,
						mode: "gutter",
						rows: outcome.body.split("\n").map((line) => theme.fg("toolOutput", line)),
						limit: expanded ? undefined : PREVIEW.BASH,
						from: "tail",
						more: (hidden) => moreRow(theme, hidden, "line", "tail"),
					}),
				);
			}

			if (isPartial) {
				container.addChild(
					new Text(statusRow(theme, "running", "running", [theme.fg("dim", elapsed(state))], state.frame), 0, 0),
				);
				return container;
			}

			const details = result.details as BashToolDetails | undefined;
			const meta = [theme.fg("dim", plural(countLines(outcome.body), "line"))];
			if (details?.truncation?.truncated) meta.push(theme.fg("warning", "truncated"));
			meta.push(theme.fg("dim", elapsed(state)));
			container.addChild(new Text(statusRow(theme, outcome.kind, outcome.label, meta), 0, 0));
			return container;
		},
	});

	// --- Edit tool: show path and the diff ---
	pi.registerTool({
		name: "edit",
		label: "edit",
		description: template.edit.description,
		parameters: template.edit.parameters,
		renderShell: "default",

		async execute(toolCallId, params, signal, onUpdate, ctx) {
			return baseTools(ctx.cwd).edit.execute(toolCallId, params, signal, onUpdate);
		},

		renderCall(args, theme, context) {
			markStarted(context);
			return new Text(
				callRow(theme, {
					glyph: SYM.edit,
					name: "edit",
					arg: pathArg(theme, context.cwd, args.path),
				}),
				0,
				0,
			);
		},

		renderResult(result, { expanded, isPartial }, theme, context) {
			markSettled(context, isPartial);
			const state: TimedState = context.state;

			if (isPartial) {
				return new Text(statusRow(theme, "running", "editing", [theme.fg("dim", elapsed(state))], state.frame), 0, 0);
			}

			const content = result.content[0];
			if (context.isError || (content?.type === "text" && content.text.startsWith("Error"))) {
				return new Text(statusRow(theme, "error", firstLine(content, "edit failed")), 0, 0);
			}

			const details = result.details as EditToolDetails | undefined;
			if (!details?.diff) {
				return new Text(statusRow(theme, "success", "applied", [theme.fg("dim", elapsed(state))]), 0, 0);
			}

			const { added, removed } = countPatch(details.patch);
			const container = reuseContainer(context);
			container.addChild(
				new BodyText({
					theme,
					mode: "indent",
					rows: renderDiff(details.diff).split("\n"),
					limit: expanded ? undefined : PREVIEW.DIFF_ROWS,
					more: (hidden) => moreRow(theme, hidden, "line"),
				}),
			);
			container.addChild(
				new Text(
					statusRow(theme, "success", "applied", [
						`${theme.fg("toolDiffAdded", `+${added}`)} ${theme.fg("toolDiffRemoved", `-${removed}`)}`,
						theme.fg("dim", elapsed(state)),
					]),
					0,
					0,
				),
			);
			return container;
		},
	});

	// --- Write tool: show path and a highlighted preview ---
	pi.registerTool({
		name: "write",
		label: "write",
		description: template.write.description,
		parameters: template.write.parameters,

		async execute(toolCallId, params, signal, onUpdate, ctx) {
			return baseTools(ctx.cwd).write.execute(toolCallId, params, signal, onUpdate);
		},

		renderCall(args, theme, context) {
			markStarted(context);
			return new Text(
				callRow(theme, {
					glyph: SYM.write,
					name: "write",
					arg: pathArg(theme, context.cwd, args.path),
					meta: [theme.fg("dim", plural(countLines(args.content), "line"))],
				}),
				0,
				0,
			);
		},

		renderResult(result, { expanded, isPartial }, theme, context) {
			markSettled(context, isPartial);
			const state: TimedState = context.state;

			if (isPartial) {
				return new Text(statusRow(theme, "running", "writing", [theme.fg("dim", elapsed(state))], state.frame), 0, 0);
			}

			const content = result.content[0];
			if (context.isError || (content?.type === "text" && content.text.startsWith("Error"))) {
				return new Text(statusRow(theme, "error", firstLine(content, "write failed")), 0, 0);
			}

			const source = context.args.content;
			const budget = expanded ? PREVIEW.EXPANDED : PREVIEW.WRITE_HEAD;
			const container = reuseContainer(context);
			container.addChild(
				new BodyText({
					theme,
					mode: "indent",
					rows: numbered(theme, source, getLanguageFromPath(context.args.path), 1, budget),
					hidden: Math.max(0, countLines(source) - budget),
					more: (hidden) => moreRow(theme, hidden, "line"),
				}),
			);
			container.addChild(
				new Text(
					statusRow(theme, "success", "written", [
						theme.fg("dim", plural(countLines(source), "line")),
						theme.fg("dim", elapsed(state)),
					]),
					0,
					0,
				),
			);
			return container;
		},
	});

	// Command to view the access log
	pi.registerCommand("read-log", {
		description: "View the file access log",
		handler: async (_args, ctx) => {
			try {
				const log = readFileSync(LOG_FILE, "utf-8");
				const lines = log.trim().split("\n").slice(-20); // Last 20 entries
				ctx.ui.notify(`Recent file access:\n${lines.join("\n")}`, "info");
			} catch {
				ctx.ui.notify("No access log found", "info");
			}
		},
	});
}
