/**
 * Protected Paths (bash) Extension
 *
 * Companion to protected-paths.ts, which guards the write and edit tools, and to
 * the `read` guard in built-in-tool-renderer.ts, which guards the read tool.
 * This applies the same `guard-rules.json` policy to bash:
 *
 * 1. Commands referencing a `zeroAccessPaths` entry are blocked outright and
 *    logged to the same read-access.log the read tool uses. Without this,
 *    `cat .env` walks straight past the read guard.
 * 2. Commands that look like they delete a `noDeletePaths` entry are blocked.
 * 3. Commands that look like they modify a `readOnlyPaths` entry ask for
 *    confirmation, and block when there is no UI.
 *
 * Heuristic by design: it tokenizes on shell metacharacters, so it will miss
 * indirection (sh -c, python -c, base64, variable-built paths) and may flag a
 * command that only reads a protected path into a redirect. It is a speed bump,
 * not a security boundary. It also cannot protect secrets held in environment
 * variables — the bash tool inherits the process environment, and `echo $VAR`
 * is indistinguishable from any other echo.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { approvalRequiredReason } from "./shared/approval.ts";
import { logAccess } from "./shared/access-log.ts";
import {
	blockReason,
	commandPathMatch,
	DELETE_INDICATORS,
	getRules,
	type GuardAudit,
	takeLoadIssue,
	WRITE_INDICATORS,
} from "./shared/rules.ts";

export default function (pi: ExtensionAPI) {
	pi.on("tool_call", async (event, ctx) => {
		if (event.toolName !== "bash") return undefined;

		if (ctx.hasUI) {
			const issue = takeLoadIssue(ctx.cwd);
			if (issue) ctx.ui.notify(`Guard policy: ${issue}`, "warning");
		}

		const command = event.input.command as string;
		const { rules } = getRules(ctx.cwd);

		const secret = commandPathMatch(command, rules.zeroAccessPaths, ctx.cwd);
		if (secret) {
			await logAccess(secret.token, false, "bash: matches zero-access rule");
			if (ctx.hasUI) {
				ctx.ui.notify(`Blocked bash access to zero-access path: ${secret.token}`, "warning");
			}
			pi.appendEntry<GuardAudit>("guard-block", {
				tool: "bash",
				rule: `zero-access path "${secret.pattern}"`,
				action: "blocked",
				detail: command,
			});
			return {
				block: true,
				reason: blockReason(
					`Command references "${secret.token}", which matches the zero-access rule "${secret.pattern}" in guard-rules.json. These paths are blocked for bash as well as for the read tool.`,
				),
			};
		}

		if (DELETE_INDICATORS.some((r) => r.test(command))) {
			const protectedPath = commandPathMatch(command, rules.noDeletePaths, ctx.cwd);
			if (protectedPath) {
				if (ctx.hasUI) {
					ctx.ui.notify(`Blocked bash deletion of protected path: ${protectedPath.token}`, "warning");
				}
				pi.appendEntry<GuardAudit>("guard-block", {
					tool: "bash",
					rule: `no-delete path "${protectedPath.pattern}"`,
					action: "blocked",
					detail: command,
				});
				return {
					block: true,
					reason: blockReason(
						`Command looks like it deletes or moves "${protectedPath.token}", which matches the no-delete rule "${protectedPath.pattern}" in guard-rules.json.`,
					),
				};
			}
		}

		if (!WRITE_INDICATORS.some((r) => r.test(command))) return undefined;

		const readOnly = commandPathMatch(command, rules.readOnlyPaths, ctx.cwd);
		if (!readOnly) return undefined;

		const rule = `read-only path "${readOnly.pattern}"`;
		if (!ctx.hasUI) {
			pi.appendEntry<GuardAudit>("guard-block", {
				tool: "bash",
				rule,
				action: "blocked",
				detail: command,
			});
			return {
				block: true,
				reason: approvalRequiredReason("bash", event.input, ctx.cwd, `Possible write to ${rule}.`),
			};
		}

		const choice = await ctx.ui.select(
			`⚠️ Command may modify ${rule}:\n\n  ${command}\n\nAllow?`,
			["Yes", "No"],
		);
		if (choice !== "Yes") {
			pi.appendEntry<GuardAudit>("guard-block", {
				tool: "bash",
				rule,
				action: "blocked_by_user",
				detail: command,
			});
			return { block: true, reason: blockReason(`Blocked by user: command may modify ${rule}.`) };
		}

		pi.appendEntry<GuardAudit>("guard-block", {
			tool: "bash",
			rule,
			action: "allowed_by_user",
			detail: command,
		});
		return undefined;
	});
}
