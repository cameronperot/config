import type { Message } from "@earendil-works/pi-ai";

const APPROVAL_PREFIX = "Approval required (no UI):\n";

export function approvalRequiredReason(tool: string, input: unknown, cwd: string, reason: string): string {
	return `${APPROVAL_PREFIX}${JSON.stringify({ tool, input, cwd, reason }, null, 2)}\n\nThis action was not executed. Do not retry it through another tool or command. Return this approval request to the parent agent, or to the user when running directly. The parent must present the action for approval through its normal guards before executing it in the stated working directory, then delegate any remaining work. A hard policy block cannot be approved this way.`;
}

/** Preserve approval requests even if the child's final response omits them. */
export function getApprovalRequests(messages: Message[]): string[] {
	return [...new Set(messages.flatMap((message) => {
		if (message.role !== "toolResult" || !message.isError) return [];
		return message.content.flatMap((part) =>
			part.type === "text" && part.text.startsWith(APPROVAL_PREFIX) ? [part.text] : [],
		);
	}))];
}
