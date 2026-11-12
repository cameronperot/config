/**
 * Vim mode: replaces Pi's prompt editor with `VimEditor`.
 *
 * The extension owns the terminal cursor shape, so it gives the default shape back on shutdown
 * and on process exit, and reapplies its own after the process resumes from a suspend.
 */

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { VimEditor } from "./editor.ts";
import { cursorShapeSequence } from "./terminal.ts";

type EditorFactory = NonNullable<ReturnType<ExtensionContext["ui"]["getEditorComponent"]>>;

export default function (pi: ExtensionAPI): void {
	let factory: EditorFactory | undefined;
	let editor: VimEditor | undefined;
	let write: ((data: string) => void) | undefined;

	const resetShape = (): void => write?.(cursorShapeSequence("default"));
	const reapplyShape = (): void => editor?.reapplyCursorShape();

	pi.on("session_start", (_event, ctx) => {
		if (ctx.ui.getEditorComponent() !== undefined) {
			const message = "vim-mode: another extension owns the prompt editor, so it stays off";
			ctx.ui.notify(message, "error");
			return;
		}

		factory = (tui, theme, keybindings) => {
			write = (data) => tui.terminal.write(data);
			editor = new VimEditor(tui, theme, keybindings, {
				notify: (message, level) => ctx.ui.notify(message, level),
				write,
			});
			return editor;
		};
		ctx.ui.setEditorComponent(factory);
		process.on("exit", resetShape);
		process.on("SIGCONT", reapplyShape);
	});

	pi.on("session_shutdown", (_event, ctx) => {
		if (factory === undefined) return;

		resetShape();
		process.off("exit", resetShape);
		process.off("SIGCONT", reapplyShape);
		if (ctx.ui.getEditorComponent() === factory) ctx.ui.setEditorComponent(undefined);
		factory = undefined;
		editor = undefined;
		write = undefined;
	});
}
