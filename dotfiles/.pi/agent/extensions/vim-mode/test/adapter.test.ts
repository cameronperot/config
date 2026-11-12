import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { StdinBuffer } from "@earendil-works/pi-tui";
import { VimEditor } from "../editor.ts";
import type { Cursor } from "../protocol.ts";
import { clampNormalCol } from "../text.ts";
import {
	RENDER_WIDTH,
	createHarness,
	createPlainEditor,
	createSlashProvider,
	loadBuffer,
	paste,
	parseBuffer,
	placeCursor,
	pressKeys,
	renderBuffer,
	settle,
} from "./harness.ts";

const THUMB = "👍🏽";
const FAMILY = "👨‍👩‍👧";

const at = (line: number, col: number): Cursor => ({ line, col });

function marked(editor: VimEditor): string {
	return renderBuffer(editor.getLines(), editor.getCursor());
}

const BIG_PASTE_LINES = Array.from({ length: 15 }, (_, index) => `line ${index}`);
const BIG_PASTE = BIG_PASTE_LINES.join("\n");

describe("chords reach Pi unchanged (AC5)", () => {
	const chords = ["<C-a>", "<C-e>", "<C-w>", "<C-u>", "<C-k>", "<A-b>", "<A-f>", "<A-d>"];
	const insertStates = [
		"foo bar| baz",
		"|foo bar baz",
		"foo bar baz|",
		"ab cd\nef |gh\nij kl",
		`a ${THUMB}| 漢字 b`,
	];
	const normalStates = ["foo ba|r baz", "|foo bar baz", "foo bar ba|z", "ab cd\nef |gh\nij kl"];

	for (const chord of chords) {
		it(`${chord} in insert mode matches a plain editor`, () => {
			for (const state of insertStates) {
				const vim = createHarness();
				const plain = createPlainEditor();
				const { text, cursor } = parseBuffer(state);
				loadBuffer(vim.editor, state);
				placeCursor(plain, text, cursor);

				vim.press(chord);
				pressKeys(plain, chord);

				assert.equal(vim.editor.getText(), plain.getText(), `${chord} text in ${state}`);
				assert.deepEqual(vim.editor.getCursor(), plain.getCursor(), `${chord} cursor`);
			}
		});

		it(`${chord} in normal mode edits like a plain editor and clamps the cursor`, () => {
			for (const state of normalStates) {
				const vim = createHarness();
				const plain = createPlainEditor();
				const { text, cursor } = parseBuffer(state);
				loadBuffer(vim.editor, state, "normal");
				placeCursor(plain, text, cursor);

				vim.press(chord);
				pressKeys(plain, chord);

				assert.equal(vim.editor.getText(), plain.getText(), `${chord} text in ${state}`);
				const { line, col } = plain.getCursor();
				const expected = at(line, clampNormalCol(plain.getLines()[line] ?? "", col));
				assert.deepEqual(vim.editor.getCursor(), expected, `${chord} cursor in ${state}`);
				assert.equal(vim.editor.getMode(), "normal");
			}
		});
	}

	it("printable keys and Backspace in insert mode match a plain editor", () => {
		const vim = createHarness();
		const plain = createPlainEditor();
		vim.press("hello wor<BS>ld 漢字<BS>x");
		pressKeys(plain, "hello wor<BS>ld 漢字<BS>x");

		assert.equal(vim.editor.getText(), plain.getText());
		assert.deepEqual(vim.editor.getCursor(), plain.getCursor());
	});
});

