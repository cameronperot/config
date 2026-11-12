/**
 * Cursor motions. A motion maps a buffer, a cursor and a count to a target and a kind, which
 * operators use to turn the target into a range. The word, find and `%` algorithms follow
 * Neovim's `fwd_word`, `end_word`, `bck_word`, `bckend_word`, `searchc` and `findmatchlimit`.
 */

import type { Cursor, FindSearch } from "./protocol.ts";
import {
	colAtDisplay,
	displayCol,
	graphemeStarts,
	lastGraphemeStart,
	nextBoundary,
	prevBoundary,
} from "./text.ts";

export type MotionKind = "exclusive" | "inclusive" | "linewise";

export interface MotionContext {
	readonly lines: readonly string[];
	readonly cursor: Cursor;
	/** Typed count, or null when none was typed. */
	readonly count: number | null;
	/** Wanted display column of vertical motions, `Infinity` after `$`. */
	readonly wantedCol: number;
	readonly lastFind: FindSearch | null;
}

export interface MotionResult {
	/** Where the motion ends. A failed motion keeps whatever progress it made. */
	readonly cursor: Cursor;
	readonly kind: MotionKind;
	readonly failed: boolean;
	/**
	 * What happens to the wanted column: `reset` drops it, `keep` retains it for the next
	 * vertical motion, `end` pins it to the line end.
	 */
	readonly want: "reset" | "keep" | "end";
	/** Set by `f F t T`: the search `;` and `,` now repeat. */
	readonly lastFind?: FindSearch;
}

/** Whether keys (count stripped) form a complete motion, the start of one, or neither. */
export type MotionStatus = "complete" | "prefix" | "none";

const SIMPLE_MOTIONS = new Set(["0", "^", "$", "w", "b", "e", "W", "B", "E", "G", ";", ",", "%"]);
const FIND_KEYS = new Set(["f", "F", "t", "T"]);

export function motionStatus(keys: string): MotionStatus {
	if (SIMPLE_MOTIONS.has(keys) || keys === "gg" || keys === "ge" || keys === "gE") {
		return "complete";
	}
	if (keys === "g") return "prefix";
	const [first = ""] = keys;
	if (FIND_KEYS.has(first)) return keys.length === 1 ? "prefix" : "complete";
	return "none";
}

const BLANK = 0;
const PUNCTUATION = 1;
const KEYWORD = 2;
const EMOJI = 3;

