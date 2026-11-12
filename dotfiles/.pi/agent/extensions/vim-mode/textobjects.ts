/**
 * Text objects: the range of `iw`, `a"`, `i(` and the rest around the cursor. The algorithms
 * follow Neovim's `current_word`, `current_quote` and `current_block` as operators run them.
 */

import { Walker, endWord, forwardWord, scanBracket } from "./motions.ts";
import type { Cursor } from "./protocol.ts";
import { nextBoundary, prevBoundary } from "./text.ts";

/**
 * A characterwise range as Neovim hands it to an operator. With `inclusive`, `end` is the last
 * character taken, which may be a line end; otherwise `end` is the first character left out and
 * may sit in column 0 of the next line.
 */
export interface TextRange {
	readonly start: Cursor;
	readonly end: Cursor;
	readonly inclusive: boolean;
}

const BLOCKS: Readonly<Record<string, readonly [string, string]>> = {
	"(": ["(", ")"],
	")": ["(", ")"],
	b: ["(", ")"],
	"[": ["[", "]"],
	"]": ["[", "]"],
	"{": ["{", "}"],
	"}": ["{", "}"],
	B: ["{", "}"],
	"<": ["<", ">"],
	">": ["<", ">"],
};

const QUOTES = new Set(['"', "'", "`"]);

/** Whether `keys` is a complete text object: `i` or `a` followed by an object character. */
export function isTextObject(keys: string): boolean {
	const [kind, ...rest] = keys;
	if (kind !== "i" && kind !== "a") return false;
	const target = rest.join("");
	return target === "w" || target === "W" || QUOTES.has(target) || target in BLOCKS;
}

const isWhite = (char: string | undefined): boolean => char === " " || char === "\t";

function incl(walker: Walker): number {
	const moved = walker.inc();
	return moved >= 1 && walker.col !== 0 ? walker.inc() : moved;
}

function decl(walker: Walker): number {
	const moved = walker.dec();
	return moved === 1 && walker.col !== 0 ? walker.dec() : moved;
}

function oneLeft(walker: Walker): boolean {
	if (walker.col === 0) return false;
	walker.col = prevBoundary(walker.text, walker.col);
	return true;
}

/** Whether the cursor is on or before the first non-blank of its line. */
function inIndent(walker: Walker): boolean {
	let indent = 0;
	while (isWhite(walker.text[indent])) indent++;
	return indent >= walker.col + 1;
}

function backInLine(walker: Walker): void {
	const startClass = walker.cls();
	while (walker.col !== 0) {
		walker.dec();
		if (walker.cls() !== startClass) {
			walker.inc();
			break;
		}
	}
}

/** Where a word object's search stopped when it found no object. */
interface Stopped {
	readonly stop: Cursor;
}

function wordObject(
	lines: readonly string[],
	cursor: Cursor,
	count: number,
	include: boolean,
	big: boolean,
): TextRange | Stopped {
	const walker = new Walker(lines, cursor, big);
	let inclusive = true;
	let includeWhite = false;

	backInLine(walker);
	let start = walker.cursor;
	if ((walker.cls() === 0) === include) {
		if (!endWord(walker, 1, true, true)) return { stop: walker.cursor };
	} else {
		forwardWord(walker, 1, true);
		if (walker.col === 0) decl(walker);
		else oneLeft(walker);
		includeWhite = include;
	}

	for (let remaining = count - 1; remaining > 0; remaining--) {
		inclusive = true;
		if (incl(walker) === -1) return { stop: walker.cursor };
		if (include !== (walker.cls() === 0)) {
			if (!forwardWord(walker, 1, true) && remaining > 1) return { stop: walker.cursor };
			// An end just past a line break must not take the first character of the next line
			if (!oneLeft(walker)) inclusive = false;
		} else if (!endWord(walker, 1, true, true)) {
			return { stop: walker.cursor };
		}
	}

	if (includeWhite && (walker.cls() !== 0 || (walker.col === 0 && !inclusive))) {
		// Without trailing white space, take the white space before the word instead
		const before = new Walker(lines, start, big);
		if (oneLeft(before)) {
			backInLine(before);
			if (before.cls() === 0 && before.col > 0) start = before.cursor;
		}
	}
	// On an empty line the object can end before it starts; the range is then the other way round
	const reversed =
		walker.line < start.line || (walker.line === start.line && walker.col < start.col);
	if (reversed) return { start: walker.cursor, end: start, inclusive };
	return { start, end: walker.cursor, inclusive };
}

function findNextQuote(line: string, from: number, quote: string, escapes: boolean): number {
	let col = from;
	for (;;) {
		const char = line[col];
		if (char === undefined) return -1;
		if (escapes && char === "\\") {
			col++;
			if (line[col] === undefined) return -1;
		} else if (char === quote) {
			return col;
		}
		col++;
	}
}

function findPrevQuote(line: string, from: number, quote: string): number {
	let col = from;
	while (col > 0) {
		col = prevBoundary(line, col);
		let escapes = 0;
		while (col - escapes > 0 && line[col - escapes - 1] === "\\") escapes++;
		if (escapes % 2 === 1) col -= escapes;
		else if (line[col] === quote) break;
	}
	return col;
}

