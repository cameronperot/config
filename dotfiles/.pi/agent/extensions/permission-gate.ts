/** Enforce shared path and command policy, with one confirmation per call. */

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { logAccess } from "./shared/access-log.ts";
import { approvalRequiredReason } from "./shared/approval.ts";
import { blockReason, type GuardAudit, policyDecision, takeLoadIssue } from "./shared/rules.ts";

export default function (pi: ExtensionAPI) {
	function reportPolicyIssue(ctx: ExtensionContext): void {
		const issue = takeLoadIssue(ctx.cwd);
		if (!issue) return;
		if (ctx.hasUI) ctx.ui.notify(`Guard policy: ${issue}`, "warning");
		else process.stderr.write(`Guard policy: ${issue}\n`);
	}

	pi.on("session_start", async (_event, ctx) => reportPolicyIssue(ctx));
	pi.on("tool_call", async (event, ctx) => {
		reportPolicyIssue(ctx);

		const hit = policyDecision(event.toolName, event.input, ctx.cwd);
		if (!hit) return undefined;
		const input = event.input as Record<string, unknown>;
		const detail = (input.command ?? input.path ?? ".") as string;
		if (hit.blockedAccess) await logAccess(hit.blockedAccess, false, `${event.toolName}: ${hit.reason}`);

		if (!hit.ask) {
			if (ctx.hasUI) {
				ctx.ui.notify(`Blocked ${event.toolName}: ${hit.reason}`, "warning");
			}
			pi.appendEntry<GuardAudit>("guard-block", {
				tool: event.toolName,
				rule: hit.reason,
				action: "blocked",
				detail,
			});
			return { block: true, reason: blockReason(`${hit.reason}. Blocked by guard-rules.json.`) };
		}

		if (!ctx.hasUI) {
			pi.appendEntry<GuardAudit>("guard-block", {
				tool: event.toolName,
				rule: hit.reason,
				action: "blocked",
				detail,
			});
			return { block: true, reason: approvalRequiredReason(event.toolName, event.input, ctx.cwd, hit.reason) };
		}

		const choice = await ctx.ui.select(`⚠️ ${hit.reason}:\n\n  ${detail}\n\nAllow?`, ["Yes", "No"]);
		if (choice !== "Yes") {
			pi.appendEntry<GuardAudit>("guard-block", {
				tool: event.toolName,
				rule: hit.reason,
				action: "blocked_by_user",
				detail,
			});
			return { block: true, reason: blockReason(`Blocked by user: ${hit.reason}.`) };
		}

		pi.appendEntry<GuardAudit>("guard-block", {
			tool: event.toolName,
			rule: hit.reason,
			action: "allowed_by_user",
			detail,
		});
		return undefined;
	});
}