describe("escape policy (AC2)", () => {
	const cases = [
		{ text: "hello", forwarded: false },
		{ text: "!ls", forwarded: true },
		{ text: "", forwarded: false },
	];

	for (const { text, forwarded } of cases) {
		it(`insert mode, text=${JSON.stringify(text)}`, () => {
			const h = createHarness();
			h.editor.setText(text);
			h.clearRecords();

			h.press("<Esc>");

			assert.equal(h.escapes(), forwarded ? 1 : 0);
			assert.equal(h.editor.getMode(), "normal");
		});
	}

	it("reaches Pi on the second Escape from insert mode", () => {
		const h = createHarness();
		h.editor.setText("hello");
		h.clearRecords();

		h.press("<Esc><Esc>");

		assert.equal(h.escapes(), 1);
		assert.equal(h.editor.getMode(), "normal");
	});

	it("treats whitespace before ! as bash mode, as Pi does", () => {
		const h = createHarness();
		h.editor.setText("  !echo x");
		h.clearRecords();

		h.press("<Esc>");

		assert.equal(h.escapes(), 1);
		assert.equal(h.editor.getMode(), "normal");
	});

	it("closes autocomplete without reaching onEscape", async () => {
		const h = createHarness();
		h.editor.setAutocompleteProvider(createSlashProvider());
		h.press("/mod");
		await settle();
		assert.equal(h.editor.isShowingAutocomplete(), true);

		h.press("<Esc>");

		assert.equal(h.editor.isShowingAutocomplete(), false);
		assert.equal(h.escapes(), 0);
		assert.equal(h.editor.getText(), "/mod");
		assert.equal(h.editor.getMode(), "normal");
	});

	it("reaches onEscape on every Escape in normal mode", () => {
		const h = createHarness();
		h.press("<Esc>");
		h.press("<Esc>");
		h.press("<Esc>");

		assert.equal(h.escapes(), 2);
		assert.equal(h.editor.getMode(), "normal");
	});

	it("cancels a pending v, changes no text and still reaches onEscape", () => {
		const h = createHarness();
		loadBuffer(h.editor, "ab|c", "normal");
		h.clearRecords();

		h.press("v");
		assert.equal(h.editor.getPendingKeys(), "v");
		h.press("<Esc>");

		assert.equal(h.editor.getPendingKeys(), "");
		assert.equal(h.editor.getText(), "abc");
		assert.equal(h.escapes(), 1);
	});

	it("cancels a pending operator, changes no text and still reaches onEscape (AC7)", () => {
		for (const operator of ["d", "c", "y", "2d", '"+y']) {
			const h = createHarness();
			loadBuffer(h.editor, "ab|c", "normal");
			h.clearRecords();

			h.press(operator);
			assert.equal(h.editor.getPendingKeys(), operator);
			h.press("<Esc>");

			assert.equal(h.editor.getPendingKeys(), "", operator);
			assert.equal(h.editor.getText(), "abc", operator);
			assert.equal(h.editor.getMode(), "normal", operator);
			assert.equal(h.escapes(), 1, operator);
		}
	});
});

describe("pastes (AC3)", () => {
	it("materializes a large paste and places the cursor after it", () => {
		const h = createHarness();
		loadBuffer(h.editor, "abc|xyz");

		h.editor.handleInput(paste(BIG_PASTE));

		assert.equal(h.editor.getText(), h.editor.getExpandedText());
		assert.ok(!h.editor.getText().includes("[paste #"));
		assert.equal(h.editor.getText(), `abc${BIG_PASTE}xyz`);
		assert.deepEqual(h.editor.getCursor(), at(14, "line 14".length));
		assert.equal(h.changes.at(-1), `abc${BIG_PASTE}xyz`);
	});

	it("delivers onChange once for a large paste", () => {
		const h = createHarness();
		h.editor.handleInput(paste(BIG_PASTE));

		assert.deepEqual(h.changes, [BIG_PASTE]);
	});

	it("submits the pasted text with later normal-mode edits applied", () => {
		const h = createHarness();
		loadBuffer(h.editor, "abc|xyz");
		h.editor.handleInput(paste(BIG_PASTE));

		h.press("<Esc>x<CR>");

		const lines = [...BIG_PASTE_LINES];
		lines[0] = `abc${lines[0]}`;
		lines[14] = "line 1xyz";
		assert.deepEqual(h.submits, [lines.join("\n")]);
	});

	it("keeps every pasted line through a dequeue-style setText", () => {
		const h = createHarness();
		h.editor.handleInput(paste(BIG_PASTE));

		h.editor.setText(`${h.editor.getText()}\nq`);

		assert.equal(h.editor.getExpandedText(), `${BIG_PASTE}\nq`);
		assert.equal(h.editor.getText(), `${BIG_PASTE}\nq`);
	});

	it("switches to insert for a short paste sent in normal mode", () => {
		const h = createHarness();
		loadBuffer(h.editor, "ab|c", "normal");
		h.clearRecords();

		h.editor.handleInput(paste("hi"));

		assert.equal(h.editor.getMode(), "insert");
		assert.equal(marked(h.editor), "abhi|c");
		assert.ok(h.externals.length <= 1);
	});

	it("switches to insert for a large paste sent in normal mode", () => {
		const h = createHarness();
		loadBuffer(h.editor, "ab|c", "normal");
		h.clearRecords();

		h.editor.handleInput(paste(BIG_PASTE));

		assert.equal(h.editor.getMode(), "insert");
		assert.equal(h.editor.getText(), `ab${BIG_PASTE}c`);
		assert.deepEqual(h.editor.getCursor(), at(14, "line 14".length));
		assert.ok(h.externals.length <= 1);
	});

	it("switches to insert for Pi's clipboard paste key in normal mode", async () => {
		const h = createHarness();
		loadBuffer(h.editor, "ab|c", "normal");
		h.editor.onPasteImage = () => {
			void Promise.resolve().then(() => h.editor.insertTextAtCursor("/tmp/pasted.png"));
		};
		h.clearRecords();

		h.press("<C-v>");
		await settle();

		assert.equal(h.editor.getMode(), "insert");
		assert.equal(marked(h.editor), "ab/tmp/pasted.png|c");
	});

	it("cancels a pending command when a paste arrives in normal mode", () => {
		const h = createHarness();
		loadBuffer(h.editor, "ab|c", "normal");
		h.press("v");

		h.editor.handleInput(paste("hi"));

		assert.equal(h.editor.getPendingKeys(), "");
		assert.equal(h.editor.getMode(), "insert");
	});
});

