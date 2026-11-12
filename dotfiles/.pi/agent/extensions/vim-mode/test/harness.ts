/**
 * Test harness: a real `VimEditor` (or a plain `CustomEditor`) on a stub TUI, with recording
 * hooks, Vim-notation key parsing and cursor-marker buffer helpers.
 */

import { CustomEditor } from "@earendil-works/pi-coding-agent";
import type { KeybindingsManager as PiKeybindingsManager } from "@earendil-works/pi-coding-agent";
import {
	KeybindingsManager,
	setKeybindings,
	TUI_KEYBINDINGS,
	type AutocompleteProvider,
	type EditorTheme,
	type TUI,
} from "@earendil-works/pi-tui";
import type { ExternalChange } from "../editor.ts";
import { VimEditor } from "../editor.ts";
import type { Cursor, Mode, NoticeLevel } from "../protocol.ts";
import { graphemeStarts, nextBoundary } from "../text.ts";

const identity = (text: string): string => text;

export const STUB_THEME: EditorTheme = {
	borderColor: identity,
	selectList: {
		selectedPrefix: identity,
		selectedText: identity,
		description: identity,
		scrollInfo: identity,
		noMatch: identity,
	},
};

export const STUB_KEYBINDINGS = new KeybindingsManager({
	...TUI_KEYBINDINGS,
	"app.interrupt": { defaultKeys: "escape" },
	"app.clear": { defaultKeys: "ctrl+c" },
	"app.exit": { defaultKeys: "ctrl+d" },
	"app.suspend": { defaultKeys: "ctrl+z" },
	"app.editor.external": { defaultKeys: "ctrl+g" },
	"app.clipboard.pasteImage": { defaultKeys: ["alt+v", "ctrl+v"] },
});
setKeybindings(STUB_KEYBINDINGS);

/** A stub TUI whose terminal passes writes to `write`. */
export function createTui(write: (data: string) => void = () => {}): TUI {
	return { requestRender() {}, terminal: { rows: 40, columns: 80, write } } as unknown as TUI;
}

export const RENDER_WIDTH = 80;

export interface Notice {
	message: string;
	level: NoticeLevel;
}

type EditorClass = new (...args: ConstructorParameters<typeof VimEditor>) => VimEditor;

export interface HarnessOptions {
	editorClass?: EditorClass;
}

export interface Harness {
	editor: VimEditor;
	/** Terminal bytes written by the editor. */
	writes: string[];
	notices: Notice[];
	externals: ExternalChange[];
	/** Texts delivered to the `onChange` Pi assigned. */
	changes: string[];
	/** Texts delivered to the `onSubmit` Pi assigned. */
	submits: string[];
	/** Number of times `onEscape` ran. */
	escapes: () => number;
	/** Types Vim-notation keys into the editor. */
	press: (notation: string) => void;
	/** Forgets recorded writes, notices, hook calls, changes and submits. */
	clearRecords: () => void;
}

/** Builds a `VimEditor` wired the way Pi wires it: handlers assigned after construction. */
export function createHarness(options: HarnessOptions = {}): Harness {
	let escapes = 0;
	const writes: string[] = [];
	const notices: Notice[] = [];
	const externals: ExternalChange[] = [];
	const changes: string[] = [];
	const submits: string[] = [];

	const EditorType = options.editorClass ?? VimEditor;
	const editor = new EditorType(
		createTui(),
		STUB_THEME,
		STUB_KEYBINDINGS as unknown as PiKeybindingsManager,
		{
			notify: (message, level) => notices.push({ message, level }),
			write: (data) => writes.push(data),
			onExternalChange: (change) => externals.push(change),
		},
	);
	editor.onChange = (text) => changes.push(text);
	editor.onSubmit = (text) => submits.push(text);
	editor.onEscape = () => {
		escapes++;
	};
	editor.onAction("app.clear", () => editor.setText(""));

	return {
		editor,
		writes,
		notices,
		externals,
		changes,
		submits,
		escapes: () => escapes,
		press: (notation) => pressKeys(editor, notation),
		clearRecords: () => {
			for (const record of [writes, notices, externals, changes, submits]) record.length = 0;
			escapes = 0;
		},
	};
}

/** A `CustomEditor` with the same stubs, the reference for pass-through behaviour. */
export function createPlainEditor(): CustomEditor {
	const keybindings = STUB_KEYBINDINGS as unknown as PiKeybindingsManager;
	return new CustomEditor(createTui(), STUB_THEME, keybindings);
}

/** A provider that offers `/model` and `/mode` for any text starting with `/`. */
export function createSlashProvider(): AutocompleteProvider {
	return {
		getSuggestions: async (lines, cursorLine, cursorCol) => {
			const prefix = (lines[cursorLine] ?? "").slice(0, cursorCol);
			if (!prefix.startsWith("/")) return null;
			const items = ["model", "mode"]
				.filter((name) => `/${name}`.startsWith(prefix))
				.map((name) => ({ value: `/${name}`, label: `/${name}` }));
			return { items, prefix };
		},
		applyCompletion: (lines, cursorLine, _cursorCol, item) => {
			const completed = lines.with(cursorLine, item.value);
			return { lines: completed, cursorLine, cursorCol: item.value.length };
		},
	};
}

