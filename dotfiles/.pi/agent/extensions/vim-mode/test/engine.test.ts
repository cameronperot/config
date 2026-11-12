import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { initialState, step } from "../engine.ts";
import type { Cursor, Effect, EngineState, Snapshot } from "../protocol.ts";

const THUMB = "👍🏽";

interface Run {
	snapshot: Snapshot;
	state: EngineState;
	effects: Effect[];
	lastEffects: readonly Effect[];
}

function tokenize(keys: string): string[] {
	return keys.match(/<Esc>|<CR>|[\s\S]/gu) ?? [];
}

/** Feeds `keys` through the engine, applying edit and cursor effects to the snapshot. */
function run(
	keys: string,
	lines: readonly string[],
	cursor: Cursor,
	state: EngineState = { ...initialState, mode: "normal" },
): Run {
	let result: Run = { snapshot: { lines, cursor }, state, effects: [], lastEffects: [] };
	for (const key of tokenize(keys)) {
		const out = step(result.state, result.snapshot, key);
		let snapshot = result.snapshot;
		for (const effect of out.effects) {
			if (effect.type === "edit") snapshot = effect.snapshot;
			if (effect.type === "cursor") snapshot = { ...snapshot, cursor: effect.cursor };
		}
		result = {
			snapshot,
			state: out.state,
			effects: [...result.effects, ...out.effects],
			lastEffects: out.effects,
		};
	}
	return result;
}

const at = (line: number, col: number): Cursor => ({ line, col });

describe("h and l", () => {
	it("h moves left, l moves right", () => {
		assert.deepEqual(run("h", ["abc"], at(0, 2)).snapshot.cursor, at(0, 1));
		assert.deepEqual(run("l", ["abc"], at(0, 0)).snapshot.cursor, at(0, 1));
	});

	it("honour a count and stop at the line edges", () => {
		assert.deepEqual(run("2h", ["abcd"], at(0, 3)).snapshot.cursor, at(0, 1));
		assert.deepEqual(run("9h", ["abcd"], at(0, 3)).snapshot.cursor, at(0, 0));
		assert.deepEqual(run("2l", ["abcd"], at(0, 0)).snapshot.cursor, at(0, 2));
		assert.deepEqual(run("9l", ["abcd"], at(0, 0)).snapshot.cursor, at(0, 3));
		assert.deepEqual(run("10l", ["abcdefghijkl"], at(0, 0)).snapshot.cursor, at(0, 10));
	});

	it("emit no effect at an edge or on an empty line", () => {
		assert.deepEqual(run("h", ["abc"], at(0, 0)).effects, []);
		assert.deepEqual(run("l", ["abc"], at(0, 2)).effects, []);
		assert.deepEqual(run("l", [""], at(0, 0)).effects, []);
	});

	it("never leave the line", () => {
		assert.deepEqual(run("9l", ["ab", "cd"], at(0, 0)).snapshot.cursor, at(0, 1));
		assert.deepEqual(run("9h", ["ab", "cd"], at(1, 1)).snapshot.cursor, at(1, 0));
	});

	it("step over whole graphemes", () => {
		const lines = [`a${THUMB}b`];
		assert.deepEqual(run("l", lines, at(0, 0)).snapshot.cursor, at(0, 1));
		assert.deepEqual(run("ll", lines, at(0, 0)).snapshot.cursor, at(0, 5));
		assert.deepEqual(run("h", lines, at(0, 5)).snapshot.cursor, at(0, 1));
		assert.deepEqual(run("l", ["漢字"], at(0, 0)).snapshot.cursor, at(0, 1));
		assert.deepEqual(run("l", ["👨‍👩‍👧x"], at(0, 0)).snapshot.cursor, at(0, 8));
	});
});

