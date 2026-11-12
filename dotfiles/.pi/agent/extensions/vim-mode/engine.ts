/**
 * Pure vim engine: key in, state and effects out. See protocol.ts for the contract.
 */

import type {
	Cursor,
	Effect,
	EngineState,
	LastChange,
	Register,
	Snapshot,
	StepResult,
	WantedColumn,
} from "./protocol.ts";
import { motionStatus, runMotion } from "./motions.ts";
import {
	applyOperator,
	joinLines,
	leadingWhite,
	openLine,
	putRegister,
	replaceChars,
	resolveRange,
	resolveTarget,
	targetStatus,
	toggleCase,
} from "./operators.ts";
import type { Edit, Operator, Range } from "./operators.ts";
import {
	clampNormalCol,
	colAtDisplay,
	displayCol,
	graphemeStarts,
	lastGraphemeStart,
	nextBoundary,
	prevBoundary,
} from "./text.ts";

const MAX_COUNT = 999_999_999;
// Upper bound on the characters one put inserts; a larger one would exhaust memory
const MAX_PUT_SIZE = 10_000_000;

export const initialState: EngineState = {
	mode: "insert",
	pending: "",
	want: null,
	lastFind: null,
	register: null,
	autoIndent: null,
	lastChange: null,
	insertCount: null,
};

interface Command {
	/** Product of the counts typed before the command, or null when none was typed. */
	count: number | null;
	/** Register typed with `"`, or null. */
	register: string | null;
	/** Keys after the count and register. */
	keys: string;
}

/** Splits pending keys into count, register and command keys; null while a `"` waits. */
function parsePending(pending: string): Command | null {
	let count: number | null = null;
	let register: string | null = null;
	let index = 0;
	for (;;) {
		const digits = /^[1-9][0-9]*/.exec(pending.slice(index))?.[0];
		if (digits !== undefined) {
			count = Math.min((count ?? 1) * Number(digits), MAX_COUNT);
			index += digits.length;
		} else if (pending[index] === '"') {
			const [name] = pending.slice(index + 1);
			if (name === undefined) return null;
			register = name;
			index += 1 + name.length;
		} else {
			return { count, register, keys: pending.slice(index) };
		}
	}
}

function done(
	state: EngineState,
	effects: readonly Effect[],
	want: WantedColumn | null = null,
): StepResult {
	return { state: { ...state, pending: "", want }, effects };
}

function moveTo(snapshot: Snapshot, cursor: Cursor): readonly Effect[] {
	const { line, col } = snapshot.cursor;
	return cursor.line === line && cursor.col === col ? [] : [{ type: "cursor", cursor }];
}

function leaveInsert(state: EngineState, snapshot: Snapshot): StepResult {
	const { line, col } = snapshot.cursor;
	const text = snapshot.lines[line] ?? "";
	const next = {
		...state,
		mode: "normal" as const,
		pending: "",
		want: null,
		autoIndent: null,
		insertCount: null,
	};
	if (state.autoIndent === line && /^[ \t]+$/.test(text)) {
		// An autoindent that nothing followed is removed
		const lines = snapshot.lines.with(line, "");
		const cursor = { line, col: 0 };
		const edit: Effect = { type: "edit", snapshot: { lines, cursor } };
		// Neovim keeps the column the indent reached as the wanted column
		const want = { col: displayCol(text, text.length), cursor };
		return { state: { ...next, want }, effects: [{ type: "mode", mode: "normal" }, edit] };
	}
	const cursor = { line, col: prevBoundary(text, col) };
	const effects: Effect[] = [{ type: "mode", mode: "normal" }, ...moveTo(snapshot, cursor)];
	return { state: next, effects };
}

function moveHorizontal(
	state: EngineState,
	snapshot: Snapshot,
	count: number,
	direction: "left" | "right",
): StepResult {
	const { line, col } = snapshot.cursor;
	const text = snapshot.lines[line] ?? "";
	const limit = lastGraphemeStart(text);
	let target = col;
	for (let i = 0; i < count; i++) {
		if (direction === "left" ? target === 0 : target >= limit) break;
		target = direction === "left" ? prevBoundary(text, target) : nextBoundary(text, target);
	}
	const want = target === col ? state.want : null;
	return done(state, moveTo(snapshot, { line, col: target }), want);
}

/** Display column vertical motions aim for: the stored one while the cursor is where it left it. */
function wantedColumn(state: EngineState, snapshot: Snapshot): number {
	const { line, col } = snapshot.cursor;
	if (state.want?.cursor.line === line && state.want.cursor.col === col) return state.want.col;
	return displayCol(snapshot.lines[line] ?? "", col);
}