/** Waits for the editor's asynchronous autocomplete request to settle. */
export async function settle(): Promise<void> {
	await new Promise((resolve) => setImmediate(resolve));
	await new Promise((resolve) => setImmediate(resolve));
}

const NAMED_KEYS: Record<string, string> = {
	Esc: "\x1b",
	CR: "\r",
	BS: "\x7f",
	Tab: "\t",
	Up: "\x1b[A",
	Down: "\x1b[B",
	Right: "\x1b[C",
	Left: "\x1b[D",
	Home: "\x1b[H",
	End: "\x1b[F",
	Del: "\x1b[3~",
	lt: "<",
};

const SPECIAL_KEY = /(<(?:Esc|CR|BS|Tab|Up|Down|Left|Right|Home|End|Del|lt|[CA]-[^>]+)>)/u;

function decodeToken(token: string): string {
	if (!token.startsWith("<") || token.length === 1) return token;
	const name = token.slice(1, -1);
	const named = NAMED_KEYS[name];
	if (named !== undefined) return named;

	const target = name.slice(2);
	if (name.startsWith("C-")) {
		if (target === "-") return "\x1f";
		return String.fromCharCode(target.toLowerCase().charCodeAt(0) & 0x1f);
	}
	return `\x1b${target === "BS" ? "\x7f" : target}`;
}

/**
 * Splits Vim notation into the terminal data of each key press: `<Esc>`, `<CR>`, `<BS>`,
 * `<Tab>`, `<Up>` `<Down>` `<Left>` `<Right>` `<Home>` `<End>` `<Del>`, `<lt>`, `<C-x>`, `<C-->`
 * and `<A-x>`. Everything else is typed literally, one UTF-16 unit per key press, which is how
 * Pi's stdin buffer delivers raw text.
 */
export function parseKeys(notation: string): string[] {
	return notation
		.split(SPECIAL_KEY)
		.flatMap((part, index) => (index % 2 === 1 ? [decodeToken(part)] : part.split("")));
}

/** Types the notation as one burst of input: the editor's held-back text runs at its end. */
export function pressKeys(
	editor: { handleInput: (data: string) => void; flushPendingInput?: () => void },
	notation: string,
): void {
	for (const data of parseKeys(notation)) editor.handleInput(data);
	editor.flushPendingInput?.();
}

/** Bracketed-paste terminal data for `text`. */
export function paste(text: string): string {
	return `\x1b[200~${text}\x1b[201~`;
}

export const CURSOR_MARK = "|";

export interface Buffer {
	text: string;
	cursor: Cursor;
}

/** Parses a buffer whose single `|` marks the cursor. */
export function parseBuffer(marked: string): Buffer {
	const offset = marked.indexOf(CURSOR_MARK);
	if (offset === -1 || marked.indexOf(CURSOR_MARK, offset + 1) !== -1) {
		throw new Error(`expected exactly one '${CURSOR_MARK}' in ${JSON.stringify(marked)}`);
	}
	const text = marked.slice(0, offset) + marked.slice(offset + 1);
	const lines = marked.slice(0, offset).split("\n");
	return { text, cursor: { line: lines.length - 1, col: lines.at(-1)?.length ?? 0 } };
}

/** Inverse of `parseBuffer`. */
export function renderBuffer(lines: readonly string[], cursor: Cursor): string {
	return lines
		.map((text, index) =>
			index === cursor.line
				? text.slice(0, cursor.col) + CURSOR_MARK + text.slice(cursor.col)
				: text,
		)
		.join("\n");
}

interface Placeable {
	setText: (text: string) => void;
	getCursor: () => Cursor;
	handleInput: (data: string) => void;
}

/** Sets the text and walks the cursor to `cursor` with arrow keys. */
export function placeCursor(editor: Placeable, text: string, cursor: Cursor): void {
	editor.setText(text);
	for (let sent = 0; sent < text.length * 2 + 2; sent++) {
		const current = editor.getCursor();
		if (current.line === cursor.line && current.col === cursor.col) return;
		const sameLine = current.line === cursor.line;
		const past = current.line > cursor.line || (sameLine && current.col > cursor.col);
		editor.handleInput(past ? "\x1b[D" : "\x1b[C");
	}
	throw new Error(`could not place the cursor at ${JSON.stringify(cursor)}`);
}

/**
 * Loads a marked buffer into a `VimEditor`. In normal mode the cursor must sit on a grapheme,
 * or at column 0 of an empty line.
 */
export function loadBuffer(editor: VimEditor, marked: string, mode: Mode = "insert"): void {
	const { text, cursor } = parseBuffer(marked);
	if (mode === "insert") {
		placeCursor(editor, text, cursor);
		return;
	}

	const line = text.split("\n")[cursor.line] ?? "";
	if (line !== "" && !graphemeStarts(line).includes(cursor.col)) {
		throw new Error(`normal mode needs the cursor on a grapheme: ${JSON.stringify(marked)}`);
	}
	// Escape moves the cursor one grapheme left, so start one to the right
	placeCursor(editor, text, { line: cursor.line, col: nextBoundary(line, cursor.col) });
	editor.handleInput("\x1b");
}