describe("x", () => {
	it("deletes the character under the cursor and keeps the column", () => {
		const out = run("x", ["abc"], at(0, 1));
		assert.deepEqual(out.snapshot, { lines: ["ac"], cursor: at(0, 1) });
	});

	it("clamps the cursor after deleting the last character", () => {
		const out = run("x", ["abc"], at(0, 2));
		assert.deepEqual(out.snapshot, { lines: ["ab"], cursor: at(0, 1) });
	});

	it("honours a count and stops at the line end", () => {
		assert.deepEqual(run("2x", ["abcd"], at(0, 1)).snapshot, {
			lines: ["ad"],
			cursor: at(0, 1),
		});
		assert.deepEqual(run("9x", ["abcd"], at(0, 1)).snapshot, {
			lines: ["a"],
			cursor: at(0, 0),
		});
	});

	it("leaves other lines alone and changes nothing on an empty line", () => {
		assert.deepEqual(run("x", ["ab", "cd"], at(1, 0)).snapshot.lines, ["ab", "d"]);
		assert.deepEqual(run("x", ["ab", "", "cd"], at(1, 0)).effects, []);
	});

	it("deletes a whole grapheme", () => {
		assert.deepEqual(run("x", [`a${THUMB}b`], at(0, 1)).snapshot, {
			lines: ["ab"],
			cursor: at(0, 1),
		});
		assert.deepEqual(run("x", ["漢字"], at(0, 0)).snapshot.lines, ["字"]);
	});

	it("emits a single edit effect", () => {
		const out = run("x", ["abc"], at(0, 1));
		assert.equal(out.effects.length, 1);
		assert.equal(out.effects[0]?.type, "edit");
	});
});

describe("i and a", () => {
	it("i enters insert mode without moving", () => {
		const out = run("i", ["abc"], at(0, 1));
		assert.deepEqual(out.effects, [{ type: "mode", mode: "insert" }]);
		assert.equal(out.state.mode, "insert");
	});

	it("a enters insert mode one grapheme to the right", () => {
		const out = run("a", ["abc"], at(0, 1));
		assert.equal(out.state.mode, "insert");
		assert.deepEqual(out.snapshot.cursor, at(0, 2));
	});

	it("a on the last grapheme moves to the line end", () => {
		assert.deepEqual(run("a", ["abc"], at(0, 2)).snapshot.cursor, at(0, 3));
		assert.deepEqual(run("a", [`a${THUMB}`], at(0, 1)).snapshot.cursor, at(0, 5));
	});

	it("a on an empty line stays at column 0", () => {
		const out = run("a", [""], at(0, 0));
		assert.equal(out.state.mode, "insert");
		assert.deepEqual(out.snapshot.cursor, at(0, 0));
	});

	it("take a count that the Escape turns into a replay request", () => {
		for (const keys of ["3i", "3a"]) {
			const entered = run(keys, ["abc"], at(0, 1));
			assert.equal(entered.state.mode, "insert");
			assert.equal(entered.state.insertCount, 3);

			const out = step(entered.state, entered.snapshot, "<Esc>");

			assert.deepEqual(out.effects, [{ type: "repeat-insert", count: 2 }]);
			assert.equal(out.state.mode, "insert");
			assert.equal(out.state.insertCount, null);
		}
	});
});

describe("<Esc> from insert mode", () => {
	const insert: EngineState = { ...initialState, mode: "insert" };

	it("enters normal mode with the cursor one left", () => {
		const out = run("<Esc>", ["abc"], at(0, 2), insert);
		assert.equal(out.state.mode, "normal");
		assert.deepEqual(out.snapshot.cursor, at(0, 1));
		assert.deepEqual(out.effects[0], { type: "mode", mode: "normal" });
	});

	it("clamps onto the last grapheme from the line end", () => {
		assert.deepEqual(run("<Esc>", ["abc"], at(0, 3), insert).snapshot.cursor, at(0, 2));
		assert.deepEqual(run("<Esc>", [`a${THUMB}`], at(0, 5), insert).snapshot.cursor, at(0, 1));
	});

	it("stays at column 0 at the line start and on an empty line", () => {
		for (const [line, col] of [["abc", 0], ["", 0]] as const) {
			const out = run("<Esc>", [line], at(0, col), insert);
			assert.equal(out.state.mode, "normal");
			assert.deepEqual(out.snapshot.cursor, at(0, 0));
			assert.deepEqual(out.effects, [{ type: "mode", mode: "normal" }]);
		}
	});

	it("is the only key the engine reacts to in insert mode", () => {
		const out = step(insert, { lines: ["abc"], cursor: at(0, 1) }, "x");
		assert.deepEqual(out, { state: insert, effects: [] });
	});

	it("returns to the original grapheme after a then nothing typed", () => {
		const out = run("a<Esc>", ["abc"], at(0, 0));
		assert.equal(out.state.mode, "normal");
		assert.deepEqual(out.snapshot.cursor, at(0, 0));
	});
});

