import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { cursorShapeFor, cursorShapeSequence, osc52Sequence } from "../terminal.ts";
import { RENDER_WIDTH, createHarness, loadBuffer, placeCursor } from "./harness.ts";

const BAR = "\x1b[6 q";
const BLOCK = "\x1b[2 q";
const DEFAULT = "\x1b[0 q";
const UNDERLINE = "\x1b[4 q";

function bottomBorder(lines: string[]): string {
	return lines.at(-1) ?? "";
}

describe("cursor shape sequences", () => {
	it("builds DECSCUSR for each shape", () => {
		assert.equal(cursorShapeSequence("bar"), "\x1b[6 q");
		assert.equal(cursorShapeSequence("block"), "\x1b[2 q");
		assert.equal(cursorShapeSequence("underline"), "\x1b[4 q");
		assert.equal(cursorShapeSequence("default"), "\x1b[0 q");
	});

	it("picks a bar for insert mode and a block for normal mode", () => {
		const state = {
			pending: "",
			want: null,
			lastFind: null,
			register: null,
			autoIndent: null,
			lastChange: null,
			insertCount: null,
		};
		assert.equal(cursorShapeFor({ ...state, mode: "insert" }), "bar");
		assert.equal(cursorShapeFor({ ...state, mode: "normal" }), "block");
	});

	it("picks an underline while an operator waits for its target", () => {
		const state = {
			want: null,
			lastFind: null,
			register: null,
			autoIndent: null,
			lastChange: null,
			insertCount: null,
		};
		for (const pending of ["d", "c", "y", "2d", "d2", "di", "dg", '"+y', '2"+d3']) {
			assert.equal(cursorShapeFor({ ...state, pending, mode: "normal" }), "underline", pending);
		}
		for (const pending of ["", "2", "g", "v", "f", '"', '"+', "r"]) {
			assert.equal(cursorShapeFor({ ...state, pending, mode: "normal" }), "block", pending);
		}
	});

	it("keeps the bar in insert mode whatever is pending", () => {
		const state = {
			want: null,
			lastFind: null,
			register: null,
			autoIndent: null,
			lastChange: null,
			insertCount: null,
		};

		assert.equal(cursorShapeFor({ ...state, pending: "d", mode: "insert" }), "bar");
	});
});