describe("submit and follow-up", () => {
	it("submits from normal mode and returns to an empty insert-mode prompt", () => {
		const h = createHarness();
		loadBuffer(h.editor, "hell|o", "normal");

		h.press("<CR>");

		assert.deepEqual(h.submits, ["hello"]);
		assert.equal(h.editor.getText(), "");
		assert.equal(h.editor.getMode(), "insert");
	});

	it("submits from normal mode when the cursor follows a backslash", () => {
		const h = createHarness();
		loadBuffer(h.editor, "a\\|b", "normal");

		h.press("<CR>");

		assert.deepEqual(h.submits, ["a\\b"]);
		assert.equal(h.editor.getText(), "");
		assert.equal(h.editor.getMode(), "insert");
	});

	it("keeps the last f search across a submit", () => {
		const h = createHarness();
		loadBuffer(h.editor, "|abcb", "normal");
		h.press("fb<CR>");

		loadBuffer(h.editor, "|xbyb", "normal");
		h.press(";");

		assert.equal(marked(h.editor), "x|byb");
	});

	it("resets after an idle follow-up", () => {
		const h = createHarness();
		loadBuffer(h.editor, "hell|o", "normal");
		h.press("v");

		h.editor.setText("");
		h.editor.onSubmit?.("hello");

		assert.equal(h.editor.getText(), "");
		assert.equal(h.editor.getMode(), "insert");
		assert.equal(h.editor.getPendingKeys(), "");
		assert.deepEqual(h.submits, ["hello"]);
	});

	it("resets after a streaming follow-up", () => {
		const h = createHarness();
		loadBuffer(h.editor, "hell|o", "normal");
		h.press("v");

		h.editor.setText("");

		assert.equal(h.editor.getText(), "");
		assert.equal(h.editor.getMode(), "insert");
		assert.equal(h.editor.getPendingKeys(), "");
		assert.deepEqual(h.submits, []);
	});

	it("leaves insert mode for normal mode after a bash submit", () => {
		const h = createHarness();
		h.press("!echo x<CR>");

		assert.deepEqual(h.submits, ["!echo x"]);
		assert.equal(h.editor.getText(), "");
		assert.equal(h.editor.getMode(), "normal");
	});

	it("delivers onChange before onSubmit", () => {
		const h = createHarness();
		const order: string[] = [];
		h.editor.onChange = (text) => order.push(`change:${text}`);
		h.editor.onSubmit = (text) => order.push(`submit:${text}`);

		h.press("hi<CR>");

		assert.deepEqual(order, ["change:h", "change:hi", "change:", "submit:hi"]);
	});
});