function quoteObject(
	lines: readonly string[],
	cursor: Cursor,
	count: number,
	include: boolean,
	quote: string,
): TextRange | null {
	const line = lines[cursor.line] ?? "";
	let colStart = cursor.col;
	let colEnd: number;

	if (line[colStart] === quote) {
		// On a quote it is unknown whether it opens or closes, so pair quotes from the line start
		const firstCol = colStart;
		colStart = 0;
		for (;;) {
			colStart = findNextQuote(line, colStart, quote, false);
			if (colStart < 0 || colStart > firstCol) return null;
			colEnd = findNextQuote(line, colStart + 1, quote, true);
			if (colEnd < 0) return null;
			if (colStart <= firstCol && firstCol <= colEnd) break;
			colStart = colEnd + 1;
		}
	} else {
		colStart = findPrevQuote(line, colStart, quote);
		if (line[colStart] !== quote) {
			colStart = findNextQuote(line, colStart, quote, false);
			if (colStart < 0) return null;
		}
		colEnd = findNextQuote(line, colStart + 1, quote, true);
		if (colEnd < 0) return null;
	}

	if (include) {
		if (isWhite(line[colEnd + 1])) {
			while (isWhite(line[colEnd + 1])) colEnd++;
		} else {
			while (colStart > 0 && isWhite(line[colStart - 1])) colStart--;
		}
	}
	const quotesIncluded = include || count > 1;
	const at = (col: number): Cursor => ({ line: cursor.line, col });
	const start = at(quotesIncluded ? colStart : nextBoundary(line, colStart));
	if (!quotesIncluded) return { start, end: at(colEnd), inclusive: false };
	// A last character on the line is taken as an inclusive end rather than a line-end position
	const next = nextBoundary(line, colEnd);
	if (next >= line.length) return { start, end: at(colEnd), inclusive: true };
	return { start, end: at(next), inclusive: false };
}

function blockObject(
	lines: readonly string[],
	cursor: Cursor,
	count: number,
	include: boolean,
	[opener, closer]: readonly [string, string],
): TextRange | null {
	const walker = new Walker(lines, cursor, false);
	// On an opening bracket the block is the one it opens, so the search starts just after it
	if (opener === "{") {
		while (inIndent(walker)) {
			if (walker.inc() !== 0) break;
		}
	}
	if (walker.text[walker.col] === opener) walker.col++;

	// The search for the opening bracket ignores quotes; the one for the closing bracket does not
	const opening = { escapes: true, quotes: false };
	const backward = scanBracket(lines, walker.cursor, closer, opener, true, opening) !== null;
	let found: Cursor | null = null;
	let start: Cursor | null = null;
	for (let remaining = count; remaining > 0; remaining--) {
		found = scanBracket(lines, walker.cursor, closer, opener, backward, opening);
		if (found === null) break;
		walker.line = found.line;
		walker.col = found.col;
		start = found;
	}
	if (found === null || start === null) return null;
	const close = scanBracket(lines, start, opener, closer, false, { escapes: true, quotes: true });
	if (close === null) return null;

	const end = new Walker(lines, close, false);
	if (include) return { start, end: end.cursor, inclusive: true };

	// Exclude the brackets, and the indent before a closing bracket that starts its line
	const inner = new Walker(lines, start, false);
	incl(inner);
	let lineBreak = end.col === 0;
	decl(end);
	while (inIndent(end)) {
		lineBreak = true;
		if (decl(end) !== 0) break;
	}
	if (lineBreak) {
		incl(end);
		return { start: inner.cursor, end: end.cursor, inclusive: false };
	}
	const nonEmpty = inner.line < end.line || (inner.line === end.line && inner.col <= end.col);
	if (!nonEmpty) return { start: inner.cursor, end: inner.cursor, inclusive: false };
	return { start: inner.cursor, end: end.cursor, inclusive: true };
}

/**
 * Finds the range of a text object around the cursor.
 *
 * @param lines - Buffer lines.
 * @param cursor - Cursor position.
 * @param object - `i` or `a` followed by the object character, e.g. `iw` or `a"`.
 * @param count - Typed count, or null when none was typed.
 * @returns The range, empty when it has no `inclusive` end and `end` equals `start`, or null
 *   when there is no such object.
 */
export function selectTextObject(
	lines: readonly string[],
	cursor: Cursor,
	object: string,
	count: number | null,
): TextRange | null {
	const include = object.startsWith("a");
	const target = object.slice(1);
	const n = count ?? 1;
	if (target === "w" || target === "W") {
		const found = wordObject(lines, cursor, n, include, target === "W");
		return "stop" in found ? null : found;
	}
	if (QUOTES.has(target)) return quoteObject(lines, cursor, n, include, target);
	const pair = BLOCKS[target];
	return pair === undefined ? null : blockObject(lines, cursor, n, include, pair);
}

/**
 * Where Neovim leaves the cursor when a word object fails after searching partway, e.g. `d5iw`
 * with fewer words left. Quote and block objects never move it.
 *
 * @param lines - Buffer lines.
 * @param cursor - Cursor position.
 * @param object - `i` or `a` followed by the object character.
 * @param count - Typed count, or null when none was typed.
 * @returns The cursor where the search stopped, or null when the object does not move it.
 */
export function failedObjectStop(
	lines: readonly string[],
	cursor: Cursor,
	object: string,
	count: number | null,
): Cursor | null {
	const target = object.slice(1);
	if (target !== "w" && target !== "W") return null;
	const found = wordObject(lines, cursor, count ?? 1, object.startsWith("a"), target === "W");
	return "stop" in found ? found.stop : null;
}