// Neovim's `classes` table of `utf_class`: runs of code points above 0xff that are not keywords
const UNICODE_CLASSES: readonly (readonly [number, number, number])[] = [
	[0x037e, 0x037e, PUNCTUATION],
	[0x0387, 0x0387, PUNCTUATION],
	[0x055a, 0x055f, PUNCTUATION],
	[0x0589, 0x0589, PUNCTUATION],
	[0x05be, 0x05be, PUNCTUATION],
	[0x05c0, 0x05c0, PUNCTUATION],
	[0x05c3, 0x05c3, PUNCTUATION],
	[0x05f3, 0x05f4, PUNCTUATION],
	[0x060c, 0x060c, PUNCTUATION],
	[0x061b, 0x061b, PUNCTUATION],
	[0x061f, 0x061f, PUNCTUATION],
	[0x066a, 0x066d, PUNCTUATION],
	[0x06d4, 0x06d4, PUNCTUATION],
	[0x0700, 0x070d, PUNCTUATION],
	[0x0964, 0x0965, PUNCTUATION],
	[0x0970, 0x0970, PUNCTUATION],
	[0x0df4, 0x0df4, PUNCTUATION],
	[0x0e4f, 0x0e4f, PUNCTUATION],
	[0x0e5a, 0x0e5b, PUNCTUATION],
	[0x0f04, 0x0f12, PUNCTUATION],
	[0x0f3a, 0x0f3d, PUNCTUATION],
	[0x0f85, 0x0f85, PUNCTUATION],
	[0x104a, 0x104f, PUNCTUATION],
	[0x10fb, 0x10fb, PUNCTUATION],
	[0x1361, 0x1368, PUNCTUATION],
	[0x166d, 0x166e, PUNCTUATION],
	[0x1680, 0x1680, BLANK],
	[0x169b, 0x169c, PUNCTUATION],
	[0x16eb, 0x16ed, PUNCTUATION],
	[0x1735, 0x1736, PUNCTUATION],
	[0x17d4, 0x17dc, PUNCTUATION],
	[0x1800, 0x180a, PUNCTUATION],
	[0x2000, 0x200b, BLANK],
	[0x200c, 0x2027, PUNCTUATION],
	[0x2028, 0x2029, BLANK],
	[0x202a, 0x202e, PUNCTUATION],
	[0x202f, 0x202f, BLANK],
	[0x2030, 0x205e, PUNCTUATION],
	[0x205f, 0x205f, BLANK],
	[0x2060, 0x206f, PUNCTUATION],
	[0x2070, 0x207f, 0x2070],
	[0x2080, 0x2094, 0x2080],
	[0x20a0, 0x27ff, PUNCTUATION],
	[0x2800, 0x28ff, 0x2800],
	[0x2900, 0x2998, PUNCTUATION],
	[0x29d8, 0x29db, PUNCTUATION],
	[0x29fc, 0x29fd, PUNCTUATION],
	[0x2e00, 0x2e7f, PUNCTUATION],
	[0x3000, 0x3000, BLANK],
	[0x3001, 0x3020, PUNCTUATION],
	[0x3030, 0x3030, PUNCTUATION],
	[0x303d, 0x303d, PUNCTUATION],
	[0x3040, 0x309f, 0x3040],
	[0x30a0, 0x30ff, 0x30a0],
	[0x3300, 0x9fff, 0x4e00],
	[0xac00, 0xd7a3, 0xac00],
	[0xf900, 0xfaff, 0x4e00],
	[0xfd3e, 0xfd3f, PUNCTUATION],
	[0xfe30, 0xfe6b, PUNCTUATION],
	[0xff00, 0xff0f, PUNCTUATION],
	[0xff1a, 0xff20, PUNCTUATION],
	[0xff3b, 0xff40, PUNCTUATION],
	[0xff5b, 0xff65, PUNCTUATION],
	[0x1d000, 0x1d24f, PUNCTUATION],
	[0x1d400, 0x1d7ff, PUNCTUATION],
	[0x1f000, 0x1f2ff, PUNCTUATION],
	[0x1f300, 0x1f9ff, PUNCTUATION],
	[0x20000, 0x2a6df, 0x4e00],
	[0x2a700, 0x2b73f, 0x4e00],
	[0x2b740, 0x2b81f, 0x4e00],
	[0x2f800, 0x2fa1f, 0x4e00],
];

const EMOJI_PATTERN = /^\p{Emoji}/u;

/**
 * Word class of a grapheme, judged by its first code point as Neovim's `utf_class` does with
 * `iskeyword=@,48-57,_,192-255`: 0 blank, 1 punctuation, 2 keyword, 3 emoji, and one more class
 * for each script that Neovim keeps apart (CJK ideographs, Hiragana, Katakana, Hangul).
 *
 * @param grapheme - One grapheme; an empty string is the end of a line and counts as blank.
 * @param big - Treat every non-blank class as one, as the capital word motions do.
 */
export function wordClass(grapheme: string, big = false): number {
	const code = grapheme.codePointAt(0);
	if (code === undefined || code === 0x20 || code === 0x09 || code === 0xa0) return BLANK;
	let wordClass = PUNCTUATION;
	if (code < 0x100) {
		const keyword =
			(code >= 0x30 && code <= 0x39) ||
			(code >= 0x41 && code <= 0x5a) ||
			(code >= 0x61 && code <= 0x7a) ||
			code === 0x5f ||
			code === 0xb5 ||
			code >= 0xc0;
		wordClass = keyword ? KEYWORD : PUNCTUATION;
	} else if (EMOJI_PATTERN.test(grapheme)) {
		wordClass = EMOJI;
	} else {
		const entry = UNICODE_CLASSES.find(([low, high]) => code >= low && code <= high);
		wordClass = entry === undefined ? KEYWORD : entry[2];
	}
	return big && wordClass !== BLANK ? PUNCTUATION : wordClass;
}

