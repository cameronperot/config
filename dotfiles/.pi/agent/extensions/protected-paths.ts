/**
 * Protected Paths Extension
 *
 * Blocks `write` and `edit` against the policy in `guard-rules.json`: paths in
 * `zeroAccessPaths` (secrets, which are also unreadable) and paths in
 * `readOnlyPaths` (lockfiles, build output, shell rc files — readable, but not
 * ours to rewrite).
 *
 * Matching is per path segment, so a `.env` rule no longer catches
 * `.env-example` or a directory called `environments/`.
 * Explicit `grep` targets also obey zero-access rules; recursive searches and
 * shell indirection are not contained by this filename-based guard.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { blockReason, type GuardAudit, readOnlyMatch, takeLoadIssue, zeroAccessMatch } from "./shared/rules.ts";

export default function (pi: ExtensionAPI) {
	pi.on("tool_call", async (event, ctx) => {
		if (event.toolName !== "write" && event.toolName !== "edit" && event.toolName !== "grep") {
			return undefined;
		}

		if (ctx.hasUI) {
			const issue = takeLoadIssue(ctx.cwd);
			if (issue) ctx.ui.notify(`Guard policy: ${issue}`, "warning");
		}

		const path = (event.input.path as string | undefined) ?? ".";
		const secret = zeroAccessMatch(path, ctx.cwd);
		const readOnly = secret || event.toolName === "grep" ? undefined : readOnlyMatch(path, ctx.cwd);
		const rule = secret
			? `zero-access path "${secret}"`
			: readOnly
				? `read-only path "${readOnly}"`
				: undefined;

		if (!rule) {
			return undefined;
		}

		if (ctx.hasUI) {
			ctx.ui.notify(`Blocked ${event.toolName} to ${rule}: ${path}`, "warning");
		}
		pi.appendEntry<GuardAudit>("guard-block", {
			tool: event.toolName,
			rule,
			action: "blocked",
			detail: path,
		});

		return { block: true, reason: blockReason(`"${path}" matches ${rule} in guard-rules.json.`) };
	});
}
