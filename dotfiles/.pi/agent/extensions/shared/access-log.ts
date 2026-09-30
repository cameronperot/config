/**
 * The shared read-access log.
 *
 * Imported by built-in-tool-renderer.ts (records allowed reads) and
 * permission-gate.ts (records blocked access), so a path blocked for `read` and the
 * same path blocked for `cat` land in one file. Policy itself lives in
 * `rules.ts`; this module only records what happened.
 *
 * This directory has no index.ts and no package.json, so Pi's extension
 * discovery (extensions/*.ts and extensions/*\/index.ts, one level, no
 * recursion) does not try to load it as an extension.
 */

import { appendFile } from "node:fs/promises";
import { join } from "node:path";
import { getAgentDir, withFileMutationQueue } from "@earendil-works/pi-coding-agent";

export const LOG_FILE = join(getAgentDir(), "read-access.log");

export async function logAccess(path: string, allowed: boolean, reason?: string): Promise<void> {
	const timestamp = new Date().toISOString();
	const status = allowed ? "ALLOWED" : "BLOCKED";
	const msg = reason ? ` (${reason})` : "";
	const line = `[${timestamp}] ${status}: ${path}${msg}\n`;

	try {
		await withFileMutationQueue(LOG_FILE, async () => {
			await appendFile(LOG_FILE, line);
		});
	} catch {
		// Ignore logging errors
	}
}
