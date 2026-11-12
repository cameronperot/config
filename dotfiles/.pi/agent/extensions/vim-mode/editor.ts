/**
 * Pi adapter: a `CustomEditor` whose normal mode is driven by the pure engine.
 *
 * Insert mode, chords and every key the engine does not own go to Pi unchanged. Engine edits
 * reach Pi through `setText` plus a cursor walk, because the public editor API has no cursor
 * setter. The mutation gateway (`setText`, `insertTextAtCursor` and the `onSubmit`/`onChange`
 * accessors) keeps the engine consistent with changes it did not make.
 */

import { CustomEditor } from "@earendil-works/pi-coding-agent";
import type { KeybindingsManager } from "@earendil-works/pi-coding-agent";
import {
	decodeKittyPrintable,
	getKeybindings,
	matchesKey,
	visibleWidth,
} from "@earendil-works/pi-tui";
import type { EditorTheme, TUI } from "@earendil-works/pi-tui";
import { initialState, step } from "./engine.ts";
import type {
	Cursor,
	Effect,
	EngineState,
	Mode,
	NoticeLevel,
	PiAction,
	Snapshot,
} from "./protocol.ts";
import { leadingWhite } from "./operators.ts";
import { cursorShapeFor, cursorShapeSequence, osc52Sequence } from "./terminal.ts";
import { clampNormalCol, graphemeStarts } from "./text.ts";

/** A text change that did not come from the engine or from insert-mode typing. */
export interface ExternalChange {
	readonly before: Snapshot;
	readonly after: Snapshot;
}

export interface VimEditorOptions {
	notify: (message: string, level: NoticeLevel) => void;
	/** Writes raw bytes to the terminal. */
	write: (data: string) => void;
	/** Called once per external text change. */
	onExternalChange?: (change: ExternalChange) => void;
}

const PI_UP = "\x1b[A";
const PI_DOWN = "\x1b[B";
const PI_RIGHT = "\x1b[C";
const PI_LEFT = "\x1b[D";
const PI_LINE_START = "\x01";
const PI_LINE_END = "\x05";
const BRACKETED_PASTE_START = "\x1b[200~";
const CONTROL_CHARACTER = /[\u0000-\u001f\u007f-\u009f]/;
const NON_ASCII = /[^\u0000-\u007f]/;
const HIGH_SURROGATE_END = /[\ud800-\udbff]$/;

/** One undoable change: the buffer around it, with `before.cursor` where Vim's undo returns. */
interface UndoEntry {
	readonly before: Snapshot;
	readonly after: Snapshot;
}

/** Keys passed to Pi during an insert session, which `.` and counted inserts replay. */
interface Transcript {
	readonly keys: string[];
	/** False once the session held anything but typed text, deletions and pastes. */
	repeatable: boolean;
}

const NOT_REPEATABLE =
	"vim-mode: not repeatable, the insert session held keys other than typed text and deletions";

const PI_ACTION_KEYS: Record<"up" | "down", string> = { up: PI_UP, down: PI_DOWN };

/** Text a key press types, or undefined for chords, escape sequences and control keys. */
function printableText(data: string): string | undefined {
	const kitty = decodeKittyPrintable(data);
	if (kitty !== undefined) return kitty;
	return data !== "" && !CONTROL_CHARACTER.test(data) ? data : undefined;
}

function textOf(snapshot: Snapshot): string {
	return snapshot.lines.join("\n");
}

function sameCursor(a: Cursor, b: Cursor): boolean {
	return a.line === b.line && a.col === b.col;
}

/** Splits text into graphemes, the unit of one key press. */
function splitGraphemes(text: string): string[] {
	const starts = graphemeStarts(text);
	return starts.map((start, index) => text.slice(start, starts[index + 1]));
}

function sameLines(a: readonly string[], b: readonly string[]): boolean {
	return a.length === b.length && a.every((text, index) => text === b[index]);
}

/**
 * Cursor after undoing `entry`, following Neovim's `u_undoredo`: the saved cursor when it lies in
 * or next to the changed lines, otherwise the first changed line at its first non-blank.
 *
 * Neovim knows which lines a command saved. Here they come from a diff, which is ambiguous when
 * the change duplicates a neighbouring line (`yyP`): any start from `lowest` to `prefix` describes
 * the same change, so the saved cursor decides among them.
 */
