import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
	charClass,
	clampNormalCol,
	colAtDisplay,
	displayCol,
	displayWidth,
	graphemeStarts,
	lastGraphemeStart,
	nextBoundary,
	prevBoundary,
} from "../text.ts";

const THUMB = "👍🏽"; // 4 UTF-16 units
const FAMILY = "👨‍👩‍👧"; // 8 UTF-16 units
const COMBINED = "é"; // 2 UTF-16 units

describe("graphemeStarts", () => {
	it("is empty for an empty line", () => {
		assert.deepEqual(graphemeStarts(""), []);
	});

	it("treats a skin-tone emoji as one grapheme", () => {
		assert.deepEqual(graphemeStarts(`a${THUMB}b`), [0, 1, 5]);
	});

	it("treats a ZWJ sequence as one grapheme", () => {
		assert.deepEqual(graphemeStarts(`a${FAMILY}b`), [0, 1, 9]);
	});

	it("keeps a combining mark with its base", () => {
		assert.deepEqual(graphemeStarts(`${COMBINED}x`), [0, 2]);
	});

	it("splits CJK into one grapheme per character", () => {
		assert.deepEqual(graphemeStarts("漢字"), [0, 1]);
	});
});

describe("boundaries", () => {
	const line = `a${THUMB}b`;

	it("steps forward over a whole grapheme", () => {
		assert.equal(nextBoundary(line, 0), 1);
		assert.equal(nextBoundary(line, 1), 5);
		assert.equal(nextBoundary(line, 5), 6);
		assert.equal(nextBoundary(line, 6), 6);
	});

	it("steps backward over a whole grapheme", () => {
		assert.equal(prevBoundary(line, 6), 5);
		assert.equal(prevBoundary(line, 5), 1);
		assert.equal(prevBoundary(line, 1), 0);
		assert.equal(prevBoundary(line, 0), 0);
	});

	it("steps over a ZWJ sequence, a combining mark and CJK", () => {
		assert.equal(nextBoundary(FAMILY, 0), 8);
		assert.equal(prevBoundary(FAMILY, 8), 0);
		assert.equal(nextBoundary(COMBINED, 0), 2);
		assert.equal(nextBoundary("漢字", 0), 1);
		assert.equal(prevBoundary("漢字", 2), 1);
	});

	it("agrees with the grapheme start list at every column", () => {
		const text = `ae\u0301${THUMB}${FAMILY}漢b`;
		const starts = graphemeStarts(text);
		for (let col = 0; col <= text.length + 2; col++) {
			const after = starts.find((start) => start > col) ?? text.length;
			const before = starts.findLast((start) => start < col) ?? 0;
			assert.equal(nextBoundary(text, col), after, `nextBoundary at ${col}`);
			assert.equal(prevBoundary(text, col), before, `prevBoundary at ${col}`);
		}
	});

	it("walks a long line in bounded time", () => {
		const text = "a".repeat(10_000);
		const started = performance.now();
		let col = 0;
		while (col < text.length) col = nextBoundary(text, col);
		while (col > 0) col = prevBoundary(text, col);
		assert.ok(performance.now() - started < 1000, "boundary walk over 10,000 characters");
	});

	it("finds the last grapheme start", () => {
		assert.equal(lastGraphemeStart(""), 0);
		assert.equal(lastGraphemeStart(`a${THUMB}`), 1);
		assert.equal(lastGraphemeStart(FAMILY), 0);
	});

	it("clamps a column onto the grapheme containing it", () => {
		assert.equal(clampNormalCol(`a${THUMB}b`, 3), 1);
		assert.equal(clampNormalCol(`a${THUMB}b`, 99), 5);
		assert.equal(clampNormalCol("", 4), 0);
	});
});

describe("charClass", () => {
	it("classifies per iskeyword=@,48-57,_,192-255", () => {
		assert.equal(charClass("a"), "keyword");
		assert.equal(charClass("Z"), "keyword");
		assert.equal(charClass("7"), "keyword");
		assert.equal(charClass("_"), "keyword");
		assert.equal(charClass("é"), "keyword");
		assert.equal(charClass("-"), "punctuation");
		assert.equal(charClass("."), "punctuation");
		assert.equal(charClass(" "), "blank");
		assert.equal(charClass("\t"), "blank");
	});

	it("classifies characters above 255 by their Unicode category", () => {
		assert.equal(charClass("漢"), "keyword");
		assert.equal(charClass("，"), "punctuation");
		assert.equal(charClass(THUMB), "punctuation");
	});
});

describe("display width", () => {
	it("matches Neovim's strdisplaywidth", () => {
		assert.equal(displayWidth("a"), 1);
		assert.equal(displayWidth("é"), 1);
		assert.equal(displayWidth(COMBINED), 1);
		assert.equal(displayWidth("漢"), 2);
		assert.equal(displayWidth("Ａ"), 2);
		assert.equal(displayWidth("ｱ"), 1);
		assert.equal(displayWidth(THUMB), 2);
		assert.equal(displayWidth(FAMILY), 2);
	});

	it("widens a symbol that an emoji variation selector makes emoji", () => {
		assert.equal(displayWidth("©\uFE0F"), 2);
		assert.equal(displayWidth("☀\uFE0F"), 2);
		assert.equal(displayWidth("❤\uFE0F"), 2);
		assert.equal(displayWidth("©"), 1);
		assert.equal(displayWidth("1\uFE0F\u20E3"), 1);
	});

	it("converts between offsets and cells", () => {
		const line = `漢a${THUMB}b`;
		assert.equal(displayCol(line, 0), 0);
		assert.equal(displayCol(line, 1), 2);
		assert.equal(displayCol(line, 2), 3);
		assert.equal(displayCol(line, 6), 5);
		assert.equal(colAtDisplay(line, 0), 0);
		assert.equal(colAtDisplay(line, 1), 0);
		assert.equal(colAtDisplay(line, 2), 1);
		assert.equal(colAtDisplay(line, 4), 2);
		assert.equal(colAtDisplay(line, 99), 6);
		assert.equal(colAtDisplay("", 3), 0);
	});
});
