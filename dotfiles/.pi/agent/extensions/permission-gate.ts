/**
 * Permission Gate Extension
 *
 * Applies the `bashPatterns` list from `guard-rules.json` to every bash command.
 * Severity is a property of the rule rather than of this file: an entry with
 * `ask: true` prompts for confirmation, an entry without it blocks outright. So
 * `git reset --hard` can ask while `git filter-branch` refuses, from one list.
 *
 * Rules that ask still block when there is no UI to ask through.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { approvalRequiredReason } from "./shared/approval.ts";
import { blockReason, type GuardAudit, matchingBashPatterns, takeLoadIssue } from "./shared/rules.ts";

export default function (pi: ExtensionAPI) {
	pi.on("tool_call", async (event, ctx) => {
		if (event.toolName !== "bash") return undefined;

		if (ctx.hasUI) {
			const issue = takeLoadIssue(ctx.cwd);
			if (issue) ctx.ui.notify(`Guard policy: ${issue}`, "warning");
		}

		const command = event.input.command as string;
		const hits = matchingBashPatterns(command, ctx.cwd);
		if (hits.length === 0) return undefined;
		const blocked = hits.filter((rule) => !rule.ask);
		const hit = {
			ask: blocked.length === 0,
			reason: [...new Set((blocked.length > 0 ? blocked : hits).map((rule) => rule.reason))].join("; "),
		};

		if (!hit.ask) {
			if (ctx.hasUI) {
				ctx.ui.notify(`Blocked bash command: ${hit.reason}`, "warning");
			}
			pi.appendEntry<GuardAudit>("guard-block", {
				tool: "bash",
				rule: hit.reason,
				action: "blocked",
				detail: command,
			});
			return { block: true, reason: blockReason(`${hit.reason}. Blocked by guard-rules.json.`) };
		}

		if (!ctx.hasUI) {
			pi.appendEntry<GuardAudit>("guard-block", {
				tool: "bash",
				rule: hit.reason,
				action: "blocked",
				detail: command,
			});
			return { block: true, reason: approvalRequiredReason("bash", event.input, ctx.cwd, hit.reason) };
		}

		const choice = await ctx.ui.select(`⚠️ ${hit.reason}:\n\n  ${command}\n\nAllow?`, ["Yes", "No"]);
		if (choice !== "Yes") {
			pi.appendEntry<GuardAudit>("guard-block", {
				tool: "bash",
				rule: hit.reason,
				action: "blocked_by_user",
				detail: command,
			});
			return { block: true, reason: blockReason(`Blocked by user: ${hit.reason}.`) };
		}

		pi.appendEntry<GuardAudit>("guard-block", {
			tool: "bash",
			rule: hit.reason,
			action: "allowed_by_user",
			detail: command,
		});
		return undefined;
	});
}