/**
 * A cursor that may rest on the end of a line, like Vim's `inc()` and `dec()`. Both return 0
 * after a step within a line, 1 after crossing to another line, 2 after stepping onto the end
 * of a line, and -1 at the buffer edge.
 */
export class Walker {
	line: number;
	col: number;
	readonly lines: readonly string[];
	readonly big: boolean;

	constructor(lines: readonly string[], cursor: Cursor, big: boolean) {
		this.lines = lines;
		this.line = cursor.line;
		this.col = cursor.col;
		this.big = big;
	}

	get text(): string {
		return this.lines[this.line] ?? "";
	}

	get atLineEnd(): boolean {
		return this.col >= this.text.length;
	}

	get onEmptyLine(): boolean {
		return this.col === 0 && this.text === "";
	}

	get onLastLine(): boolean {
		return this.line === this.lines.length - 1;
	}

	cls(): number {
		const text = this.text;
		return wordClass(text.slice(this.col, nextBoundary(text, this.col)), this.big);
	}

	inc(): number {
		const text = this.text;
		if (this.col < text.length) {
			this.col = nextBoundary(text, this.col);
			return this.col < text.length ? 0 : 2;
		}
		if (this.line < this.lines.length - 1) {
			this.line++;
			this.col = 0;
			return 1;
		}
		return -1;
	}

	dec(): number {
		if (this.col > 0) {
			this.col = prevBoundary(this.text, this.col);
			return 0;
		}
		if (this.line > 0) {
			this.line--;
			this.col = this.text.length;
			return 1;
		}
		return -1;
	}

	/** Steps while the class under the cursor equals `wanted`; true when it hit the buffer edge. */
	skip(wanted: number, forward: boolean): boolean {
		while (this.cls() === wanted) {
			if ((forward ? this.inc() : this.dec()) === -1) return true;
		}
		return false;
	}

	get cursor(): Cursor {
		return { line: this.line, col: this.col };
	}
}

/**
 * Moves to the start of the next word `count` times. With `eol`, the last step stops at the end
 * of a line instead of crossing it, which operators and text objects need.
 */
export function forwardWord(walker: Walker, count: number, eol = false): boolean {
	for (let remaining = count; remaining > 0; remaining--) {
		const last = remaining === 1;
		const startClass = walker.cls();
		const lastLine = walker.onLastLine;
		const moved = walker.inc();
		if (moved === -1 || (moved >= 1 && lastLine)) return false;
		if (moved >= 1 && eol && last) return true;

		if (startClass !== BLANK) {
			while (walker.cls() === startClass) {
				const step = walker.inc();
				if (step === -1 || (step >= 1 && eol && last)) return true;
			}
		}
		while (walker.cls() === BLANK) {
			if (walker.onEmptyLine) break;
			const step = walker.inc();
			if (step === -1 || (step >= 1 && eol && last)) return true;
		}
	}
	return true;
}

/**
 * Moves to the end of the word `count` times. With `stop`, a cursor already on a word end stays
 * there; with `empty`, an empty line ends the search.
 */
export function endWord(walker: Walker, count: number, stop = false, empty = false): boolean {
	let stopHere = stop;
	for (let remaining = count; remaining > 0; remaining--) {
		const startClass = walker.cls();
		if (walker.inc() === -1) return false;

		let finished = false;
		if (walker.cls() === startClass && startClass !== BLANK) {
			if (walker.skip(startClass, true)) return false;
		} else if (!stopHere || startClass === BLANK) {
			while (walker.cls() === BLANK) {
				if (empty && walker.onEmptyLine) {
					finished = true;
					break;
				}
				if (walker.inc() === -1) return false;
			}
			if (!finished && walker.skip(walker.cls(), true)) return false;
		}
		if (!finished) walker.dec();
		stopHere = false;
	}
	return true;
}