describe("j and k", () => {
	const five = ["a", "b", "c", "d", "e"];

	it("uncounted j and k are Pi's down and up", () => {
		assert.deepEqual(run("j", five, at(0, 0)).effects, [{ type: "pi", action: "down" }]);
		assert.deepEqual(run("k", five, at(2, 0)).effects, [{ type: "pi", action: "up" }]);
	});

	it("counted j and k move by logical lines", () => {
		assert.deepEqual(run("3j", five, at(0, 0)).snapshot.cursor, at(3, 0));
		assert.deepEqual(run("2k", five, at(4, 0)).snapshot.cursor, at(2, 0));
	});

	it("cap at the buffer edges", () => {
		assert.deepEqual(run("3j", five, at(3, 0)).snapshot.cursor, at(4, 0));
		assert.deepEqual(run("3k", five, at(1, 0)).snapshot.cursor, at(0, 0));
		assert.deepEqual(run("9j", five, at(0, 0)).snapshot.cursor, at(4, 0));
	});

	it("do nothing when already at the edge", () => {
		assert.deepEqual(run("3j", five, at(4, 0)).effects, []);
		assert.deepEqual(run("3k", five, at(0, 0)).effects, []);
	});

	it("never emit a Pi action, so they never browse history", () => {
		assert.ok(run("3j", five, at(4, 0)).effects.every((e) => e.type !== "pi"));
		assert.ok(run("3k", five, at(0, 0)).effects.every((e) => e.type !== "pi"));
	});

	it("keep the preferred column across a short line", () => {
		const lines = ["abcdef", "ab", "abcdef"];
		const first = run("1j", lines, at(0, 4));
		assert.deepEqual(first.snapshot.cursor, at(1, 1));
		const second = run("1j", lines, first.snapshot.cursor, first.state);
		assert.deepEqual(second.snapshot.cursor, at(2, 4));
	});

	it("drop the preferred column when the cursor was moved elsewhere", () => {
		const lines = ["abcdef", "ab", "abcdef"];
		const first = run("1j", lines, at(0, 4));
		const second = run("1j", lines, at(1, 0), first.state);
		assert.deepEqual(second.snapshot.cursor, at(2, 0));
	});

	it("measure the preferred column in display cells", () => {
		assert.deepEqual(run("1k", ["漢字x", "abcd"], at(1, 2)).snapshot.cursor, at(0, 1));
		assert.deepEqual(run("1j", ["abcd", "漢字x"], at(0, 3)).snapshot.cursor, at(1, 1));
	});

	it("land on a grapheme boundary", () => {
		assert.deepEqual(run("1j", ["abcd", `a${THUMB}b`], at(0, 2)).snapshot.cursor, at(1, 1));
	});
});

describe("counts", () => {
	it("accumulate digits into the pending keys", () => {
		assert.equal(run("3", ["abc"], at(0, 0)).state.pending, "3");
		assert.equal(run("12", ["abc"], at(0, 0)).state.pending, "12");
		assert.equal(run("10", ["abc"], at(0, 0)).state.pending, "10");
	});

	it("clear the pending keys once the command runs", () => {
		assert.equal(run("3l", ["abcdef"], at(0, 0)).state.pending, "");
	});

	it("do not overflow on a huge count", () => {
		const out = run("99999999999999999999l", ["abc"], at(0, 0));
		assert.deepEqual(out.snapshot.cursor, at(0, 2));
	});
});

describe("vv and Enter", () => {
	it("vv is the external-editor action", () => {
		const out = run("vv", ["abc"], at(0, 1));
		assert.deepEqual(out.effects, [{ type: "pi", action: "external-editor" }]);
		assert.equal(out.state.pending, "");
	});

	it("a lone v stays pending and shows in the border", () => {
		const out = run("v", ["abc"], at(0, 1));
		assert.equal(out.state.pending, "v");
		assert.deepEqual(out.effects, []);
	});

	it("Enter is the submit action and clears the pending keys", () => {
		assert.deepEqual(run("<CR>", ["abc"], at(0, 1)).effects, [{ type: "pi", action: "submit" }]);
		const out = run("v<CR>", ["abc"], at(0, 1));
		assert.deepEqual(out.lastEffects, [{ type: "pi", action: "submit" }]);
		assert.equal(out.state.pending, "");
	});
});