describe("mutation gateway", () => {
	it("reports history recall in normal mode once", () => {
		const h = createHarness();
		h.editor.addToHistory("old");
		loadBuffer(h.editor, "|", "normal");
		h.clearRecords();

		h.press("k");

		assert.equal(h.editor.getText(), "old");
		assert.equal(h.externals.length, 1);
		assert.deepEqual(h.changes, ["old"]);
	});

	it("reports an outside setText once", () => {
		const h = createHarness();
		loadBuffer(h.editor, "ab|c", "normal");
		h.clearRecords();

		h.editor.setText("hello");

		assert.equal(h.externals.length, 1);
		assert.deepEqual(h.changes, ["hello"]);
		assert.equal(marked(h.editor), "hell|o");
	});

	it("reports insertTextAtCursor once", () => {
		const h = createHarness();
		loadBuffer(h.editor, "ab|c");
		h.clearRecords();

		h.editor.insertTextAtCursor("XY");

		assert.equal(h.externals.length, 1);
		assert.deepEqual(h.changes, ["abXYc"]);
	});

	it("reports an external-editor-style setText once", () => {
		const h = createHarness();
		loadBuffer(h.editor, "ab|c", "normal");
		h.clearRecords();

		h.editor.setText("one\ntwo");

		assert.equal(h.externals.length, 1);
		assert.deepEqual(h.changes, ["one\ntwo"]);
		assert.equal(marked(h.editor), "one\ntw|o");
	});

	it("does not report an unchanged setText", () => {
		const h = createHarness();
		loadBuffer(h.editor, "ab|c", "normal");
		h.clearRecords();

		h.editor.setText("abc");

		assert.equal(h.externals.length, 0);
	});

	it("passes the text before and after the change to the hook", () => {
		const h = createHarness();
		loadBuffer(h.editor, "ab|c");
		h.clearRecords();

		h.editor.setText("zz");

		assert.deepEqual(h.externals[0]?.before.lines, ["abc"]);
		assert.deepEqual(h.externals[0]?.after.lines, ["zz"]);
	});

	it("cancels a pending v with a notice when the text changes outside", () => {
		const h = createHarness();
		loadBuffer(h.editor, "ab|c", "normal");
		h.press("v");
		h.clearRecords();

		h.editor.setText("zzz");

		assert.equal(h.editor.getPendingKeys(), "");
		assert.equal(h.notices.length, 1);
		assert.equal(h.notices[0]?.level, "warning");
	});

	it("keeps normal mode when a transaction empties the text", () => {
		const h = createHarness();
		loadBuffer(h.editor, "|a", "normal");
		h.clearRecords();

		h.press("x");

		assert.equal(h.editor.getText(), "");
		assert.equal(h.editor.getMode(), "normal");
		assert.equal(h.externals.length, 0);
	});

	it("keeps insert mode when Backspace empties the line", () => {
		const h = createHarness();
		loadBuffer(h.editor, "a|b", "normal");

		h.press("a<BS><BS>");
		assert.equal(h.editor.getText(), "");
		assert.equal(h.editor.getMode(), "insert");

		h.press("<Esc>");
		assert.equal(h.editor.getMode(), "normal");
		assert.equal(marked(h.editor), "|");
	});

	it("resets to insert mode on Pi's clear, on a non-empty and an empty prompt", () => {
		const h = createHarness();
		loadBuffer(h.editor, "ab|c", "normal");
		h.press("<C-c>");
		assert.equal(h.editor.getText(), "");
		assert.equal(h.editor.getMode(), "insert");

		h.press("<Esc>");
		assert.equal(h.editor.getMode(), "normal");
		h.press("<C-c>");
		assert.equal(h.editor.getMode(), "insert");
	});

	it("calls an onSubmit assigned after construction", () => {
		const h = createHarness();
		const later: string[] = [];
		h.editor.onSubmit = (text) => later.push(text);

		h.press("hi<CR>");

		assert.deepEqual(later, ["hi"]);
		assert.deepEqual(h.submits, []);
	});

	it("clamps the cursor after Pi moves it past the line end in normal mode", () => {
		const h = createHarness();
		loadBuffer(h.editor, "|abc", "normal");

		h.press("<Right><Right><Right>");
		assert.deepEqual(h.editor.getCursor(), at(0, 2));

		h.press("<Home><End>");
		assert.deepEqual(h.editor.getCursor(), at(0, 2));
		assert.equal(h.editor.getText(), "abc");
	});

	it("forgets the wanted column once Pi moves the cursor", () => {
		const h = createHarness();
		loadBuffer(h.editor, "abc|def\nab\nabcdef", "normal");

		h.press("1j");
		assert.equal(marked(h.editor), "abcdef\na|b\nabcdef");
		h.press("<C-a><C-e>");
		assert.equal(marked(h.editor), "abcdef\na|b\nabcdef");
		h.press("1j");

		assert.equal(marked(h.editor), "abcdef\nab\na|bcdef");
	});
});