function backwardWord(walker: Walker, count: number): boolean {
	for (let remaining = count; remaining > 0; remaining--) {
		if (walker.dec() === -1) return false;

		let onWord = true;
		while (walker.cls() === BLANK) {
			if (walker.onEmptyLine) {
				onWord = false;
				break;
			}
			if (walker.dec() === -1) return true;
		}
		if (onWord) {
			if (walker.skip(walker.cls(), false)) return true;
			walker.inc();
		}
	}
	return true;
}

function backwardWordEnd(walker: Walker, count: number): boolean {
	for (let remaining = count; remaining > 0; remaining--) {
		const startClass = walker.cls();
		if (walker.dec() === -1) return false;

		if (startClass !== BLANK && walker.skip(startClass, false)) return true;
		while (walker.cls() === BLANK) {
			if (walker.onEmptyLine) break;
			if (walker.dec() === -1) return true;
		}
	}
	return true;
}

function wordMotion(keys: string, context: MotionContext): MotionResult {
	const big = keys === "W" || keys === "B" || keys === "E" || keys === "gE";
	const walker = new Walker(context.lines, context.cursor, big);
	const count = context.count ?? 1;
	let ok: boolean;
	let kind: MotionKind = "exclusive";
	if (keys === "w" || keys === "W") {
		ok = forwardWord(walker, count);
	} else if (keys === "e" || keys === "E") {
		ok = endWord(walker, count);
		kind = "inclusive";
	} else if (keys === "b" || keys === "B") {
		ok = backwardWord(walker, count);
	} else {
		ok = backwardWordEnd(walker, count);
		kind = "inclusive";
	}

	const moved = { ...walker.cursor };
	const { line, col } = context.cursor;
	const forward = moved.line > line || (moved.line === line && moved.col > col);
	if (forward && moved.col > 0 && walker.atLineEnd) {
		// A forward motion that ends past the last character settles on it and includes it
		moved.col = lastGraphemeStart(walker.text);
		kind = "inclusive";
	}
	return { cursor: moved, kind, failed: !ok, want: "reset" };
}

function firstNonBlank(text: string): number {
	let col = 0;
	while (col < text.length - 1 && (text[col] === " " || text[col] === "\t")) col++;
	return col;
}

function lineMotion(keys: string, context: MotionContext): MotionResult {
	const { lines, cursor, count } = context;
	const lastLine = lines.length - 1;
	const text = lines[cursor.line] ?? "";
	if (keys === "0") {
		return {
			cursor: { line: cursor.line, col: 0 },
			kind: "exclusive",
			failed: false,
			want: "reset",
		};
	}
	if (keys === "^") {
		return {
			cursor: { line: cursor.line, col: firstNonBlank(text) },
			kind: "exclusive",
			failed: false,
			want: "reset",
		};
	}

	// `$` fails, without moving, only when a count asks for lines below the last one
	const down = (count ?? 1) - 1;
	if (down > 0 && cursor.line === lastLine) {
		return { cursor, kind: "inclusive", failed: true, want: "end" };
	}
	const line = Math.min(cursor.line + down, lastLine);
	const col = lastGraphemeStart(lines[line] ?? "");
	return { cursor: { line, col }, kind: "inclusive", failed: false, want: "end" };
}

/** Jump to a line, keeping the wanted column as `nostartofline` does. */
function gotoLine(line: number, context: MotionContext): MotionResult {
	const clamped = Math.min(Math.max(line, 0), context.lines.length - 1);
	const col = colAtDisplay(context.lines[clamped] ?? "", context.wantedCol);
	return { cursor: { line: clamped, col }, kind: "linewise", failed: false, want: "keep" };
}

