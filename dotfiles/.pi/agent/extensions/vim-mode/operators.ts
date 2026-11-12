/**
 * Operators and line-editing commands. An operator takes a range from a motion or text object
 * and deletes, changes or yanks it, following Neovim's `do_pending_operator`, `op_delete`,
 * `op_change`, `do_put` and `do_join`.
 */

import type { MotionKind } from "./motions.ts";
import { Walker, endWord, forwardWord, motionStatus, runMotion } from "./motions.ts";
import type { Cursor, FindSearch, Register } from "./protocol.ts";
import { failedObjectStop, isTextObject, selectTextObject } from "./textobjects.ts";
import {
	clampNormalCol,
	colAtDisplay,
	lastGraphemeStart,
	nextBoundary,
	prevBoundary,
} from "./text.ts";

export type Operator = "d" | "c" | "y";

/** Operator keys, optionally behind a count and register prefix, as in `2"+y`. */
const OPERATOR_PENDING = /^(?:[1-9][0-9]*|"[\s\S])*[dcy]/u;

/** Whether the pending keys have an operator waiting for its motion. */
export function operatorPending(pending: string): boolean {
	return OPERATOR_PENDING.test(pending);
}

/** Where an operator's motion or text object reaches, before the range rules apply. */
export interface Target {
	readonly from: Cursor;
	readonly to: Cursor;
	readonly kind: MotionKind;
	/** The motion failed: Neovim cancels the operator without a change. */
	readonly failed: boolean;
	/** The motion pins the wanted column to the line end, as `$` does. */
	readonly pinned?: boolean;
	/** A failed `%` on an empty line operates on its line break, which Neovim then removes. */
	readonly takesBreak?: boolean;
	readonly lastFind?: FindSearch;
}

export interface TargetContext {
	readonly lines: readonly string[];
	readonly cursor: Cursor;
	/** Counts typed before the operator and before the motion, multiplied; null when none. */
	readonly count: number | null;
	/** Display column that vertical motions aim for. */
	readonly wantedCol: number;
	readonly lastFind: FindSearch | null;
}

export type TargetStatus = "complete" | "prefix" | "none";

/**
 * Whether keys typed after an operator form a complete target, the start of one, or neither.
 *
 * @param operator - The operator, whose repeated key (`dd`) targets whole lines.
 * @param keys - Keys after the operator and its motion count.
 */
export function targetStatus(operator: Operator, keys: string): TargetStatus {
	if (keys === operator || "hljk".includes(keys)) return "complete";
	const [first = ""] = keys;
	if (first === "i" || first === "a") {
		if (keys.length === 1) return "prefix";
		return isTextObject(keys) ? "complete" : "none";
	}
	return motionStatus(keys);
}

const FORGIVING_MOTIONS = new Set(["e", "E", "%"]);

const isWhite = (char: string | undefined): boolean => char === " " || char === "\t";

/** Number of leading spaces and tabs: the column `I` inserts at, and the indent `o` copies. */
export function leadingWhite(text: string): number {
	let count = 0;
	while (isWhite(text[count])) count++;
	return count;
}

function sameCursor(a: Cursor, b: Cursor): boolean {
	return a.line === b.line && a.col === b.col;
}

function isBefore(a: Cursor, b: Cursor): boolean {
	return a.line < b.line || (a.line === b.line && a.col < b.col);
}

/** The cursor column of Vim's `BL_WHITE | BL_FIX`: the first non-blank, or the last character. */
function firstNonBlankCol(text: string): number {
	return clampNormalCol(text, leadingWhite(text));
}

function wordTarget(
	operator: Operator,
	big: boolean,
	{ lines, cursor, count }: TargetContext,
): Target {
	const walker = new Walker(lines, cursor, big);
	const n = count ?? 1;
	const char = walker.text[cursor.col];
	let kind: MotionKind = "exclusive";
	if (operator === "c" && char !== undefined && !isWhite(char)) {
		// `cw` on a word changes up to its end, as `ce` does
		endWord(walker, n, true);
		kind = "inclusive";
	} else {
		forwardWord(walker, n, true);
	}
	const to = { ...walker.cursor };
	if (isBefore(cursor, to) && to.col > 0 && walker.atLineEnd) {
		// A motion that ends past the last character settles on it and includes it
		to.col = prevBoundary(walker.text, to.col);
		kind = "inclusive";
	}
	return { from: cursor, to, kind, failed: false };
}

function verticalTarget(
	keys: string,
	{ lines, cursor, wantedCol }: TargetContext,
	linesAway: number,
): Target {
	const last = lines.length - 1;
	const line =
		keys === "j"
			? Math.min(cursor.line + linesAway, last)
			: Math.max(cursor.line - linesAway, 0);
	const failed = line === cursor.line;
	const to = failed ? cursor : { line, col: colAtDisplay(lines[line] ?? "", wantedCol) };
	return { from: cursor, to, kind: "linewise", failed };
}

function horizontalTarget(keys: string, { lines, cursor, count }: TargetContext): Target {
	const text = lines[cursor.line] ?? "";
	let col = cursor.col;
	for (let i = 0; i < (count ?? 1); i++) {
		if (keys === "h" ? col === 0 : col >= text.length) break;
		col = keys === "h" ? prevBoundary(text, col) : nextBoundary(text, col);
	}
	return { from: cursor, to: { line: cursor.line, col }, kind: "exclusive", failed: false };
}

/**
 * Resolves the keys after an operator to the two ends of its range. Returns null when a text
 * object does not exist at the cursor.
 *
 * @param operator - The operator.
 * @param keys - A complete target per `targetStatus`.
 * @param context - Buffer, cursor and the state motions read.
 */
export function resolveTarget(
	operator: Operator,
	keys: string,
	context: TargetContext,
): Target | null {
	const { lines, cursor, count } = context;
	if (keys === operator) {
		const away = (count ?? 1) - 1;
		const last = lines.length - 1;
		const line = Math.min(cursor.line + away, last);
		return {
			from: cursor,
			to: { line, col: cursor.col },
			kind: "linewise",
			failed: away > 0 && cursor.line === last,
		};
	}
	if (keys === "h" || keys === "l") return horizontalTarget(keys, context);
	if (keys === "j" || keys === "k") return verticalTarget(keys, context, count ?? 1);
	if (keys === "w" || keys === "W") return wordTarget(operator, keys === "W", context);

	if (keys.startsWith("i") || keys.startsWith("a")) {
		const range = selectTextObject(lines, cursor, keys, count);
		if (range === null) {
			// A word object that ran out of text still leaves the cursor where its search stopped
			const stop = failedObjectStop(lines, cursor, keys, count);
			return stop === null ? null : { from: cursor, to: stop, kind: "exclusive", failed: true };
		}
		const kind = range.inclusive ? "inclusive" : "exclusive";
		return { from: range.start, to: range.end, kind, failed: false };
	}

	const result = runMotion(keys, context);
	const next = lines[cursor.line + 1];
	if (keys === "%" && count === null && result.failed && next !== undefined && lines[cursor.line] === "") {
		const to = { line: cursor.line + 1, col: 0 };
		return { from: cursor, to, kind: "exclusive", failed: false, takesBreak: true };
	}
	// Word motions and `%` still operate on what they passed when they run out of text
	const forgiving = FORGIVING_MOTIONS.has(keys) && !(keys === "%" && count !== null);
	// Under an operator, `N%` reaches its line as a characterwise motion
	const kind = keys === "%" && count !== null ? "exclusive" : result.kind;
	return {
		from: cursor,
		to: result.cursor,
		kind,
		failed: result.failed && !forgiving,
		pinned: result.want === "end",
		lastFind: result.lastFind,
	};
}

/** The text an operator acts on, after Neovim's rules for an exclusive end in column 0. */
export interface Range {
	readonly start: Cursor;
	readonly end: Cursor;
	/** With `inclusive`, `end` is the last character taken; otherwise the first one left out. */
	readonly inclusive: boolean;
	readonly linewise: boolean;
	/** The end moved to the previous line (`:h exclusive-linewise`). */
	readonly endAdjusted: boolean;
	/** The range is taken as it stands: a multi-line delete never widens to whole lines. */
	readonly literal?: boolean;
}

export function resolveRange(
	lines: readonly string[],
	from: Cursor,
	to: Cursor,
	kind: MotionKind,
): Range {
	const [start, end] = isBefore(to, from) ? [to, from] : [from, to];
	if (kind === "linewise") {
		return { start, end, inclusive: false, linewise: true, endAdjusted: false };
	}

	let inclusive = kind === "inclusive";
	if (inclusive || end.col !== 0 || end.line === start.line) {
		return { start, end, inclusive, linewise: false, endAdjusted: false };
	}

	// An exclusive end in column 0 moves back to the end of the previous line
	const endLine = end.line - 1;
	if (leadingWhite(lines[start.line] ?? "") >= start.col) {
		return {
			start,
			end: { line: endLine, col: 0 },
			inclusive: false,
			linewise: true,
			endAdjusted: true,
		};
	}
	const text = lines[endLine] ?? "";
	let col = 0;
	if (text !== "") {
		col = lastGraphemeStart(text);
		inclusive = true;
	}
	return { start, end: { line: endLine, col }, inclusive, linewise: false, endAdjusted: true };
}

export interface OperatorResult {
	readonly lines: readonly string[];
	readonly cursor: Cursor;
	/** The new unnamed register, or null to leave it alone. */
	readonly register: Register | null;
	/** Enter insert mode. */
	readonly insert: boolean;
	/** Line holding an autoindent that Escape removes. */
	readonly autoIndent: number | null;
}

function textAt(lines: readonly string[], line: number): string {
	return lines[line] ?? "";
}

/** End of the range as an exclusive position. */
function exclusiveEnd(lines: readonly string[], { end, inclusive }: Range): Cursor {
	const text = textAt(lines, end.line);
	if (!inclusive) return end;
	const col = end.col >= text.length ? text.length : nextBoundary(text, end.col);
	return { line: end.line, col };
}

function sliceText(lines: readonly string[], start: Cursor, end: Cursor): readonly string[] {
	if (start.line === end.line) return [textAt(lines, start.line).slice(start.col, end.col)];
	return [
		textAt(lines, start.line).slice(start.col),
		...lines.slice(start.line + 1, end.line),
		textAt(lines, end.line).slice(0, end.col),
	];
}

function removeCharwise(
	lines: readonly string[],
	start: Cursor,
	end: Cursor,
): { lines: readonly string[]; joined: string } {
	const head = textAt(lines, start.line).slice(0, start.col);
	const joined = head + textAt(lines, end.line).slice(end.col);
	return {
		lines: [...lines.slice(0, start.line), joined, ...lines.slice(end.line + 1)],
		joined,
	};
}

function deleteLinewise(
	operator: Operator,
	lines: readonly string[],
	range: Range,
	wantedCol: number,
): OperatorResult {
	const { start, end } = range;
	const register = { lines: lines.slice(start.line, end.line + 1), linewise: true };
	if (operator === "c") {
		const first = textAt(lines, start.line);
		const indent = first.slice(0, leadingWhite(first));
		return {
			lines: [...lines.slice(0, start.line), indent, ...lines.slice(end.line + 1)],
			cursor: { line: start.line, col: indent.length },
			register,
			insert: true,
			autoIndent: indent === "" ? null : start.line,
		};
	}

	const rest = [...lines.slice(0, start.line), ...lines.slice(end.line + 1)];
	if (rest.length === 0) rest.push("");
	const line = Math.min(start.line, rest.length - 1);
	const text = textAt(rest, line);
	const col = range.endAdjusted ? firstNonBlankCol(text) : colAtDisplay(text, wantedCol);
	return { lines: rest, cursor: { line, col }, register, insert: false, autoIndent: null };
}

/**
 * Runs an operator over a range.
 *
 * @param operator - `d`, `c` or `y`.
 * @param lines - Buffer lines.
 * @param range - The range from `resolveRange`.
 * @param wantedCol - Display column to return to after a linewise delete.
 */
export function applyOperator(
	operator: Operator,
	lines: readonly string[],
	range: Range,
	wantedCol: number,
): OperatorResult {
	const { start } = range;
	const stop = exclusiveEnd(lines, range);
	const empty =
		!range.linewise &&
		sameCursor(start, range.end) &&
		(!range.inclusive ||
			(operator === "y" && range.end.col >= textAt(lines, range.end.line).length));

	if (operator === "y") {
		const yanked = range.linewise
			? lines.slice(start.line, range.end.line + 1)
			: sliceText(lines, start, stop);
		return {
			lines,
			cursor: start,
			register: { lines: yanked, linewise: range.linewise },
			insert: false,
			autoIndent: null,
		};
	}

	let linewise = range.linewise;
	if (operator === "d" && !linewise && !range.literal && start.line !== range.end.line) {
		// A multi-line delete that starts in the indent and ends at a line end takes whole lines
		const tail = textAt(lines, stop.line).slice(stop.col);
		linewise = /^[ \t]*$/.test(tail) && leadingWhite(textAt(lines, start.line)) >= start.col;
	}
	if (linewise) return deleteLinewise(operator, lines, { ...range, linewise }, wantedCol);

	const nothing = sameCursor(start, stop);
	if (empty || (nothing && operator === "d")) {
		return { lines, cursor: start, register: null, insert: operator === "c", autoIndent: null };
	}

	const register = { lines: sliceText(lines, start, stop), linewise: false };
	const { lines: edited, joined } = removeCharwise(lines, start, stop);
	const insert = operator === "c";
	const col = insert ? start.col : clampNormalCol(joined, start.col);
	return {
		lines: edited,
		cursor: { line: start.line, col },
		register,
		insert,
		autoIndent: null,
	};
}

export interface Edit {
	readonly lines: readonly string[];
	readonly cursor: Cursor;
}

/**
 * Puts the register after (`p`) or before (`P`) the cursor.
 *
 * @param lines - Buffer lines.
 * @param cursor - Cursor position.
 * @param register - Register contents.
 * @param count - Number of copies.
 * @param before - Put before the cursor instead of after it.
 */
export function putRegister(
	lines: readonly string[],
	cursor: Cursor,
	register: Register,
	count: number,
	before: boolean,
): Edit {
	if (register.linewise) {
		const inserted = Array.from({ length: count }, () => register.lines).flat();
		const at = before ? cursor.line : cursor.line + 1;
		const first = inserted[0] ?? "";
		return {
			lines: [...lines.slice(0, at), ...inserted, ...lines.slice(at)],
			cursor: { line: at, col: firstNonBlankCol(first) },
		};
	}

	const text = textAt(lines, cursor.line);
	const col = before || text === "" ? cursor.col : nextBoundary(text, cursor.col);
	const inserted = register.lines.join("\n").repeat(count);
	const combined = text.slice(0, col) + inserted + text.slice(col);
	const edited = [
		...lines.slice(0, cursor.line),
		...combined.split("\n"),
		...lines.slice(cursor.line + 1),
	];
	if (inserted === "") return { lines, cursor };
	if (inserted.includes("\n")) return { lines: edited, cursor: { line: cursor.line, col } };
	return { lines: edited, cursor: { line: cursor.line, col: col + lastGraphemeStart(inserted) } };
}

/**
 * Joins `count` lines starting at `line`, as `J` does with `nojoinspaces`. Returns null when
 * there are too few lines below.
 *
 * @param lines - Buffer lines.
 * @param line - First line of the join.
 * @param count - Typed count, or null; `J` joins at least two lines.
 */
export function joinLines(
	lines: readonly string[],
	line: number,
	count: number | null,
): Edit | null {
	let n = Math.max(count ?? 2, 2);
	const last = lines.length - 1;
	if (line + n - 1 > last) {
		if (n <= 2) return null;
		n = last - line + 1;
	}

	let joined = textAt(lines, line);
	let end1 = joined.at(-1) ?? "";
	let end2 = joined.at(-2) ?? "";
	let col = 0;
	for (let t = 1; t < n; t++) {
		const raw = textAt(lines, line + t);
		const piece = raw.slice(leadingWhite(raw));
		let spaces = 0;
		if (piece !== "" && !piece.startsWith(")") && joined !== "" && end1 !== "\t") {
			if (end1 === " ") end1 = end2;
			else spaces = 1;
		}
		col = joined.length;
		joined += " ".repeat(spaces) + piece;
		end1 = piece.at(-1) ?? "";
		end2 = piece.at(-2) ?? "";
	}
	return {
		lines: [...lines.slice(0, line), joined, ...lines.slice(line + n)],
		cursor: { line, col: clampNormalCol(joined, col) },
	};
}

/**
 * Replaces `count` characters under the cursor. Returns null when fewer remain on the line.
 *
 * @param lines - Buffer lines.
 * @param cursor - Cursor position.
 * @param char - The replacement grapheme.
 * @param count - Typed count, or null.
 */
export function replaceChars(
	lines: readonly string[],
	cursor: Cursor,
	char: string,
	count: number | null,
): Edit | null {
	const n = count ?? 1;
	const text = textAt(lines, cursor.line);
	let end = cursor.col;
	for (let i = 0; i < n; i++) {
		if (end >= text.length) return null;
		end = nextBoundary(text, end);
	}
	const edited = text.slice(0, cursor.col) + char.repeat(n) + text.slice(end);
	return {
		lines: lines.with(cursor.line, edited),
		cursor: { line: cursor.line, col: cursor.col + char.repeat(n - 1).length },
	};
}

function swapCase(grapheme: string): string {
	const lower = grapheme.toLowerCase();
	const swapped = grapheme !== lower ? lower : grapheme.toUpperCase();
	// Case mappings that change the number of characters (`ß` to `SS`) are left alone
	return [...swapped].length === [...grapheme].length ? swapped : grapheme;
}

/**
 * Toggles the case of `count` characters from the cursor and moves past them. Returns null on
 * an empty line.
 *
 * @param lines - Buffer lines.
 * @param cursor - Cursor position.
 * @param count - Typed count, or null.
 */
export function toggleCase(
	lines: readonly string[],
	cursor: Cursor,
	count: number | null,
): Edit | null {
	const text = textAt(lines, cursor.line);
	if (text === "") return null;

	let end = cursor.col;
	for (let i = 0; i < (count ?? 1) && end < text.length; i++) end = nextBoundary(text, end);
	const swapped = Array.from(
		text.slice(cursor.col, end).matchAll(/[\s\S]/gu),
		([char]) => swapCase(char),
	).join("");
	const head = text.slice(0, cursor.col) + swapped;
	const edited = head + text.slice(end);
	return {
		lines: lines.with(cursor.line, edited),
		cursor: { line: cursor.line, col: clampNormalCol(edited, head.length) },
	};
}

/**
 * Opens a line above or below `line` with that line's indent.
 *
 * @param lines - Buffer lines.
 * @param line - Line the cursor is on.
 * @param below - Open below (`o`) instead of above (`O`).
 */
export function openLine(
	lines: readonly string[],
	line: number,
	below: boolean,
): Edit & { readonly autoIndent: number | null } {
	const text = textAt(lines, line);
	const indent = text.slice(0, leadingWhite(text));
	const at = below ? line + 1 : line;
	return {
		lines: [...lines.slice(0, at), indent, ...lines.slice(at)],
		cursor: { line: at, col: indent.length },
		autoIndent: indent === "" ? null : at,
	};
}