describe("cursor walk and normalization", () => {
	const cases: { name: string; buffer: string; keys: string; expected: string }[] = [
		{ name: "first line", buffer: "a|bc\nde\nfg", keys: "x", expected: "a|c\nde\nfg" },
		{ name: "middle line", buffer: "ab\nc|de\nfg", keys: "x", expected: "ab\nc|e\nfg" },
		{ name: "last line", buffer: "ab\ncd\nf|g", keys: "x", expected: "ab\ncd\n|f" },
		{ name: "after an emoji", buffer: `${THUMB}|bc`, keys: "x", expected: `${THUMB}|c` },
		{ name: "after a ZWJ", buffer: `${FAMILY}|bc`, keys: "x", expected: `${FAMILY}|c` },
		{ name: "inside CJK", buffer: "漢|字x", keys: "x", expected: "漢|x" },
		{ name: "left of a far column", buffer: "ab|cdefghij", keys: "x", expected: "ab|defghij" },
		{ name: "last column", buffer: "abcdefghi|j", keys: "x", expected: "abcdefgh|i" },
	];

	for (const { name, buffer, keys, expected } of cases) {
		it(`lands exactly: ${name}`, () => {
			const h = createHarness();
			loadBuffer(h.editor, buffer, "normal");

			h.press(keys);

			assert.equal(marked(h.editor), expected);
			assert.equal(h.notices.length, 0);
		});
	}

	it("lands at a line end when entering insert mode with a", () => {
		const h = createHarness();
		loadBuffer(h.editor, "a|b\ncd", "normal");

		h.press("a");

		assert.equal(marked(h.editor), "ab|\ncd");
		assert.equal(h.editor.getMode(), "insert");
	});

	it("lands on the second visual row of a wide line", () => {
		const h = createHarness();
		const line = "a".repeat(100);
		loadBuffer(h.editor, `${line.slice(0, 90)}|${line.slice(90)}`, "normal");
		h.editor.render(RENDER_WIDTH);

		h.press("x");

		assert.equal(marked(h.editor), `${"a".repeat(90)}|${"a".repeat(9)}`);
	});

	it("normalizes an outside setText and keeps the cursor on a grapheme", () => {
		const h = createHarness();
		loadBuffer(h.editor, "ab|c", "normal");

		h.editor.setText("a\r\n\tb");

		assert.deepEqual(h.editor.getLines(), ["a", "    b"]);
		assert.deepEqual(h.editor.getCursor(), at(1, 4));
	});

	it("restores the text and cursor and reports an error when the walk stalls", () => {
		let dropped = 0;
		class StallingEditor extends VimEditor {
			protected override piInput(data: string): void {
				if (data === "\x1b[C" && dropped++ === 0) return;
				super.piInput(data);
			}
		}
		const h = createHarness({ editorClass: StallingEditor });
		loadBuffer(h.editor, "ab|cdefghij", "normal");
		h.clearRecords();

		h.press("x");

		assert.equal(marked(h.editor), "ab|cdefghij");
		assert.equal(h.notices.length, 1);
		assert.equal(h.notices[0]?.level, "error");
		assert.equal(dropped > 0, true);
	});
});

