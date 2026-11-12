import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { CASES, COMMANDS } from "./cases.ts";
import { RENDER_WIDTH, createHarness, loadBuffer, renderBuffer } from "./harness.ts";

describe("case matrix coverage", () => {
	it("gives every implemented command a case", () => {
		const missing = COMMANDS.filter(
			({ command }) => !CASES.some((entry) => entry.command === command),
		).map(({ command }) => command);

		assert.deepEqual(missing, [], "commands without a case");
	});

	it("gives every countable command a counted case", () => {
		const missing = COMMANDS.filter(
			({ command, countable }) =>
				countable && !CASES.some((entry) => entry.command === command && entry.counted === true),
		).map(({ command }) => command);

		assert.deepEqual(missing, [], "countable commands without a counted case");
	});

	it("lists every command a case names", () => {
		const listed = new Set(COMMANDS.map(({ command }) => command));
		const unknown = CASES.filter(({ command }) => !listed.has(command)).map(({ name }) => name);

		assert.deepEqual(unknown, [], "cases naming a command outside the manifest");
	});

	it("flags a case as counted only when its keys carry a count", () => {
		const wrong = CASES.filter(
			({ keys, counted }) => counted === true && !/(?:^|\D)[1-9]/.test(keys),
		).map(({ name }) => name);

		assert.deepEqual(wrong, []);
	});

	it("has unique case names", () => {
		const names = CASES.map(({ name }) => name);

		assert.equal(new Set(names).size, names.length);
	});
});

describe("case matrix through VimEditor", () => {
	for (const { name, command, buffer, keys, expect, mode = "normal" } of CASES) {
		it(name, () => {
			const h = createHarness();
			let externalEditorOpens = 0;
			h.editor.onAction("app.editor.external", () => {
				externalEditorOpens++;
			});
			loadBuffer(h.editor, buffer, "normal");
			// Pi's cursor-down and cursor-up read the layout of the last render
			h.editor.render(RENDER_WIDTH);
			h.clearRecords();

			h.press(keys);

			assert.equal(renderBuffer(h.editor.getLines(), h.editor.getCursor()), expect);
			assert.equal(h.editor.getMode(), mode);
			assert.equal(externalEditorOpens, command === "vv" ? 1 : 0);
			assert.deepEqual(
				h.notices.filter(({ level }) => level === "error"),
				[],
			);
		});
	}
});
