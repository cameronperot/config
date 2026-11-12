/**
 * Terminal escape sequences the extension writes: cursor shapes (DECSCUSR).
 */

import { operatorPending } from "./operators.ts";
import type { EngineState } from "./protocol.ts";

export type CursorShape = "bar" | "block" | "underline" | "default";

const CURSOR_SHAPE_SEQUENCES: Record<CursorShape, string> = {
	bar: "\x1b[6 q",
	block: "\x1b[2 q",
	underline: "\x1b[4 q",
	default: "\x1b[0 q",
};

export function cursorShapeSequence(shape: CursorShape): string {
	return CURSOR_SHAPE_SEQUENCES[shape];
}

/**
 * Shape for the engine state: a bar while typing, a block in normal mode and an underline while
 * an operator waits for its target.
 */
export function cursorShapeFor(state: EngineState): CursorShape {
	if (state.mode === "insert") return "bar";
	return operatorPending(state.pending) ? "underline" : "block";
}

/** OSC 52 sequence that sets the system clipboard to `text`. */
export function osc52Sequence(text: string): string {
	return `\x1b]52;c;${Buffer.from(text, "utf8").toString("base64")}\x07`;
}