describe("terminal input delivery", () => {
	/** Feeds `data` through Pi's stdin buffer into the editor, as the terminal does. */
	function typeLikeTerminal(editor: VimEditor, data: string): void {
		const stdin = new StdinBuffer();
		stdin.on("data", (sequence: string) => editor.handleInput(sequence));
		stdin.process(data);
	}

	it("delivers raw text one UTF-16 unit at a time", () => {
		const received: string[] = [];
		const stdin = new StdinBuffer();
		stdin.on("data", (sequence: string) => received.push(sequence));
		stdin.process(`f${THUMB}`);

		assert.deepEqual(received, ["f", "\ud83d", "\udc4d", "\ud83c", "\udffd"]);
	});

	for (const [name, glyph] of [
		["a skin-tone emoji", THUMB],
		["a ZWJ sequence", FAMILY],
	] as const) {
		it(`finds ${name} typed through the stdin buffer`, async () => {
			const h = createHarness();
			loadBuffer(h.editor, `|ab${glyph}c`, "normal");

			typeLikeTerminal(h.editor, `f${glyph}`);
			await settle();

			assert.equal(marked(h.editor), `ab|${glyph}c`);
			assert.equal(h.editor.getPendingKeys(), "");
		});
	}

	it("runs a held grapheme when the next key arrives, without waiting", () => {
		const h = createHarness();
		loadBuffer(h.editor, `|ab${THUMB}c`, "normal");

		typeLikeTerminal(h.editor, `f${THUMB}x`);

		assert.equal(h.editor.getText(), "abc");
	});

	it("runs a held grapheme before an Escape", async () => {
		const h = createHarness();
		loadBuffer(h.editor, `|ab${THUMB}c`, "normal");

		typeLikeTerminal(h.editor, `f${THUMB}\x1b`);
		await settle();

		assert.equal(marked(h.editor), `ab|${THUMB}c`);
	});
});

describe("undo", () => {
	it("runs Pi's undo key in insert mode and stays there (AC5)", () => {
		const h = createHarness();
		h.press("foo bar<C-w>baz");

		h.press("<C-->");
		assert.equal(h.editor.getText(), "foo bar");
		assert.equal(h.editor.getMode(), "insert");

		h.press("<C-->");
		assert.equal(h.editor.getText(), "");
		assert.equal(h.editor.getMode(), "insert");
	});

	it("runs Pi's undo key in normal mode like u (AC5)", () => {
		const h = createHarness();
		loadBuffer(h.editor, "one |two three", "normal");
		h.press("dw");
		assert.equal(marked(h.editor), "one |three");

		h.press("<C-->");

		assert.equal(marked(h.editor), "one |two three");
		assert.equal(h.editor.getMode(), "normal");
	});

	it("cancels a pending command when Pi's undo key arrives", () => {
		const h = createHarness();
		loadBuffer(h.editor, "ab|c", "normal");
		h.press("x");

		h.press("d");
		h.press("<C-->");

		assert.equal(h.editor.getPendingKeys(), "");
		assert.equal(marked(h.editor), "ab|c");
	});

	it("undoes an external setText", () => {
		const h = createHarness();
		loadBuffer(h.editor, "ab|c", "normal");
		h.editor.setText("hello");
		assert.equal(h.editor.getText(), "hello");

		h.press("u");

		assert.equal(marked(h.editor), "ab|c");
	});

	it("undoes a history recall", () => {
		const h = createHarness();
		h.editor.addToHistory("old");
		loadBuffer(h.editor, "|", "normal");
		h.press("k");
		assert.equal(h.editor.getText(), "old");

		h.press("u");

		assert.equal(h.editor.getText(), "");
	});

	it("undoes an external change that arrives during an insert session as its own entry", () => {
		const h = createHarness();
		h.press("ab");

		h.editor.setText("zzz");
		h.press("c");
		h.press("<C-->");
		assert.equal(h.editor.getText(), "zzz");

		h.press("<C-->");
		assert.equal(h.editor.getText(), "ab");

		h.press("<C-->");
		assert.equal(h.editor.getText(), "");
	});

	it("starts a new undo entry at ctrl+w and ctrl+u in insert mode", () => {
		const h = createHarness();
		h.press("foo bar<C-w>baz<Esc>");

		h.press("u");
		assert.equal(h.editor.getText(), "foo bar");

		h.press("u");
		assert.equal(h.editor.getText(), "");

		h.press("aone two<C-u>three<Esc>u");
		assert.equal(h.editor.getText(), "one two");
	});

	it("keeps a whole insert session as one entry, with the change that opened it", () => {
		const h = createHarness();
		loadBuffer(h.editor, "a|bc d", "normal");

		h.press("cwxyz<Esc>");
		assert.equal(h.editor.getText(), "axyz d");

		h.press("u");
		assert.equal(marked(h.editor), "a|bc d");
	});

	it("records no entry for a command that changes nothing", () => {
		const h = createHarness();
		loadBuffer(h.editor, "a|bc", "normal");
		h.press("x");

		h.press("J");
		h.press("u");

		assert.equal(h.editor.getText(), "abc");
	});

	it("records no entry for an insert session that ends where it began", () => {
		const h = createHarness();
		loadBuffer(h.editor, "a|bc", "normal");
		h.press("x");

		h.press("iy<BS><Esc>");
		h.press("u");

		assert.equal(h.editor.getText(), "abc");
	});

	it("undoes as many entries as the count asks for", () => {
		const h = createHarness();
		loadBuffer(h.editor, "a|bcdef", "normal");
		h.press("xxx");
		assert.equal(h.editor.getText(), "aef");

		h.press("2u");

		assert.equal(h.editor.getText(), "acdef");
	});

	it("reports the oldest change instead of failing silently", () => {
		const h = createHarness();
		h.press("<Esc>");
		h.clearRecords();

		h.press("u");

		assert.deepEqual(h.notices, [
			{ message: "vim-mode: already at the oldest change", level: "info" },
		]);
		assert.equal(h.editor.getText(), "");
	});

	it("clears the undo entries on a submit", () => {
		const h = createHarness();
		h.press("hi<CR>");
		h.press("<Esc>");
		h.clearRecords();

		h.press("u");

		assert.equal(h.editor.getText(), "");
		assert.equal(h.notices[0]?.level, "info");
	});

	it("clears the undo entries on Pi's clear", () => {
		const h = createHarness();
		loadBuffer(h.editor, "ab|c", "normal");
		h.press("x<C-c>");
		h.press("<Esc>");
		h.clearRecords();

		h.press("u");

		assert.equal(h.editor.getText(), "");
		assert.equal(h.notices[0]?.level, "info");
	});

	it("keeps the undo entries when a transaction empties the text", () => {
		const h = createHarness();
		loadBuffer(h.editor, "|a", "normal");

		h.press("x");
		assert.equal(h.editor.getText(), "");
		h.press("u");

		assert.equal(marked(h.editor), "|a");
	});
});