function undoCursor({ before, after }: UndoEntry): Cursor {
	const common = Math.min(before.lines.length, after.lines.length);
	let prefix = 0;
	while (prefix < common && before.lines[prefix] === after.lines[prefix]) prefix++;
	let suffix = 0;
	while (suffix < common && before.lines.at(-1 - suffix) === after.lines.at(-1 - suffix)) {
		suffix++;
	}

	const lowest = Math.min(Math.max(common - suffix, 0), prefix);
	const changed = before.lines.length - prefix - Math.min(suffix, common - prefix);
	const { cursor } = before;
	if (cursor.line >= lowest - 1 && cursor.line <= prefix + changed) return cursor;
	if (prefix >= before.lines.length) return { line: before.lines.length - 1, col: 0 };

	const text = before.lines[prefix] ?? "";
	return { line: prefix, col: clampNormalCol(text, leadingWhite(text)) };
}

/** Number of graphemes before `col`. */
function graphemeIndex(line: string, col: number): number {
	return graphemeStarts(line).filter((start) => start < col).length;
}

/** Cursor at UTF-16 `offset` of `text`, where lines are separated by `\n`. */
function cursorAtOffset(text: string, offset: number): Cursor {
	const lines = text.slice(0, offset).split("\n");
	return { line: lines.length - 1, col: lines.at(-1)?.length ?? 0 };
}

/**
 * Next key of the cursor walk. Anchoring at a line edge with `ctrl+a`/`ctrl+e` is chosen when it
 * costs fewer keys than stepping, and `←`/`→` cross line boundaries.
 */
function walkKey(lines: readonly string[], from: Cursor, to: Cursor): string {
	const text = lines[from.line] ?? "";
	if (from.line < to.line) return from.col < text.length ? PI_LINE_END : PI_RIGHT;
	if (from.line > to.line) return from.col > 0 ? PI_LINE_START : PI_LEFT;

	const fromIndex = graphemeIndex(text, from.col);
	const toIndex = graphemeIndex(text, to.col);
	const direct = Math.abs(toIndex - fromIndex);
	const viaStart = to.col === 0 ? 1 : 1 + toIndex;
	const viaEnd = 1 + graphemeStarts(text).length - toIndex;
	if (direct <= viaStart && direct <= viaEnd) return to.col > from.col ? PI_RIGHT : PI_LEFT;
	return viaStart <= viaEnd ? PI_LINE_START : PI_LINE_END;
}

export class VimEditor extends CustomEditor {
	private readonly appKeys: KeybindingsManager;
	private readonly editorTheme: EditorTheme;
	private readonly options: VimEditorOptions;
	private engineState: EngineState = initialState;
	private piOnSubmit: ((text: string) => void) | undefined;
	private piOnChange: ((text: string) => void) | undefined;
	private heldChange: string | null = null;
	// Last grapheme of the typed text while it may still grow. Pi's stdin buffer delivers raw
	// text one UTF-16 unit at a time, so an emoji with a skin tone arrives in four key presses
	private heldText = "";
	private holds = 0;
	private undoEntries: UndoEntry[] = [];
	// Buffer at the start of the open insert session, which is one undo entry; null in normal mode
	private insertSession: Snapshot | null = null;
	// Keys of the open insert session; null when no command started it
	private transcript: Transcript | null = null;
	private lastTranscript: Transcript | null = null;
	// Nonzero while a counted insert replays, which keeps its steps inside one undo entry
	private replaying = 0;
	// Set after the cursor shape was reset for an external program; the next render restores it
	private reapplyShape = false;
	// Set while a key is forwarded to Pi; `reported` marks that the gateway already accounted
	// for the key's text change
	private passing: { reported: boolean } | null = null;