describe("cursor shape writes (AC4)", () => {
	it("writes the insert shape at construction", () => {
		const h = createHarness();

		assert.deepEqual(h.writes, [BAR]);
	});

	it("follows insert -> normal -> insert", () => {
		const h = createHarness();
		h.clearRecords();

		h.press("<Esc>");
		assert.deepEqual(h.writes, [BLOCK]);
		h.press("i");
		assert.deepEqual(h.writes, [BLOCK, BAR]);
	});

	it("writes the underline after d and the block once the motion completes", () => {
		const h = createHarness();
		loadBuffer(h.editor, "foo |bar baz", "normal");
		h.clearRecords();

		h.press("d");
		assert.deepEqual(h.writes, [UNDERLINE]);
		h.press("w");

		assert.deepEqual(h.writes, [UNDERLINE, BLOCK]);
		assert.equal(h.editor.getText(), "foo baz");
	});

	it("keeps the underline through a count, a prefix and a text object", () => {
		const h = createHarness();
		loadBuffer(h.editor, "foo |bar baz", "normal");
		h.clearRecords();

		h.press("2d");
		h.press("i");
		assert.deepEqual(h.writes, [UNDERLINE]);
		h.press("w");

		assert.deepEqual(h.writes, [UNDERLINE, BLOCK]);
	});

	it("returns to the block when an operator is cancelled", () => {
		const h = createHarness();
		loadBuffer(h.editor, "foo |bar", "normal");
		h.clearRecords();

		h.press("y");
		h.press("<Esc>");

		assert.deepEqual(h.writes, [UNDERLINE, BLOCK]);
	});

	it("goes from the underline to the bar when c enters insert mode", () => {
		const h = createHarness();
		loadBuffer(h.editor, "foo |bar", "normal");
		h.clearRecords();

		h.press("cw");

		assert.deepEqual(h.writes, [UNDERLINE, BAR]);
	});

	it("writes nothing when the mode does not change", () => {
		const h = createHarness();
		h.press("abc");
		h.clearRecords();

		h.press("<Left>");
		h.editor.setText("zzz");

		assert.deepEqual(h.writes, []);
	});

	it("switches to the insert shape when Pi's clear resets the mode", () => {
		const h = createHarness();
		loadBuffer(h.editor, "ab|c", "normal");
		h.clearRecords();

		h.press("<C-c>");

		assert.deepEqual(h.writes, [BAR]);
	});

	for (const clean of [true, false]) {
		const outcome = clean ? "clean exit" : "failed editor";
		it(`resets before vv and restores on the first render (${outcome})`, () => {
			const h = createHarness();
			h.editor.onAction("app.editor.external", () => {});
			loadBuffer(h.editor, "fo|o", "normal");
			h.clearRecords();

			h.press("vv");
			assert.deepEqual(h.writes, [DEFAULT]);

			if (clean) h.editor.setText("bar");
			assert.deepEqual(h.writes, [DEFAULT]);

			h.editor.render(RENDER_WIDTH);
			assert.deepEqual(h.writes, [DEFAULT, BLOCK]);

			h.editor.render(RENDER_WIDTH);
			assert.deepEqual(h.writes, [DEFAULT, BLOCK]);
		});
	}

	for (const [key, action] of [
		["<C-g>", "app.editor.external"],
		["<C-z>", "app.suspend"],
	] as const) {
		for (const mode of ["insert", "normal"] as const) {
			it(`${key} in ${mode} mode resets and restores the shape`, () => {
				const h = createHarness();
				h.editor.onAction(action, () => {});
				loadBuffer(h.editor, "fo|o", mode);
				h.clearRecords();

				h.press(key);
				assert.deepEqual(h.writes, [DEFAULT]);

				h.editor.render(RENDER_WIDTH);
				assert.deepEqual(h.writes, [DEFAULT, mode === "insert" ? BAR : BLOCK]);
			});
		}
	}

	it("reapplies the shape of the current mode on request", () => {
		const h = createHarness();
		h.press("<Esc>");
		h.clearRecords();

		h.editor.reapplyCursorShape();

		assert.deepEqual(h.writes, [BLOCK]);
	});

	it("reports an error and writes nothing when vv has no external editor action", () => {
		const h = createHarness();
		loadBuffer(h.editor, "fo|o", "normal");
		h.clearRecords();

		h.press("vv");

		assert.deepEqual(h.writes, []);
		assert.equal(h.notices[0]?.level, "error");
	});
});

describe("bottom border", () => {
	it("shows the mode label", () => {
		const h = createHarness();
		assert.match(bottomBorder(h.editor.render(RENDER_WIDTH)), /INSERT/);

		h.press("<Esc>");
		const border = bottomBorder(h.editor.render(RENDER_WIDTH));
		assert.match(border, /NORMAL/);
		assert.doesNotMatch(border, /INSERT/);
	});

	it("shows the pending keys and drops them once the command is done", () => {
		const h = createHarness();
		loadBuffer(h.editor, "ab|c", "normal");

		h.press("v");
		assert.match(bottomBorder(h.editor.render(RENDER_WIDTH)), / NORMAL +v /);

		h.press("v");
		assert.doesNotMatch(bottomBorder(h.editor.render(RENDER_WIDTH)), / v /);
	});

	it("keeps the label next to Pi's scroll indicator", () => {
		const h = createHarness();
		const text = Array.from({ length: 30 }, (_, index) => `l${index}`).join("\n");
		placeCursor(h.editor, text, { line: 0, col: 0 });

		const border = bottomBorder(h.editor.render(RENDER_WIDTH));

		assert.match(border, /INSERT/);
		assert.match(border, /↓ \d+ more/);
		assert.equal([...border].length, RENDER_WIDTH);
	});

	it("is exactly as wide as the render width", () => {
		const h = createHarness();
		h.press("<Esc>v");

		assert.equal([...bottomBorder(h.editor.render(RENDER_WIDTH))].length, RENDER_WIDTH);
	});
});

