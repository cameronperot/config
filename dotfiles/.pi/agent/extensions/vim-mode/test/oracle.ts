/**
 * Neovim oracle: runs keys against `nvim -n --clean --headless` and reports the resulting
 * buffer, cursor and mode, with columns converted from Neovim's byte offsets to UTF-16.
 */

import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { Cursor, Mode } from "../protocol.ts";

export interface OracleResult {
	lines: string[];
	cursor: Cursor;
	mode: Mode;
}

export interface OracleRange {
	start: Cursor;
	/** Inclusive: the start of the last selected character. */
	end: Cursor;
}

type Capture = "state" | "marks";

interface RawState {
	lines: string[];
	cursor: [number, number];
	mode: string;
}

interface RawMarks {
	start: [number, number];
	stop: [number, number];
}

const TIMEOUT_MS = 10_000;

const MODES: Record<string, Mode> = { n: "normal", i: "insert" };

// The capture runs inside the typeahead: with "xt", Neovim leaves insert mode when the
// typeahead ends, so a capture taken afterwards would always read normal mode
const SCRIPT = `
local input = vim.json.decode(table.concat(vim.fn.readfile(vim.env.ORACLE_INPUT), "\\n"))

function _G.oracle_capture()
	local result
	if input.capture == "marks" then
		result = {
			start = vim.api.nvim_buf_get_mark(0, "<"),
			stop = vim.api.nvim_buf_get_mark(0, ">"),
		}
	else
		result = {
			lines = vim.api.nvim_buf_get_lines(0, 0, -1, false),
			cursor = vim.api.nvim_win_get_cursor(0),
			mode = vim.api.nvim_get_mode().mode,
		}
	end
	vim.fn.writefile({ vim.json.encode(result) }, vim.env.ORACLE_OUTPUT)
end

vim.api.nvim_buf_set_lines(0, 0, -1, false, input.lines)
vim.api.nvim_win_set_cursor(0, { input.line + 1, input.col })
local keys = input.keys .. "<Cmd>lua oracle_capture()<CR><Esc>"
vim.api.nvim_feedkeys(vim.api.nvim_replace_termcodes(keys, true, true, true), "xt", false)
vim.cmd("qa!")
`;

function byteOffset(line: string, col: number): number {
	return Buffer.byteLength(line.slice(0, col), "utf8");
}

function utf16Offset(line: string, bytes: number): number {
	const encoded = Buffer.from(line, "utf8");
	if (bytes > encoded.length) {
		throw new Error(`byte column ${bytes} is past the end of ${JSON.stringify(line)}`);
	}
	return encoded.subarray(0, bytes).toString("utf8").length;
}

function toCursor(lines: readonly string[], [row, bytes]: [number, number]): Cursor {
	const line = row - 1;
	return { line, col: utf16Offset(lines[line] ?? "", bytes) };
}

function runNeovim(text: string, cursor: Cursor, keys: string, capture: Capture): unknown {
	const lines = text.split("\n");
	const dir = mkdtempSync(join(tmpdir(), "vim-mode-oracle-"));
	try {
		const script = join(dir, "oracle.lua");
		const input = join(dir, "input.json");
		const output = join(dir, "output.json");
		writeFileSync(script, SCRIPT);
		writeFileSync(
			input,
			JSON.stringify({
				lines,
				line: cursor.line,
				col: byteOffset(lines[cursor.line] ?? "", cursor.col),
				keys,
				capture,
			}),
		);

		const run = spawnSync(
			"nvim",
			["-n", "--clean", "--headless", "-c", `luafile ${script}`],
			{
				env: { ...process.env, ORACLE_INPUT: input, ORACLE_OUTPUT: output },
				encoding: "utf8",
				timeout: TIMEOUT_MS,
			},
		);
		if (run.error !== undefined) {
			throw new Error(`could not run nvim: ${run.error.message}`);
		}
		if (run.status !== 0) {
			throw new Error(`nvim exited with ${run.status}: ${run.stderr}`);
		}
		return JSON.parse(readFileSync(output, "utf8"));
	} finally {
		rmSync(dir, { recursive: true, force: true });
	}
}

/**
 * Runs `keys` in normal mode against `text` with the cursor at `cursor`.
 *
 * @param text - Buffer text, lines separated by `\n`.
 * @param cursor - Start position; `col` is a UTF-16 offset.
 * @param keys - Keys in Vim notation, e.g. `ciwfoo<Esc>`.
 * @returns The buffer lines, the cursor (UTF-16) and the mode once the keys are consumed.
 */
export function runCase(text: string, cursor: Cursor, keys: string): OracleResult {
	const raw = runNeovim(text, cursor, keys, "state") as RawState;
	const mode = MODES[raw.mode];
	if (mode === undefined) {
		throw new Error(`unexpected Neovim mode '${raw.mode}' after ${JSON.stringify(keys)}`);
	}
	return { lines: raw.lines, cursor: toCursor(raw.lines, raw.cursor), mode };
}

/**
 * Selects a text object with `v<object><Esc>` and reads the `'<` and `'>` marks.
 *
 * @param text - Buffer text, lines separated by `\n`.
 * @param cursor - Start position; `col` is a UTF-16 offset.
 * @param object - Text-object keys, e.g. `iw` or `a"`.
 * @returns The selected range, both ends as UTF-16 positions.
 */
export function selectRange(text: string, cursor: Cursor, object: string): OracleRange {
	const raw = runNeovim(text, cursor, `v${object}<Esc>`, "marks") as RawMarks;
	const lines = text.split("\n");
	return { start: toCursor(lines, raw.start), end: toCursor(lines, raw.stop) };
}