	constructor(
		tui: TUI,
		theme: EditorTheme,
		keybindings: KeybindingsManager,
		options: VimEditorOptions,
	) {
		super(tui, theme, keybindings);
		this.appKeys = keybindings;
		this.editorTheme = theme;
		this.options = options;

		// `onSubmit` and `onChange` are class fields on `Editor`, so a prototype accessor would be
		// shadowed. Pi assigns both after the factory returns.
		Object.defineProperty(this, "onSubmit", {
			configurable: true,
			enumerable: true,
			get: () => this.handleSubmit,
			set: (handler: ((text: string) => void) | undefined) => {
				this.piOnSubmit = handler;
			},
		});
		Object.defineProperty(this, "onChange", {
			configurable: true,
			enumerable: true,
			get: () => this.handleChange,
			set: (handler: ((text: string) => void) | undefined) => {
				this.piOnChange = handler;
			},
		});
		this.insertSession = this.snapshot();
		this.writeShape();
	}

	getMode(): Mode {
		return this.engineState.mode;
	}

	getPendingKeys(): string {
		return this.engineState.pending;
	}

	override render(width: number): string[] {
		if (this.reapplyShape) {
			this.reapplyShape = false;
			this.writeShape();
		}
		return super.render(width);
	}

	/** Writes the shape for the current state, e.g. after the process resumes from a suspend. */
	reapplyCursorShape(): void {
		this.writeShape();
	}

	override handleInput(data: string): void {
		this.holdChanges(() => this.route(data));
	}

	/** Runs the typed grapheme that is still held back, at the end of a burst of input. */
	flushPendingInput(): void {
		this.releaseHeldText();
	}

	override setText(text: string): void {
		const before = this.snapshot();
		super.setText(text);
		this.markReported();
		this.reportExternalChange(before);
		this.forgetWantedColumn();
		if (this.getText() === "") this.resetToInsert();
		this.clampWhenNormal();
	}

	override insertTextAtCursor(text: string): void {
		const before = this.snapshot();
		super.insertTextAtCursor(text);
		this.markReported();
		this.reportExternalChange(before);
		this.forgetWantedColumn();
		this.clampWhenNormal();
	}

	protected override renderBottomBorder(width: number, hiddenLineCount: number): string {
		const { mode, pending } = this.engineState;
		const lead = "──";
		const label = ` ${mode === "insert" ? "INSERT" : "NORMAL"} `;
		const keys = pending === "" ? "" : ` ${pending} `;
		const scroll = hiddenLineCount > 0 ? ` ↓ ${hiddenLineCount} more ` : "";
		const fill = width - visibleWidth(lead + label + keys + scroll);
		if (fill < 1) return super.renderBottomBorder(width, hiddenLineCount);

		const { selectedText, description, scrollInfo } = this.editorTheme.selectList;
		return (
			this.borderColor(lead) +
			selectedText(label) +
			description(keys) +
			this.borderColor("─".repeat(fill)) +
			scrollInfo(scroll)
		);
	}

	/** Forwards `data` to Pi's editor. The cursor walk goes through here too. */
	protected piInput(data: string): void {
		super.handleInput(data);
	}

	private readonly handleSubmit = (text: string): void => {
		this.markReported();
		this.flushHeldChange();
		this.resetToInsert();
		this.piOnSubmit?.(text);
		if (text.startsWith("!")) {
			this.insertSession = null;
			this.setEngineState({ ...this.engineState, mode: "normal" });
		}
	};

	private readonly handleChange = (text: string): void => {
		if (this.holds > 0) {
			this.heldChange = text;
			return;
		}
		this.piOnChange?.(text);
	};

	private notify(message: string, level: NoticeLevel): void {
		this.options.notify(message, level);
	}

	private snapshot(): Snapshot {
		return { lines: this.getLines(), cursor: this.getCursor() };
	}

	private markReported(): void {
		if (this.passing !== null) this.passing.reported = true;
	}

	/** Delivers Pi's `onChange` once, with the final text, however many times Pi fired it. */
	private holdChanges(run: () => void): void {
		this.holds++;
		try {
			run();
		} finally {
			this.holds--;
			if (this.holds === 0) this.flushHeldChange();
		}
	}

	private flushHeldChange(): void {
		if (this.heldChange === null) return;
		const text = this.heldChange;
		this.heldChange = null;
		this.piOnChange?.(text);
	}

	private setEngineState(next: EngineState): void {
		const previous = this.engineState;
		this.engineState = next;
		if (cursorShapeFor(previous) !== cursorShapeFor(next)) this.writeShape();
		if (previous.mode !== next.mode || previous.pending !== next.pending) {
			this.tui.requestRender();
		}
	}