function moveVertical(
	state: EngineState,
	snapshot: Snapshot,
	count: number,
	direction: "up" | "down",
): StepResult {
	const { line, col } = snapshot.cursor;
	const lastLine = snapshot.lines.length - 1;
	const targetLine =
		direction === "up" ? Math.max(line - count, 0) : Math.min(line + count, lastLine);
	if (targetLine === line) return done(state, [], state.want);

	const want = wantedColumn(state, snapshot);
	const cursor = { line: targetLine, col: colAtDisplay(snapshot.lines[targetLine] ?? "", want) };
	return done(state, [{ type: "cursor", cursor }], { col: want, cursor });
}

function moveByMotion(
	state: EngineState,
	snapshot: Snapshot,
	keys: string,
	count: number | null,
): StepResult {
	const wantedCol = wantedColumn(state, snapshot);
	const result = runMotion(keys, {
		lines: snapshot.lines,
		cursor: snapshot.cursor,
		count,
		wantedCol,
		lastFind: state.lastFind,
	});
	let want: WantedColumn | null = null;
	if (result.want === "keep") want = { col: wantedCol, cursor: result.cursor };
	if (result.want === "end") want = { col: Infinity, cursor: result.cursor };
	const next = { ...state, pending: "", want, lastFind: result.lastFind ?? state.lastFind };
	return { state: next, effects: moveTo(snapshot, result.cursor) };
}

function sameLines(a: readonly string[], b: readonly string[]): boolean {
	return a.length === b.length && a.every((text, index) => text === b[index]);
}

/** An edit effect when the text changed, otherwise only the cursor move, if any. */
function editEffects(snapshot: Snapshot, edit: Edit): readonly Effect[] {
	if (sameLines(edit.lines, snapshot.lines)) return moveTo(snapshot, edit.cursor);
	return [{ type: "edit", snapshot: edit }];
}

function enterInsert(
	state: EngineState,
	snapshot: Snapshot,
	edit: Edit,
	autoIndent: number | null = null,
	insertCount: number | null = null,
): StepResult {
	const effects: Effect[] = [{ type: "mode", mode: "insert" }, ...editEffects(snapshot, edit)];
	const next = { ...state, mode: "insert" as const, pending: "", want: null };
	return { state: { ...next, autoIndent, insertCount }, effects };
}

const REGISTER_COMMANDS = "dcyxXDCYsSpP";

/** Commands that stand for an operator and a target. */
const OPERATOR_SHORTHANDS: Readonly<Record<string, readonly [Operator, string]>> = {
	x: ["d", "l"],
	X: ["d", "h"],
	D: ["d", "$"],
	C: ["c", "$"],
	Y: ["y", "$"],
	s: ["c", "l"],
	S: ["c", "c"],
};

const CLIPBOARD_READ_NOTICE: Effect = {
	type: "notice",
	level: "warning",
	message: "vim-mode: reading the clipboard is not available, paste with the terminal instead",
};

const PUT_TOO_LARGE_NOTICE: Effect = {
	type: "notice",
	level: "warning",
	message: "vim-mode: the put is too large, nothing was put",
};

function clipboardEffects(register: Register | null, clipboard: boolean): readonly Effect[] {
	if (!clipboard || register === null) return [];
	const text = register.lines.join("\n") + (register.linewise ? "\n" : "");
	return text === "" ? [] : [{ type: "clipboard", text }];
}

const utf8 = new TextEncoder();

/**
 * Column of the grapheme that holds UTF-8 byte `offset` of `text`. Neovim saves the cursor
 * column as a byte offset, so a column carried to a line with wider characters lands on the
 * character that contains that byte.
 */
function colAtByte(text: string, offset: number): number {
	let col = 0;
	let bytes = 0;
	for (const start of graphemeStarts(text)) {
		bytes += utf8.encode(text.slice(col, start)).length;
		if (bytes > offset) break;
		col = start;
	}
	return col;
}

/**
 * Cursor Neovim's undo returns to after an operator: the start of the range. A linewise change
 * differs. One line returns to the cursor column, but no further right than its indent. Several
 * lines return to the second line at the byte column of the range start, because Neovim saves
 * the lines below the first before the first itself.
 */
function operatorUndoCursor(lines: readonly string[], range: Range, operator: Operator): Cursor {
	const { start, end } = range;
	if (operator !== "c" || !range.linewise) return start;

	const text = lines[start.line] ?? "";
	if (end.line === start.line) {
		const col = Math.min(start.col, leadingWhite(text));
		return { line: start.line, col: clampNormalCol(text, col) };
	}
	const below = lines[start.line + 1] ?? "";
	const offset = utf8.encode(text.slice(0, start.col)).length;
	return { line: start.line + 1, col: colAtByte(below, offset) };
}