describe("clipboard (AC1, AC7)", () => {
	const OSC = (base64: string): string => `\x1b]52;c;${base64}\x07`;

	it("builds OSC 52 with base64 of the UTF-8 bytes", () => {
		assert.equal(osc52Sequence("abc"), OSC("YWJj"));
		assert.equal(osc52Sequence("漢字"), OSC("5ryi5a2X"));
		assert.equal(osc52Sequence("abc\n"), OSC("YWJjCg=="));
	});

	it('writes OSC 52 for "+yiw and fills the unnamed register', () => {
		const h = createHarness();
		loadBuffer(h.editor, "foo b|ar", "normal");
		h.clearRecords();

		h.press('"+yiw');
		assert.deepEqual(h.writes, [UNDERLINE, BLOCK, OSC("YmFy")]);
		assert.equal(h.editor.getText(), "foo bar");

		h.press("$p");
		assert.equal(h.editor.getText(), "foo barbar");
	});

	it('writes the line and its line break for "+yy', () => {
		const h = createHarness();
		loadBuffer(h.editor, "ab|c", "normal");
		h.clearRecords();

		h.press('"+yy');

		assert.equal(h.writes.at(-1), OSC("YWJjCg=="));
		h.press("p");
		assert.equal(h.editor.getText(), "abc\nabc");
	});

	it('writes non-ASCII text for "+Y', () => {
		const h = createHarness();
		loadBuffer(h.editor, "|漢字", "normal");
		h.clearRecords();

		h.press('"+Y');

		assert.equal(h.writes.at(-1), OSC("5ryi5a2X"));
	});

	it('writes the clipboard for "+ with a motion, an operator count and d', () => {
		const h = createHarness();
		loadBuffer(h.editor, "|foo bar baz", "normal");
		h.clearRecords();

		h.press('"+y2w');
		assert.equal(h.writes.at(-1), OSC("Zm9vIGJhciA="));

		h.clearRecords();
		h.press('"+dw');
		assert.equal(h.writes.at(-1), OSC("Zm9vIA=="));
		assert.equal(h.editor.getText(), "bar baz");
	});

	it("writes nothing for a plain yank", () => {
		const h = createHarness();
		loadBuffer(h.editor, "ab|c", "normal");
		h.clearRecords();

		h.press("yy");

		assert.ok(h.writes.every((data) => !data.startsWith("\x1b]52")));
	});

	for (const key of ["p", "P"]) {
		it(`"+${key} changes no text and says the clipboard cannot be read`, () => {
			const h = createHarness();
			loadBuffer(h.editor, "ab|c", "normal");
			h.press("yl");
			h.clearRecords();

			h.press(`"+${key}`);

			assert.equal(h.editor.getText(), "abc");
			assert.equal(h.notices.length, 1);
			assert.equal(h.notices[0]?.level, "warning");
			assert.match(h.notices[0]?.message ?? "", /clipboard/);
			assert.equal(h.editor.getPendingKeys(), "");
		});
	}

	it('cancels "q with no text change and no clipboard write', () => {
		const h = createHarness();
		loadBuffer(h.editor, "ab|c", "normal");
		h.clearRecords();

		h.press('"q');

		assert.equal(h.editor.getText(), "abc");
		assert.equal(h.editor.getPendingKeys(), "");
		assert.equal(h.editor.getMode(), "normal");
		assert.deepEqual(h.notices, []);
		assert.deepEqual(h.writes, []);
	});

	it('cancels "+ before a command that takes no register', () => {
		const h = createHarness();
		loadBuffer(h.editor, "a|bc", "normal");
		h.clearRecords();

		h.press('"+w');

		assert.equal(h.editor.getPendingKeys(), "");
		assert.equal(h.editor.getText(), "abc");
		assert.deepEqual(h.writes, []);
	});

	it("keeps the register across a submit", () => {
		const h = createHarness();
		loadBuffer(h.editor, "a|bc", "normal");
		h.press("yl");

		h.press("<CR>");
		h.editor.setText("xyz");
		h.press("<Esc>0p");

		assert.equal(h.editor.getText(), "xbyz");
	});
});