	private writeShape(): void {
		this.options.write(cursorShapeSequence(cursorShapeFor(this.engineState)));
	}

	/** Gives the terminal its default shape back before another program draws a cursor. */
	private suspendShape(): void {
		this.options.write(cursorShapeSequence("default"));
		this.reapplyShape = true;
	}

	private cancelPending(): void {
		if (this.engineState.pending === "") return;
		this.setEngineState({ ...this.engineState, pending: "" });
	}

	/** Drops the wanted column: a cursor Pi moved is not where the engine left it. */
	private forgetWantedColumn(): void {
		if (this.engineState.want === null) return;
		this.setEngineState({ ...this.engineState, want: null });
	}

	private resetToInsert(): void {
		const { lastFind, register, lastChange } = this.engineState;
		this.setEngineState({ ...initialState, lastFind, register, lastChange });
		this.undoEntries = [];
		this.insertSession = this.snapshot();
		// An interrupted session leaves the last change without the keys that completed it
		if (this.transcript !== null) this.lastTranscript = null;
		this.transcript = null;
	}

	private pushUndo(before: Snapshot, after: Snapshot): void {
		if (!sameLines(before.lines, after.lines)) this.undoEntries.push({ before, after });
	}

	/** Ends the open insert session, which becomes an undo entry when it changed the text. */
	private closeInsertSession(after: Snapshot): void {
		if (this.insertSession === null) return;
		this.pushUndo(this.insertSession, after);
		this.insertSession = null;
	}

	/** Once a key follows an autoindent, Escape no longer removes it, even if the line is blank. */
	private keepAutoIndent(): void {
		if (this.engineState.autoIndent === null) return;
		this.setEngineState({ ...this.engineState, autoIndent: null });
	}

	/** Starts a new undo entry in the middle of an insert session. */
	private breakInsertSession(): void {
		const now = this.snapshot();
		this.closeInsertSession(now);
		this.insertSession = now;
	}

	/** Records the undo entry of the engine key just applied, or opens or closes a session. */
	private recordUndo(
		modeBefore: Mode,
		before: Snapshot,
		edited: boolean,
		changeStart: Cursor | null,
	): void {
		if (this.replaying > 0) return;
		const after = this.snapshot();
		const mode = this.engineState.mode;
		if (modeBefore === "insert") {
			if (mode === "normal") {
				this.closeInsertSession(after);
				if (this.transcript !== null) this.lastTranscript = this.transcript;
				this.transcript = null;
			}
			return;
		}
		// Without an edit the insert point is where the entry command left the cursor
		const cursor = changeStart ?? (edited ? before.cursor : after.cursor);
		const origin = { lines: before.lines, cursor };
		if (mode === "insert") {
			this.insertSession = origin;
			this.transcript = { keys: [], repeatable: true };
		} else if (edited) this.pushUndo(origin, after);
	}

	private undoChanges(count: number): void {
		const insert = this.engineState.mode === "insert";
		if (insert) this.closeInsertSession(this.snapshot());
		const popped = this.undoEntries.splice(Math.max(this.undoEntries.length - count, 0)).reverse();
		const oldest = popped.at(-1);
		if (oldest === undefined) {
			this.notify("vim-mode: already at the oldest change", "info");
		} else {
			const { line, col } = undoCursor(oldest);
			const text = oldest.before.lines[line] ?? "";
			const cursor = { line, col: insert ? col : clampNormalCol(text, col) };
			if (this.applyEdit({ lines: oldest.before.lines, cursor })) {
				this.forgetWantedColumn();
			} else {
				this.undoEntries.push(...popped.reverse());
			}
		}
		if (insert) this.insertSession = this.snapshot();
	}

	private route(data: string): void {
		if (this.engineState.mode !== "normal" || printableText(data) === undefined) {
			this.releaseHeldText();
		}
		// The extension owns undo, so Pi's undo key runs the same undo as `u`
		if (getKeybindings().matches(data, "tui.editor.undo")) {
			this.cancelPending();
			this.undoChanges(1);
			return;
		}
		if (this.engineState.mode === "insert") {
			this.routeInsert(data);
		} else {
			this.routeNormal(data);
		}
	}