describe("motion prefixes and searches", () => {
	it("hold g, f and a counted t as pending commands", () => {
		for (const keys of ["g", "f", "2t", "3g"]) {
			const out = run(keys, ["abc"], at(0, 1));

			assert.equal(out.state.pending, keys);
			assert.deepEqual(out.effects, [], keys);
		}
	});

	it("cancel g followed by an unmapped key without moving (AC7)", () => {
		for (const keys of ["gz", "gq", "g<Esc>"]) {
			const out = run(keys, ["abc"], at(0, 1));

			assert.deepEqual(out.snapshot, { lines: ["abc"], cursor: at(0, 1) }, keys);
			assert.equal(out.state.pending, "", keys);
		}
	});

	it("remember a search that finds nothing", () => {
		const out = run("fz", ["abc"], at(0, 0));

		assert.deepEqual(out.effects, []);
		assert.deepEqual(out.state.lastFind, { key: "f", char: "z" });
	});

	it("repeat the remembered search after other commands", () => {
		const out = run("fbl;", ["abcabcb"], at(0, 0));

		assert.deepEqual(out.snapshot.cursor, at(0, 4));
		assert.deepEqual(out.state.lastFind, { key: "f", char: "b" });
	});

	it("keep the remembered search through insert mode", () => {
		const out = run("fbi<Esc>;", ["abcabc"], at(0, 0));

		assert.deepEqual(out.state.lastFind, { key: "f", char: "b" });
	});

	it("pin the wanted column to the line end after $", () => {
		const out = run("$", ["abc", "x"], at(0, 0));

		assert.deepEqual(out.state.want, { col: Infinity, cursor: at(0, 2) });
		assert.deepEqual(run("$1j", ["abc", "xyz"], at(0, 0)).snapshot.cursor, at(1, 2));
	});

	it("keep the wanted column when h or l cannot move", () => {
		const out = run("$2hG", ["", "abcdef"], at(0, 0));

		assert.deepEqual(out.snapshot.cursor, at(1, 5));
	});

	it("do not leave the buffer on a failed motion", () => {
		const out = run("%", ["abc"], at(0, 1));

		assert.deepEqual(out.effects, []);
		assert.equal(out.state.pending, "");
	});
});

describe("put size", () => {
	const register = (linewise: boolean) => ({
		...initialState,
		mode: "normal" as const,
		register: { lines: ["abc"], linewise },
	});

	it("rejects a put whose copies exceed the size limit, linewise and characterwise", () => {
		for (const linewise of [true, false]) {
			const out = run("999999999p", ["x"], at(0, 0), register(linewise));

			assert.deepEqual(out.snapshot, { lines: ["x"], cursor: at(0, 0) });
			assert.deepEqual(
				out.effects.map((effect) => effect.type),
				["notice"],
			);
		}
	});

	it("still puts a large count that fits", () => {
		const out = run("1000p", ["x"], at(0, 0), register(false));

		assert.equal(out.snapshot.lines[0], `x${"abc".repeat(1000)}`);
	});

	it("does nothing for an empty characterwise register, whatever the count", () => {
		const state = { ...register(false), register: { lines: [""], linewise: false } };
		const out = run("999999999p", ["x"], at(0, 0), state);

		assert.deepEqual(out.effects, []);
	});
});

describe("unmapped keys (AC7)", () => {
	it("cancel without changing text or moving the cursor", () => {
		for (const key of ["q", "z", "Q", "Z", "@"]) {
			const out = run(key, ["abc"], at(0, 1));
			assert.deepEqual(out.effects, [], key);
			assert.equal(out.state.pending, "", key);
			assert.equal(out.state.mode, "normal", key);
		}
	});

	it("cancel a pending v", () => {
		for (const key of ["q", "z", "x", "i"]) {
			const out = run(`v${key}`, ["abc"], at(0, 1));
			assert.deepEqual(out.snapshot, { lines: ["abc"], cursor: at(0, 1) }, key);
			assert.equal(out.state.pending, "", key);
			assert.equal(out.state.mode, "normal", key);
		}
	});

	it("cancel a pending count", () => {
		const out = run("3q", ["abc"], at(0, 1));
		assert.deepEqual(out.effects, []);
		assert.equal(out.state.pending, "");
	});

	it("leave the engine ready for the next command", () => {
		const out = run("vqx", ["abc"], at(0, 1));
		assert.deepEqual(out.snapshot.lines, ["ac"]);
	});

	it("<Esc> cancels a pending command", () => {
		const out = run("v<Esc>", ["abc"], at(0, 1));
		assert.deepEqual(out.effects, []);
		assert.equal(out.state.pending, "");
		assert.equal(run("3<Esc>", ["abc"], at(0, 1)).state.pending, "");
	});
});