function runOperator(
	state: EngineState,
	snapshot: Snapshot,
	operator: Operator,
	keys: string,
	count: number | null,
	clipboard: boolean,
): StepResult {
	const wantedCol = wantedColumn(state, snapshot);
	const target = resolveTarget(operator, keys, {
		lines: snapshot.lines,
		cursor: snapshot.cursor,
		count,
		wantedCol,
		lastFind: state.lastFind,
	});
	const lastFind = target?.lastFind ?? state.lastFind;
	if (target === null) return done({ ...state, lastFind }, [], state.want);
	if (target.failed) {
		// A failed motion cancels the operator but leaves the cursor where the motion stopped
		const { line, col } = target.to;
		const cursor = { line, col: clampNormalCol(snapshot.lines[line] ?? "", col) };
		const effects = moveTo(snapshot, cursor);
		let want = effects.length === 0 ? state.want : null;
		if (target.pinned) want = { col: Infinity, cursor };
		return done({ ...state, lastFind }, effects, want);
	}

	const range = target.takesBreak
		? {
				start: target.from,
				end: target.to,
				inclusive: false,
				linewise: false,
				endAdjusted: false,
				literal: true,
			}
		: resolveRange(snapshot.lines, target.from, target.to, target.kind);
	const result = applyOperator(operator, snapshot.lines, range, wantedCol);
	const lastChange =
		operator === "y"
			? state.lastChange
			: {
					keys: operator + keys,
					count,
					register: clipboard ? ("+" as const) : null,
					insert: operator === "c",
				};
	const next = { ...state, lastFind, register: result.register ?? state.register, lastChange };
	const edit = { lines: result.lines, cursor: result.cursor };
	const yanked = clipboardEffects(result.register, clipboard);
	const undoCursor = operatorUndoCursor(snapshot.lines, range, operator);
	if (result.insert) {
		// The change starts at the operator even when it left the text alone
		const entered = enterInsert(next, snapshot, edit, result.autoIndent);
		const origin: Effect = { type: "change-start", cursor: undoCursor };
		return { ...entered, effects: [origin, ...entered.effects, ...yanked] };
	}

	const edits = editEffects(snapshot, edit);
	const { line, col } = snapshot.cursor;
	const moved = undoCursor.line !== line || undoCursor.col !== col;
	const origin: readonly Effect[] =
		moved && edits.some(({ type }) => type === "edit")
			? [{ type: "change-start", cursor: undoCursor }]
			: [];
	return done(next, [...origin, ...edits, ...yanked]);
}

/** Combines the counts before an operator and before its target. */
function multiplyCounts(first: number | null, second: number | null): number | null {
	if (first === null) return second;
	if (second === null) return first;
	return Math.min(first * second, MAX_COUNT);
}

function operatorStep(
	state: EngineState,
	snapshot: Snapshot,
	command: Command,
	pending: string,
	operator: Operator,
	rest: string,
): StepResult {
	const [, digits, keys = ""] = /^([1-9][0-9]*)?([\s\S]*)$/u.exec(rest) ?? [];
	if (keys === "") return { state: { ...state, pending }, effects: [] };

	const status = targetStatus(operator, keys);
	if (status === "none") return done(state, []);
	if (status === "prefix") return { state: { ...state, pending }, effects: [] };

	const typed = digits === undefined ? null : Math.min(Number(digits), MAX_COUNT);
	const count = multiplyCounts(command.count, typed);
	return runOperator(state, snapshot, operator, keys, count, command.register === "+");
}

function put(
	state: EngineState,
	snapshot: Snapshot,
	count: number | null,
	before: boolean,
	clipboard: boolean,
): StepResult {
	if (clipboard) return done(state, [CLIPBOARD_READ_NOTICE], state.want);
	if (state.register === null) return done(state, [], state.want);
	const copySize = state.register.lines.join("\n").length + (state.register.linewise ? 1 : 0);
	if (copySize * (count ?? 1) > MAX_PUT_SIZE) {
		return done(state, [PUT_TOO_LARGE_NOTICE], state.want);
	}
	const edit = putRegister(snapshot.lines, snapshot.cursor, state.register, count ?? 1, before);
	const keys = before ? "P" : "p";
	const lastChange = { keys, count, register: null, insert: false };
	return done({ ...state, lastChange }, editEffects(snapshot, edit));
}

/** A change made of one edit: `J`, `~` or `r`. A null edit changes nothing and is not recorded. */
function lineEdit(
	state: EngineState,
	snapshot: Snapshot,
	edit: Edit | null,
	change: Pick<LastChange, "keys" | "count">,
): StepResult {
	if (edit === null) return done(state, []);
	const lastChange = { ...change, register: null, insert: false };
	return done({ ...state, lastChange }, editEffects(snapshot, edit));
}