	private routeInsert(data: string): void {
		if (!matchesKey(data, "escape")) {
			const keys = getKeybindings();
			const deletesWord = keys.matches(data, "tui.editor.deleteWordBackward");
			const deletesLine = keys.matches(data, "tui.editor.deleteToLineStart");
			// Deleting a word or a line starts a new undo entry, as in Neovim
			if (deletesWord || deletesLine) this.breakInsertSession();
			const repeatable =
				deletesWord ||
				deletesLine ||
				keys.matches(data, "tui.editor.deleteCharBackward") ||
				data.includes(BRACKETED_PASTE_START) ||
				printableText(data) !== undefined;
			if (repeatable) this.transcript?.keys.push(data);
			else if (this.transcript !== null) this.transcript.repeatable = false;
			this.keepAutoIndent();
			this.passToPi(data);
			return;
		}

		// Pi consumes the Escape when it closes autocomplete or leaves bash mode. A streaming
		// response is left running, so the Escape that aborts it comes from normal mode
		const bashMode = this.getText().trimStart().startsWith("!");
		if (this.isShowingAutocomplete() || bashMode) {
			this.passToPi(data);
		}
		this.stepEngine("<Esc>", data);
	}

	private routeNormal(data: string): void {
		if (
			data.includes(BRACKETED_PASTE_START) ||
			this.appKeys.matches(data, "app.clipboard.pasteImage")
		) {
			this.enterInsertForPaste();
			if (data.includes(BRACKETED_PASTE_START)) this.transcript?.keys.push(data);
			else if (this.transcript !== null) this.transcript.repeatable = false;
			this.passToPi(data);
			return;
		}
		if (matchesKey(data, "escape")) {
			this.stepEngine("<Esc>", data);
			// Escape moves nothing, so the column a vertical motion aims for survives it
			const { want } = this.engineState;
			this.passToPi(data);
			if (want !== null) this.setEngineState({ ...this.engineState, want });
			return;
		}
		if (matchesKey(data, "enter")) {
			this.stepEngine("<CR>", data);
			return;
		}

		const text = printableText(data);
		if (text === undefined) {
			this.passToPi(data);
			return;
		}
		const typed = this.heldText + text;
		this.heldText = "";
		const starts = graphemeStarts(typed);
		// A trailing lone high surrogate may still attach to the grapheme before it as a modifier
		let tailIndex = starts.length - 1;
		if (HIGH_SURROGATE_END.test(typed)) tailIndex = Math.max(tailIndex - 1, 0);
		const tail = typed.slice(starts[tailIndex]);
		const heldFrom = NON_ASCII.test(tail) ? tailIndex : starts.length;
		for (const [index, start] of starts.slice(0, heldFrom).entries()) {
			this.stepEngine(typed.slice(start, starts[index + 1]), data);
		}
		if (heldFrom < starts.length) this.holdText(tail);
	}

	/** Keeps text back until more input arrives or the current burst of input ends. */
	private holdText(text: string): void {
		this.heldText = text;
		queueMicrotask(() => this.releaseHeldText());
	}

	private releaseHeldText(): void {
		const text = this.heldText;
		if (text === "") return;
		this.heldText = "";
		const starts = graphemeStarts(text);
		this.holdChanges(() => {
			for (const [index, start] of starts.entries()) {
				this.stepEngine(text.slice(start, starts[index + 1]), text);
			}
		});
	}

	/** A paste in normal mode acts as an `i` followed by the pasted text. */
	private enterInsertForPaste(): void {
		const lastChange = { keys: "i", count: null, register: null, insert: true };
		this.setEngineState({
			...this.engineState,
			mode: "insert",
			pending: "",
			want: null,
			lastChange,
			insertCount: null,
		});
		this.insertSession = this.snapshot();
		this.transcript = { keys: [], repeatable: true };
	}