function findMotion(keys: string, context: MotionContext): MotionResult {
	const repeat = keys === ";" || keys === ",";
	let search = context.lastFind;
	if (!repeat) search = { key: keys[0] as FindSearch["key"], char: keys.slice(1) };
	if (search === null) {
		return { cursor: context.cursor, kind: "inclusive", failed: true, want: "keep" };
	}

	const reversed = keys === ",";
	const flip = (key: FindSearch["key"]): FindSearch["key"] =>
		key === "f" ? "F" : key === "F" ? "f" : key === "t" ? "T" : "t";
	const effective = reversed ? flip(search.key) : search.key;
	const forward = effective === "f" || effective === "t";
	const till = effective === "t" || effective === "T";
	const kind: MotionKind = forward ? "inclusive" : "exclusive";
	const remembered = repeat ? undefined : search;

	const { line, col } = context.cursor;
	const text = context.lines[line] ?? "";
	const starts = graphemeStarts(text);
	let index = starts.indexOf(col);
	// `;` after `t` must move, even when the cursor is right in front of the target
	let stop = !(repeat && (context.count ?? 1) === 1 && till);
	for (let remaining = context.count ?? 1; remaining > 0; remaining--) {
		for (;;) {
			index += forward ? 1 : -1;
			const start = starts[index];
			if (start === undefined) {
				const cursor = context.cursor;
				return { cursor, kind, failed: true, want: "keep", lastFind: remembered };
			}
			const grapheme = text.slice(start, starts[index + 1]);
			if (grapheme === search.char && stop) break;
			stop = true;
		}
	}
	if (till) index += forward ? -1 : 1;
	return {
		cursor: { line, col: starts[index] ?? col },
		kind,
		failed: false,
		want: "reset",
		lastFind: remembered,
	};
}

const OPENERS = "({[";
const CLOSERS = ")}]";

function isBracket(char: string | undefined): boolean {
	return char !== undefined && (OPENERS.includes(char) || CLOSERS.includes(char));
}

export interface ScanOptions {
	/** Ignore brackets after an odd number of backslashes. */
	readonly escapes: boolean;
	/** Ignore brackets inside double quotes and `'x'` literals, as Neovim's smart matching does. */
	readonly quotes: boolean;
}

/**
 * Scans from `from`, not including it, for the `wanted` bracket, skipping over `nested` ones and
 * the `wanted` ones that close them. The quote handling follows `findmatchlimit`: quotes only
 * count on lines with an even number of them, or when a trailing backslash continues a string.
 */
export function scanBracket(
	lines: readonly string[],
	from: Cursor,
	nested: string,
	wanted: string,
	backwards: boolean,
	options: ScanOptions,
): Cursor | null {
	let { line, col } = from;
	let text = lines[line] ?? "";
	let depth = 0;
	// -1: the quotes of the line are not counted yet; 1: the line has an even number of quotes
	let quotes = options.quotes ? -1 : 0;
	let startInQuotes: boolean | "maybe" = "maybe";
	let inQuote = false;
	for (;;) {
		if (backwards) {
			if (col === 0) {
				if (line === 0) return null;
				line--;
				text = lines[line] ?? "";
				col = text.length;
				if (options.quotes) quotes = -1;
			} else {
				col--;
			}
		} else if (col >= text.length) {
			if (line === lines.length - 1) return null;
			line++;
			text = lines[line] ?? "";
			col = 0;
			if (options.quotes) quotes = -1;
		} else {
			col++;
		}

		if (quotes === -1) {
			let atStart = quotes;
			for (let i = 0; i < text.length; i++) {
				if (i === col + (backwards ? 1 : 0)) atStart = quotes & 1;
				const literal = text[i - 1] === "'" && text[i + 1] === "'";
				if (text[i] === '"' && (i === 0 || !literal)) quotes++;
				if (text[i] === "\\" && i + 1 < text.length) i++;
			}
			quotes &= 1;
			if (quotes === 0) {
				inQuote = false;
				if (text.endsWith("\\")) {
					quotes = 1;
					if (startInQuotes === "maybe") {
						inQuote = true;
						startInQuotes = true;
					} else if (backwards) {
						inQuote = true;
					}
				}
				if ((lines[line - 1] ?? "").endsWith("\\")) {
					quotes = 1;
					if (startInQuotes === "maybe") {
						inQuote = atStart !== 0;
						if (inQuote) startInQuotes = true;
					} else if (!backwards) {
						inQuote = true;
					}
				}
			}
		}
		if (startInQuotes === "maybe") startInQuotes = false;

		const char = text[col] ?? "";
		if (char === "") {
			if (col === 0 || text[col - 1] !== "\\") {
				inQuote = false;
				startInQuotes = false;
			}
			continue;
		}
		if (char === '"' && options.quotes) {
			if (quotes !== 0 && countBackslashes(text, col) % 2 === 0) {
				inQuote = !inQuote;
				startInQuotes = false;
			}
			continue;
		}
		if (char === "'" && options.quotes) {
			const skip = literalSkip(text, col, backwards);
			if (skip !== 0) {
				col += skip;
				continue;
			}
		}
		if (char !== nested && char !== wanted) continue;
		if (inQuote && startInQuotes !== true) continue;
		if (options.escapes && countBackslashes(text, col) % 2 === 1) continue;
		if (char === nested) {
			depth++;
		} else {
			if (depth === 0) return { line, col };
			depth--;
		}
	}
}