function insertEntry(
	state: EngineState,
	snapshot: Snapshot,
	key: string,
	count: number | null,
): StepResult {
	const { line, col } = snapshot.cursor;
	const text = snapshot.lines[line] ?? "";
	const lastChange = { keys: key, count, register: null, insert: true };
	const next = { ...state, lastChange };
	const insertCount = count !== null && count > 1 ? count : null;
	switch (key) {
		case "i":
			return enterInsert(
				next,
				snapshot,
				{ lines: snapshot.lines, cursor: snapshot.cursor },
				null,
				insertCount,
			);
		case "a": {
			const cursor = { line, col: text === "" ? 0 : nextBoundary(text, col) };
			return enterInsert(next, snapshot, { lines: snapshot.lines, cursor }, null, insertCount);
		}
		case "I": {
			const cursor = { line, col: leadingWhite(text) };
			return enterInsert(next, snapshot, { lines: snapshot.lines, cursor }, null, insertCount);
		}
		case "A": {
			const cursor = { line, col: text.length };
			return enterInsert(next, snapshot, { lines: snapshot.lines, cursor }, null, insertCount);
		}
		default: {
			const opened = openLine(snapshot.lines, line, key === "o");
			return enterInsert(next, snapshot, opened, opened.autoIndent, insertCount);
		}
	}
}

function normalStep(state: EngineState, snapshot: Snapshot, key: string): StepResult {
	if (key === "<Esc>") return done(state, [], state.want);
	if (key === "<CR>") return done(state, [{ type: "pi", action: "submit" }]);

	const pending = state.pending + key;
	const waiting = { state: { ...state, pending }, effects: [] };
	const command = parsePending(pending);
	if (command === null) return waiting;

	const { count, register, keys } = command;
	// Only `"+` is supported, and only before commands that read or write a register
	if (register !== null && register !== "+") return done(state, []);
	// A leading `0` is a command, not a count digit, so it leaves `keys` non-empty
	if (keys === "") return waiting;
	if (register !== null && !REGISTER_COMMANDS.includes(keys[0] ?? "")) return done(state, []);
	if (keys === "v") return waiting;
	if (keys === "vv") return done(state, [{ type: "pi", action: "external-editor" }]);

	const [first = ""] = keys;
	if (first === "d" || first === "c" || first === "y") {
		return operatorStep(state, snapshot, command, pending, first, keys.slice(1));
	}
	const shorthand = OPERATOR_SHORTHANDS[keys];
	if (shorthand !== undefined) {
		const [operator, target] = shorthand;
		return runOperator(state, snapshot, operator, target, count, register === "+");
	}

	const status = motionStatus(keys);
	if (status === "prefix") return waiting;
	if (status === "complete") return moveByMotion(state, snapshot, keys, count);

	const n = count ?? 1;
	switch (first) {
		case "h":
			return moveHorizontal(state, snapshot, n, "left");
		case "l":
			return moveHorizontal(state, snapshot, n, "right");
		case "j":
		case "k": {
			const direction = first === "j" ? "down" : "up";
			if (count === null) return done(state, [{ type: "pi", action: direction }], state.want);
			return moveVertical(state, snapshot, n, direction);
		}
		case "u":
			return done(state, [{ type: "undo", count: n }]);
		case ".": {
			const repeated = count ?? state.lastChange?.count ?? null;
			return done(state, state.lastChange === null ? [] : [{ type: "repeat", count: repeated }]);
		}
		case "p":
		case "P":
			return put(state, snapshot, count, first === "P", register === "+");
		case "J":
			return lineEdit(state, snapshot, joinLines(snapshot.lines, snapshot.cursor.line, count), {
				keys,
				count,
			});
		case "~":
			return lineEdit(state, snapshot, toggleCase(snapshot.lines, snapshot.cursor, count), {
				keys,
				count,
			});
		case "r": {
			if (keys === "r") return waiting;
			const edit = replaceChars(snapshot.lines, snapshot.cursor, keys.slice(1), count);
			return lineEdit(state, snapshot, edit, { keys, count });
		}
		case "i":
		case "a":
		case "I":
		case "A":
		case "o":
		case "O":
			return insertEntry(state, snapshot, first, count);
		default:
			// Unmapped keys, and a pending `v` followed by anything but `v`, cancel
			return done(state, []);
	}
}

export function step(state: EngineState, snapshot: Snapshot, key: string): StepResult {
	if (state.mode === "insert") {
		if (key !== "<Esc>") return { state, effects: [] };
		if (state.insertCount === null) return leaveInsert(state, snapshot);
		// The adapter replays the typed keys, then sends the Escape that leaves insert mode
		const repeat: Effect = { type: "repeat-insert", count: state.insertCount - 1 };
		return { state: { ...state, insertCount: null }, effects: [repeat] };
	}
	return normalStep(state, snapshot, key);
}