	private stepEngine(key: string, data: string): void {
		if (this.engineState.mode === "normal") this.clampCursor();
		const modeBefore = this.engineState.mode;
		const before = this.snapshot();
		const result = step(this.engineState, before, key);
		this.setEngineState(result.state);

		let changeStart: Cursor | null = null;
		let edited = false;
		for (const effect of result.effects) {
			if (effect.type === "change-start") {
				changeStart = effect.cursor;
				continue;
			}
			if (effect.type === "edit") edited = true;
			this.applyEffect(effect, data);
		}
		this.recordUndo(modeBefore, before, edited, changeStart);
	}

	private applyEffect(effect: Exclude<Effect, { type: "change-start" }>, data: string): void {
		switch (effect.type) {
			case "cursor":
				this.moveCursorTo(effect.cursor);
				break;
			case "edit":
				this.applyEdit(effect.snapshot);
				break;
			case "mode":
				// The engine state already carries the mode
				break;
			case "pi":
				this.runPiAction(effect.action, data);
				break;
			case "notice":
				this.notify(effect.message, effect.level);
				break;
			case "clipboard":
				this.options.write(osc52Sequence(effect.text));
				break;
			case "undo":
				this.undoChanges(effect.count);
				break;
			case "repeat":
				this.repeatChange(effect.count);
				break;
			case "repeat-insert":
				this.repeatInsert(effect.count);
				break;
		}
	}

	/** Types the last change again, then replays the keys of its insert session. */
	private repeatChange(count: number | null): void {
		const change = this.engineState.lastChange;
		if (change === null) return;
		const transcript = this.lastTranscript;
		if (change.insert && transcript?.repeatable !== true) {
			this.notify(NOT_REPEATABLE, "warning");
			return;
		}

		const register = change.register === null ? "" : `"${change.register}`;
		for (const key of splitGraphemes(`${register}${count ?? ""}${change.keys}`)) {
			this.stepEngine(key, key);
		}
		if (this.engineState.mode !== "insert" || transcript === null) return;

		this.transcript = transcript;
		this.replayKeys(transcript, 1);
		this.stepEngine("<Esc>", "<Esc>");
	}

	/**
	 * Finishes a counted insert: replays the session's keys `count` more times, as Vim does at
	 * Escape, and then leaves insert mode.
	 */
	private repeatInsert(count: number): void {
		const transcript = this.transcript;
		const change = this.engineState.lastChange;
		if (transcript?.repeatable === true && change !== null) {
			// Neovim opens each further line below the previous one, also for `O`
			const opensLine = change.keys === "o" || change.keys === "O";
			this.replaying++;
			try {
				if (opensLine) {
					for (let i = 0; i < count; i++) {
						this.stepEngine("<Esc>", "<Esc>");
						this.stepEngine("o", "o");
						this.replayKeys(transcript, 1);
					}
				} else {
					this.replayKeys(transcript, count);
				}
			} finally {
				this.replaying--;
			}
			this.setEngineState({ ...this.engineState, lastChange: change });
		} else {
			this.notify(NOT_REPEATABLE, "warning");
		}
		this.stepEngine("<Esc>", "<Esc>");
	}

	/**
	 * Types the session's keys again. Runs of typed text go in as one insertion, which, unlike
	 * typing, never asks for autocomplete suggestions that would stay open in normal mode.
	 */
	private replayKeys(transcript: Transcript, times: number): void {
		if (transcript.keys.length > 0) this.keepAutoIndent();
		for (let i = 0; i < times; i++) {
			let typed = "";
			for (const data of transcript.keys) {
				const text = printableText(data);
				if (text !== undefined) {
					typed += text;
					continue;
				}
				super.insertTextAtCursor(typed);
				typed = "";
				this.passToPi(data);
			}
			super.insertTextAtCursor(typed);
		}
	}

	private runPiAction(action: PiAction, data: string): void {
		switch (action) {
			case "submit":
				this.leaveBackslash();
				this.passToPi(data);
				break;
			case "up":
			case "down":
				this.passToPi(PI_ACTION_KEYS[action]);
				break;
			case "external-editor":
				this.openExternalEditor();
				break;
		}
	}

	/** Pi turns Enter after a backslash into a newline; moving to the line start avoids that. */
	private leaveBackslash(): void {
		const { line, col } = this.getCursor();
		if (col === 0 || this.getLines()[line]?.[col - 1] !== "\\") return;
		this.moveCursorTo({ line, col: 0 });
	}

