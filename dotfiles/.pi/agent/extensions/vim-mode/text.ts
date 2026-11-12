/**
 * Grapheme and character-class helpers. Columns are UTF-16 offsets, the unit of Pi's cursor.
 */

const segmenter = new Intl.Segmenter(undefined, { granularity: "grapheme" });

export type CharClass = "blank" | "punctuation" | "keyword";

const WIDE =
	/^(?![\uff61-\uffdc\uffe8-\uffee])[\p{Emoji_Presentation}\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}\u3000-\u303e\uff01-\uff60\uffe0-\uffe6]/u;

// A non-ASCII symbol followed by VS16 renders as emoji; ASCII keycap bases stay one cell
const EMOJI_VARIANT = /^[^\u0000-\u007f]\uFE0F/u;

/** Start offset of every grapheme in `line`. */
export function graphemeStarts(line: string): number[] {
	return Array.from(segmenter.segment(line), (part) => part.index);
}

/** Smallest grapheme boundary after `col`, or the line length when `col` is on the last one. */
export function nextBoundary(line: string, col: number): number {
	const part = segmenter.segment(line).containing(col);
	return part === undefined ? line.length : part.index + part.segment.length;
}

/** Largest grapheme boundary before `col`, or 0. */
export function prevBoundary(line: string, col: number): number {
	if (col <= 0) return 0;
	const part = segmenter.segment(line).containing(Math.min(col, line.length) - 1);
	return part?.index ?? 0;
}

/** Start of the last grapheme, or 0 for an empty line: the rightmost normal-mode column. */
export function lastGraphemeStart(line: string): number {
	return graphemeStarts(line).at(-1) ?? 0;
}

/** Start of the grapheme containing `col`, clamped to the last grapheme of the line. */
export function clampNormalCol(line: string, col: number): number {
	let clamped = 0;
	for (const start of graphemeStarts(line)) {
		if (start > col) break;
		clamped = start;
	}
	return clamped;
}

/**
 * Character class of a grapheme per `iskeyword=@,48-57,_,192-255`, judged by its first code point.
 * Code points above 255 count as keyword when they are letters, digits or marks.
 */
export function charClass(grapheme: string): CharClass {
	const code = grapheme.codePointAt(0);
	if (code === undefined || grapheme[0] === " " || grapheme[0] === "\t" || code === 0xa0) {
		return "blank";
	}
	if (code < 256) {
		const keyword =
			(code >= 48 && code <= 57) ||
			(code >= 65 && code <= 90) ||
			(code >= 97 && code <= 122) ||
			code === 95 ||
			code >= 192;
		return keyword ? "keyword" : "punctuation";
	}
	return /^[\p{L}\p{N}\p{M}]/u.test(grapheme) ? "keyword" : "punctuation";
}

/** Display cells of one grapheme: 2 for wide characters and emoji, else 1. */
export function displayWidth(grapheme: string): number {
	return WIDE.test(grapheme) || EMOJI_VARIANT.test(grapheme) ? 2 : 1;
}

/** Display cells before offset `col`. */
export function displayCol(line: string, col: number): number {
	let cells = 0;
	for (const { segment, index } of segmenter.segment(line)) {
		if (index >= col) break;
		cells += displayWidth(segment);
	}
	return cells;
}

/**
 * Start offset of the grapheme covering display cell `cells`, or of the last grapheme when the
 * line is shorter.
 */
export function colAtDisplay(line: string, cells: number): number {
	let offset = 0;
	let last = 0;
	for (const { segment, index } of segmenter.segment(line)) {
		last = index;
		offset += displayWidth(segment);
		if (offset > cells) return index;
	}
	return last;
}
