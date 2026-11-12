import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { CASES } from "./cases.ts";
import { parseBuffer, renderBuffer } from "./harness.ts";
import { runCase, selectRange } from "./oracle.ts";

const THUMB = "👍🏽";
const FAMILY = "👨‍👩‍👧";

describe("oracle self-tests", () => {
	it("converts Neovim byte columns to UTF-16 offsets", () => {
		// Hand-computed UTF-16 widths: é 1, the thumb 4, the family 8, 漢 1
		const line = `é${THUMB}a${FAMILY}漢字`;
		const steps = [
			{ from: 0, keys: "l", to: 1 },
			{ from: 0, keys: "ll", to: 5 },
			{ from: 0, keys: "lll", to: 6 },
			{ from: 0, keys: "llll", to: 14 },
			{ from: 0, keys: "lllll", to: 15 },
			{ from: 15, keys: "h", to: 14 },
			{ from: 14, keys: "h", to: 6 },
			{ from: 6, keys: "h", to: 5 },
			{ from: 5, keys: "h", to: 1 },
		];

		for (const { from, keys, to } of steps) {
			const result = runCase(line, { line: 0, col: from }, keys);
			assert.deepEqual(result.cursor, { line: 0, col: to }, `${keys} from ${from}`);
		}
	});

	it("runs insert, motion and delete keys", () => {
		const result = runCase("", { line: 0, col: 0 }, "iabc<Esc>hxiZ<Esc>");

		assert.deepEqual(result, { lines: ["aZc"], cursor: { line: 0, col: 1 }, mode: "normal" });
	});

	it("types a literal less-than sign for <lt>", () => {
		const result = runCase("", { line: 0, col: 0 }, "i<lt><Esc>");

		assert.deepEqual(result, { lines: ["<"], cursor: { line: 0, col: 0 }, mode: "normal" });
	});

	it("reports insert mode when the keys end inside it", () => {
		const result = runCase("foo bar", { line: 0, col: 0 }, "cw");

		assert.deepEqual(result, { lines: [" bar"], cursor: { line: 0, col: 0 }, mode: "insert" });
	});

	it("selects a text object and returns inclusive UTF-16 columns", () => {
		const range = selectRange("foo bar", { line: 0, col: 5 }, "iw");

		assert.deepEqual(range, { start: { line: 0, col: 4 }, end: { line: 0, col: 6 } });
	});

	it("fails when Neovim reports an unexpected mode", () => {
		assert.throws(() => runCase("a", { line: 0, col: 0 }, "v"), /unexpected Neovim mode/);
	});
});

describe("case matrix against Neovim", () => {
	it("agrees with every case that is not flagged pi", (t) => {
		const mismatches: string[] = [];
		const excluded: string[] = [];
		let checked = 0;

		for (const { name, buffer, keys, expect, mode = "normal", pi } of CASES) {
			if (pi !== undefined) {
				excluded.push(`${name} (${pi})`);
				continue;
			}
			checked++;
			const start = parseBuffer(buffer);
			const result = runCase(start.text, start.cursor, keys);
			const actual = `${renderBuffer(result.lines, result.cursor)} [${result.mode}]`;
			const wanted = `${expect} [${mode}]`;
			if (actual !== wanted) {
				mismatches.push(`${name}: keys ${keys} on ${buffer}: Neovim ${actual}, expected ${wanted}`);
			}
		}

		t.diagnostic(`checked ${checked} cases against Neovim`);
		t.diagnostic(`excluded ${excluded.length} pi cases: ${excluded.join("; ")}`);
		assert.deepEqual(mismatches, []);
	});
});