	private openExternalEditor(): void {
		const open = this.actionHandlers.get("app.editor.external");
		if (open === undefined) {
			this.notify("vim-mode: no external editor action is registered", "error");
			return;
		}
		this.suspendShape();
		open();
	}

	/** Forwards a key to Pi and settles the engine around whatever Pi did with it. */
	private passToPi(data: string): void {
		const mode = this.engineState.mode;
		const before = this.snapshot();
		if (
			this.appKeys.matches(data, "app.editor.external") ||
			this.appKeys.matches(data, "app.suspend")
		) {
			this.suspendShape();
		}
		const passing = { reported: false };
		this.passing = passing;
		try {
			this.piInput(data);
		} finally {
			this.passing = null;
		}
		this.materializePaste();
		if (mode !== "normal") return;

		if (!passing.reported) this.reportExternalChange(before);
		this.cancelPending();
		this.forgetWantedColumn();
		this.clampWhenNormal();
	}

	private reportExternalChange(before: Snapshot): void {
		const after = this.snapshot();
		if (textOf(before) === textOf(after)) return;
		if (this.engineState.pending !== "") {
			this.cancelPending();
			this.notify("vim-mode: pending command cancelled, the text changed", "warning");
		}
		this.options.onExternalChange?.({ before, after });
		this.recordExternalUndo(before, after);
	}

	/** An external change is its own undo entry and ends any open insert session first. */
	private recordExternalUndo(before: Snapshot, after: Snapshot): void {
		const insert = this.insertSession !== null;
		this.closeInsertSession(before);
		this.pushUndo(before, after);
		if (insert) this.insertSession = after;
		if (this.transcript !== null) this.transcript.repeatable = false;
	}

	/**
	 * Replaces a collapsed `[paste #N]` marker with its content. The marker is the only one in
	 * the text at this point, so the cursor maps by the length of the text after it.
	 */
	private materializePaste(): void {
		const collapsed = this.getText();
		const expanded = this.getExpandedText();
		if (collapsed === expanded) return;

		const { line, col } = this.getCursor();
		const offset = this.getLines()
			.slice(0, line)
			.reduce((sum, text) => sum + text.length + 1, col);
		const target = cursorAtOffset(expanded, expanded.length - (collapsed.length - offset));
		super.setText(expanded);
		if (!this.walkTo(target)) {
			this.notify("vim-mode: could not place the cursor after a paste", "error");
		}
	}

	/** Applies a new buffer and cursor, restoring the old ones when Pi does not end up there. */
	private applyEdit(target: Snapshot): boolean {
		const before = this.snapshot();
		const text = textOf(target);
		if (text !== textOf(before)) {
			super.setText(text);
			if (this.getText() !== text) {
				this.restore(before);
				return false;
			}
		}
		if (this.walkTo(target.cursor)) return true;
		this.restore(before);
		return false;
	}

	private restore(before: Snapshot): void {
		super.setText(textOf(before));
		this.walkTo(before.cursor);
		this.notify("vim-mode: could not apply the edit, the buffer was restored", "error");
	}

	private moveCursorTo(target: Cursor): void {
		if (!this.walkTo(target)) this.notify("vim-mode: could not move the cursor", "error");
	}

	private clampWhenNormal(): void {
		if (this.engineState.mode === "normal") this.clampCursor();
	}

	/** Puts the cursor back on the last grapheme when Pi left it past the line end. */
	private clampCursor(): void {
		const { line, col } = this.getCursor();
		const target = clampNormalCol(this.getLines()[line] ?? "", col);
		if (target !== col) this.moveCursorTo({ line, col: target });
	}

	/**
	 * Moves the cursor with Pi's own keys, checking the cursor after each one.
	 *
	 * @returns Whether the cursor reached `target`.
	 */
	private walkTo(target: Cursor): boolean {
		const lines = this.getLines();
		const limit = this.getText().length + lines.length + 2;
		for (let sent = 0; sent < limit; sent++) {
			const from = this.getCursor();
			if (sameCursor(from, target)) return true;
			this.piInput(walkKey(lines, from, target));
			if (sameCursor(this.getCursor(), from)) return false;
		}
		return sameCursor(this.getCursor(), target);
	}
}