describe("repeat", () => {
	it("replays a paste typed in insert mode", () => {
		const h = createHarness();
		loadBuffer(h.editor, "|ab", "normal");
		h.press("i");
		h.editor.handleInput(paste(BIG_PASTE));
		h.press("<Esc>");
		const before = h.editor.getText();
		const offset = before.length - "ab".length - 1;
		assert.equal(before, `${BIG_PASTE}ab`);

		h.press(".");

		const expected = before.slice(0, offset) + BIG_PASTE + before.slice(offset);
		assert.equal(h.editor.getText(), expected);
		assert.equal(h.editor.getText(), h.editor.getExpandedText());
		assert.ok(!h.editor.getText().includes("[paste #"));
	});

	it("replays a paste sent in normal mode as an insert", () => {
		const h = createHarness();
		loadBuffer(h.editor, "a|bc", "normal");
		h.editor.handleInput(paste("XY"));
		assert.equal(h.editor.getMode(), "insert");
		h.press("<Esc>");
		assert.equal(marked(h.editor), "aX|Ybc");

		h.press(".");

		assert.equal(marked(h.editor), "aXX|YYbc");
	});

	it("replays a large paste sent in normal mode", () => {
		const h = createHarness();
		loadBuffer(h.editor, "|z", "normal");
		h.editor.handleInput(paste(BIG_PASTE));
		h.press("<Esc>0");
		const before = h.editor.getText();
		const offset = before.length - "line 14z".length;

		h.press(".");

		assert.equal(h.editor.getText(), before.slice(0, offset) + BIG_PASTE + before.slice(offset));
		assert.equal(h.editor.getText(), h.editor.getExpandedText());
	});

	it("replays Backspace and ctrl+w from the session", () => {
		const h = createHarness();
		loadBuffer(h.editor, "|", "normal");
		h.press("ifoo bar<C-w>baz<BS>z<Esc>");
		assert.equal(h.editor.getText(), "foo baz");

		h.press("0.");

		assert.equal(h.editor.getText(), "foo bazfoo baz");
	});

	it("leaves no autocomplete list open after replaying typed text", async () => {
		const h = createHarness();
		h.editor.setAutocompleteProvider(createSlashProvider());
		loadBuffer(h.editor, "|", "normal");
		h.press("i/mod<Esc>");
		await settle();

		h.press("0.");
		await settle();

		assert.equal(h.editor.getText(), "/mod/mod");
		assert.equal(h.editor.isShowingAutocomplete(), false);
	});

	it("sends the not-repeatable notice after an arrow key and changes no text", () => {
		const h = createHarness();
		loadBuffer(h.editor, "|ab", "normal");
		h.press("ix<Left>y<Esc>");
		const before = h.editor.getText();
		h.clearRecords();

		h.press("0.");

		assert.equal(h.editor.getText(), before);
		assert.equal(h.notices.length, 1);
		assert.equal(h.notices[0]?.level, "warning");
		assert.match(h.notices[0]?.message ?? "", /not repeatable/);
	});

	it("keeps a counted insert to the typed text when the session is not repeatable", () => {
		const h = createHarness();
		loadBuffer(h.editor, "|", "normal");
		h.clearRecords();

		h.press("3ix<Left>y<Esc>");

		assert.equal(h.editor.getText(), "yx");
		assert.equal(h.editor.getMode(), "normal");
		assert.equal(h.notices.length, 1);
		assert.match(h.notices[0]?.message ?? "", /not repeatable/);
	});

	it("does not repeat a session an outside change interrupted", () => {
		const h = createHarness();
		loadBuffer(h.editor, "a|b", "normal");
		h.press("iX");
		h.editor.setText("zzz");
		h.press("<Esc>");
		const before = h.editor.getText();
		h.clearRecords();

		h.press(".");

		assert.equal(h.editor.getText(), before);
		assert.match(h.notices[0]?.message ?? "", /not repeatable/);
	});

	it("does not repeat a session a submit ended", () => {
		const h = createHarness();
		loadBuffer(h.editor, "|a", "normal");
		h.press("ofoo<CR>");
		h.press("<Esc>");
		h.clearRecords();

		h.press(".");

		assert.equal(h.editor.getText(), "");
		assert.match(h.notices[0]?.message ?? "", /not repeatable/);
	});

	it("keeps the last change across a submit", () => {
		const h = createHarness();
		loadBuffer(h.editor, "|one two", "normal");
		h.press("dw");
		h.press("<CR>");
		h.press("abc<Esc>0");

		h.press(".");

		assert.equal(h.editor.getText(), "");
	});

	it("repeats nothing before any change", () => {
		const h = createHarness();
		loadBuffer(h.editor, "a|b", "normal");
		h.clearRecords();

		h.press(".");

		assert.equal(marked(h.editor), "a|b");
		assert.deepEqual(h.notices, []);
	});

	it("types a repeated change as one undo entry", () => {
		const h = createHarness();
		loadBuffer(h.editor, "|ab", "normal");
		h.press("Ahi<Esc>0.");
		assert.equal(h.editor.getText(), "abhihi");

		h.press("u");

		assert.equal(h.editor.getText(), "abhi");
	});

	it("keeps a counted insert as one undo entry", () => {
		const h = createHarness();
		loadBuffer(h.editor, "|x", "normal");
		h.press("3oab<Esc>");
		assert.equal(h.editor.getText(), "x\nab\nab\nab");

		h.press("u");

		assert.equal(h.editor.getText(), "x");
	});

	it("keeps the recorded count of a counted insert after its repeats", () => {
		const h = createHarness();
		loadBuffer(h.editor, "|x", "normal");
		h.press("2oab<Esc>");

		h.press(".");

		assert.equal(h.editor.getText(), "x\nab\nab\nab\nab");
	});
});

describe("autoindent", () => {
	it("keeps the indent once a key followed it, even when the key was deleted again (AC1)", () => {
		const h = createHarness();
		loadBuffer(h.editor, "  a|b", "normal");

		h.press("oX<BS><Esc>");

		assert.deepEqual(h.editor.getLines(), ["  ab", "  "]);
	});

	it("still removes an autoindent that nothing followed", () => {
		const h = createHarness();
		loadBuffer(h.editor, "  a|b", "normal");

		h.press("o<Esc>");

		assert.deepEqual(h.editor.getLines(), ["  ab", ""]);
	});

	it("keeps the indent of a replayed insert whose typing was deleted again", () => {
		const h = createHarness();
		loadBuffer(h.editor, "  a|b", "normal");
		h.press("oX<BS><Esc>");

		h.press(".");

		assert.deepEqual(h.editor.getLines(), ["  ab", "  ", "  "]);
	});
});