/** Offset to jump over a `'x'` or `'\x'` literal that starts or ends at `col`, or 0. */
function literalSkip(text: string, col: number, backwards: boolean): number {
	if (backwards) {
		if (col > 1) {
			if (text[col - 2] === "'") return -2;
			if (text[col - 2] === "\\" && col > 2 && text[col - 3] === "'") return -3;
		}
	} else if (col + 1 < text.length) {
		if (text[col + 1] === "\\" && col + 2 < text.length && text[col + 3] === "'") return 3;
		if (text[col + 2] === "'") return 2;
	}
	return 0;
}

function countBackslashes(text: string, col: number): number {
	let count = 0;
	for (let i = col - 1; i >= 0 && text[i] === "\\"; i--) count++;
	return count;
}

/**
 * Finds the bracket that matches the first one at or after the cursor. Neovim counts every
 * bracket, whether it sits in quotes, in a character literal or after a backslash.
 */
function findMatchingBracket(lines: readonly string[], cursor: Cursor): Cursor | null {
	const text = lines[cursor.line] ?? "";
	let col = cursor.col;
	while (col < text.length && !isBracket(text[col])) col++;
	const initial = text[col] ?? "";
	if (initial === "") return null;

	const backwards = CLOSERS.includes(initial);
	const target = backwards
		? OPENERS[CLOSERS.indexOf(initial)]
		: CLOSERS[OPENERS.indexOf(initial)];
	return scanBracket(lines, { line: cursor.line, col }, initial, target ?? "", backwards, {
		escapes: false,
		quotes: false,
	});
}

function percentMotion(context: MotionContext): MotionResult {
	const { lines, cursor, count } = context;
	if (count !== null) {
		if (count > 100) return { cursor, kind: "linewise", failed: true, want: "reset" };
		// Unlike `G`, `N%` aims for the cursor's own column; only a pinned line end survives
		// as it was stored, and the cursor's column becomes the wanted one
		const line = Math.ceil((lines.length * count) / 100) - 1;
		const pinned = context.wantedCol === Infinity;
		const wantedCol = pinned ? Infinity : displayCol(lines[cursor.line] ?? "", cursor.col);
		const result = gotoLine(line, { ...context, wantedCol });
		return pinned ? { ...result, want: "end" } : result;
	}
	const target = findMatchingBracket(lines, cursor);
	if (target === null) return { cursor, kind: "inclusive", failed: true, want: "reset" };
	return { cursor: target, kind: "inclusive", failed: false, want: "reset" };
}

/**
 * Runs a complete motion.
 *
 * @param keys - The motion's keys without the count, e.g. `w`, `gg` or `fx`.
 * @param context - The buffer, cursor, count and the state the motion reads.
 */
export function runMotion(keys: string, context: MotionContext): MotionResult {
	switch (keys) {
		case "0":
		case "^":
		case "$":
			return lineMotion(keys, context);
		case "w":
		case "W":
		case "b":
		case "B":
		case "e":
		case "E":
		case "ge":
		case "gE":
			return wordMotion(keys, context);
		case "gg":
			return gotoLine((context.count ?? 1) - 1, context);
		case "G":
			return gotoLine((context.count ?? context.lines.length) - 1, context);
		case ";":
		case ",":
			return findMotion(keys, context);
		case "%":
			return percentMotion(context);
		default:
			return findMotion(keys, context);
	}
}
