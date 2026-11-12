/**
 * Engine protocol: the contract between the pure vim engine and the Pi adapter.
 *
 * The engine owns vim semantics and never touches Pi. The adapter owns the editor, feeds the
 * engine one key at a time with a snapshot of the buffer, and applies the returned effects in
 * order.
 */

/** Cursor position. `col` is a UTF-16 offset on a grapheme boundary, the unit Pi's cursor uses. */
export interface Cursor {
	readonly line: number;
	readonly col: number;
}

/** Buffer contents and cursor at one moment. */
export interface Snapshot {
	readonly lines: readonly string[];
	readonly cursor: Cursor;
}

export type Mode = "insert" | "normal";

/**
 * Preferred column of vertical motions (Vim's curswant), in display cells. It is valid only
 * while the cursor is still at `cursor`, so a cursor the engine did not place invalidates it.
 * `col` is `Infinity` after `$`, which sticks to the line end.
 */
export interface WantedColumn {
	readonly col: number;
	readonly cursor: Cursor;
}

/** A `f`, `F`, `t` or `T` search, which `;` and `,` repeat. */
export interface FindSearch {
	readonly key: "f" | "F" | "t" | "T";
	readonly char: string;
}

/**
 * Contents of the unnamed register. A linewise register holds whole lines; a characterwise one
 * holds text, where each element after the first starts after a line break.
 */
export interface Register {
	readonly lines: readonly string[];
	readonly linewise: boolean;
}

/**
 * The last change `.` repeats, as the keys that make it again: `keys` follow the count and the
 * register, and an operator change keeps its operator (`x` is `dl`, `D` is `d$`).
 */
export interface LastChange {
	readonly keys: string;
	/** Product of the typed counts, or null when none was typed. */
	readonly count: number | null;
	readonly register: "+" | null;
	/** The change ends in an insert session, whose typed keys the adapter replays. */
	readonly insert: boolean;
}

export interface EngineState {
	readonly mode: Mode;
	/** Keys of the command typed so far, in the order typed. It is shown in the border. */
	readonly pending: string;
	readonly want: WantedColumn | null;
	readonly lastFind: FindSearch | null;
	readonly register: Register | null;
	/** Line that holds an autoindent no key has followed yet; Escape clears it. */
	readonly autoIndent: number | null;
	readonly lastChange: LastChange | null;
	/** Times a counted `i a I A o O` still has to insert its text, counting the typed one. */
	readonly insertCount: number | null;
}

/** Actions that only Pi can perform. `up` and `down` are Pi's own cursor and history keys. */
export type PiAction = "submit" | "up" | "down" | "external-editor";

export type NoticeLevel = "info" | "warning" | "error";

export type Effect =
	| { readonly type: "cursor"; readonly cursor: Cursor }
	| { readonly type: "edit"; readonly snapshot: Snapshot }
	| { readonly type: "mode"; readonly mode: Mode }
	| { readonly type: "pi"; readonly action: PiAction }
	| { readonly type: "change-start"; readonly cursor: Cursor }
	| { readonly type: "undo"; readonly count: number }
	| { readonly type: "repeat"; readonly count: number | null }
	| { readonly type: "repeat-insert"; readonly count: number }
	| { readonly type: "clipboard"; readonly text: string }
	| { readonly type: "notice"; readonly level: NoticeLevel; readonly message: string };

export interface StepResult {
	readonly state: EngineState;
	readonly effects: readonly Effect[];
}

/**
 * Key vocabulary. The adapter passes the engine exactly these keys: a single printable
 * grapheme (`"x"`, `"<"`, `"👍🏽"`), `"<Esc>"` or `"<CR>"`. Chords and other special keys go to
 * Pi and never reach the engine.
 *
 * In insert mode the engine reacts only to `"<Esc>"`; every other key yields no effects, and
 * Pi handles it.
 *
 * Effects apply in order. An `edit` carries the complete new buffer and cursor. A `cursor`
 * effect leaves the text alone. A `change-start` effect precedes an `edit` and names the cursor
 * Vim's undo restores for it, when that is not the cursor before the key; the adapter consumes it
 * and never applies it. A `repeat` effect asks the adapter to type `state.lastChange` again, with
 * `count` instead of the recorded one when non-null. A `repeat-insert` effect comes from the
 * Escape of a counted insert, which keeps the mode: the adapter replays the session's typed keys
 * `count` more times, opening a line before each replay after `o` and `O`, then sends `"<Esc>"`
 * again.
 *
 * @param state - Engine state before the key.
 * @param snapshot - Buffer and cursor before the key; in normal mode the cursor is on a grapheme.
 * @param key - The key, per the vocabulary above.
 */
export type Step = (state: EngineState, snapshot: Snapshot, key: string) => StepResult;
