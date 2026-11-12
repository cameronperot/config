import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { KeybindingsManager } from "@earendil-works/pi-coding-agent";
import extension from "../index.ts";
import { VimEditor } from "../editor.ts";
import { STUB_KEYBINDINGS, STUB_THEME, createTui } from "./harness.ts";

const BAR = "\x1b[6 q";
const BLOCK = "\x1b[2 q";
const DEFAULT = "\x1b[0 q";

type Handler = (event: unknown, ctx: ExtensionContext) => void;
type Factory = NonNullable<ReturnType<ExtensionContext["ui"]["getEditorComponent"]>>;

const foreignFactory: Factory = () => {
	throw new Error("the foreign factory must not run");
};

/** Loads the extension against a fake `ExtensionAPI` and a fake context. */
function load(options: { installed?: Factory; idle?: () => boolean } = {}) {
	const handlers = new Map<string, Handler>();
	extension({
		on: (event: string, handler: Handler) => {
			handlers.set(event, handler);
			return () => {};
		},
	} as unknown as ExtensionAPI);

	let installed = options.installed;
	const installs: (Factory | undefined)[] = [];
	const notices: { message: string; level: string | undefined }[] = [];
	const writes: string[] = [];
	const ctx = {
		isIdle: options.idle ?? (() => true),
		ui: {
			getEditorComponent: () => installed,
			setEditorComponent: (factory: Factory | undefined) => {
				installs.push(factory);
				installed = factory;
			},
			notify: (message: string, level?: string) => notices.push({ message, level }),
		},
	} as unknown as ExtensionContext;

	const fire = (event: string): void => {
		const handler = handlers.get(event);
		assert.ok(handler, `no ${event} handler registered`);
		handler({ type: event }, ctx);
	};

	/** Builds the editor the way Pi does once the factory is installed. */
	const build = (): VimEditor => {
		assert.ok(installed, "no editor factory installed");
		const editor = installed(
			createTui((data) => writes.push(data)),
			STUB_THEME,
			STUB_KEYBINDINGS as unknown as KeybindingsManager,
		);
		assert.ok(editor instanceof VimEditor);
		return editor;
	};

	return {
		fire,
		build,
		notices,
		writes,
		installs,
		installed: () => installed,
		replaceEditor: (factory: Factory) => {
			installed = factory;
		},
	};
}

/** The listeners that `run` adds, found by diffing `read` before and after. */
function addedListeners<T>(read: () => T[], run: () => void): T[] {
	const before = new Set(read());
	run();
	return read().filter((listener) => !before.has(listener));
}

describe("session_start", () => {
	it("installs its own editor factory", () => {
		const loaded = load();

		loaded.fire("session_start");

		assert.equal(loaded.installs.length, 1);
		assert.equal(loaded.installed(), loaded.installs[0]);
		loaded.fire("session_shutdown");
	});

	it("refuses with an error notice when another extension owns the editor", () => {
		const listeners = {
			exit: process.listenerCount("exit"),
			cont: process.listenerCount("SIGCONT"),
		};
		const loaded = load({ installed: foreignFactory });

		loaded.fire("session_start");

		assert.equal(loaded.notices.length, 1);
		assert.equal(loaded.notices[0]?.level, "error");
		assert.deepEqual(loaded.installs, []);
		assert.equal(loaded.installed(), foreignFactory);
		assert.equal(process.listenerCount("exit"), listeners.exit);
		assert.equal(process.listenerCount("SIGCONT"), listeners.cont);

		loaded.fire("session_shutdown");
		assert.deepEqual(loaded.installs, []);
		assert.equal(loaded.installed(), foreignFactory);
	});

	it("wires notices and the terminal writer into the editor", () => {
		const loaded = load({ idle: () => false });
		loaded.fire("session_start");

		const editor = loaded.build();
		assert.deepEqual(loaded.writes, [BAR]);

		let escapes = 0;
		editor.onEscape = () => {
			escapes++;
		};
		// While a response streams, the first Escape from insert mode stays out of Pi
		editor.handleInput("\x1b");
		assert.equal(escapes, 0);

		editor.handleInput("\x1b");
		assert.equal(escapes, 1);

		editor.handleInput("v");
		editor.handleInput("v");
		assert.equal(loaded.notices[0]?.level, "error");
		loaded.fire("session_shutdown");
	});
});

describe("session_shutdown", () => {
	it("uninstalls its own factory, and a following session_start installs again", () => {
		const loaded = load();
		loaded.fire("session_start");
		const first = loaded.installed();

		loaded.fire("session_shutdown");
		assert.equal(loaded.installed(), undefined);
		assert.equal(loaded.installs.at(-1), undefined);

		loaded.fire("session_start");
		assert.ok(loaded.installed());
		assert.notEqual(loaded.installed(), first);
		loaded.fire("session_shutdown");
	});

	it("leaves a factory another extension installed after startup in place", () => {
		const loaded = load();
		loaded.fire("session_start");
		loaded.replaceEditor(foreignFactory);
		const installsBefore = loaded.installs.length;

		loaded.fire("session_shutdown");

		assert.equal(loaded.installed(), foreignFactory);
		assert.equal(loaded.installs.length, installsBefore);
	});

	it("restores the process listener counts", () => {
		const before = {
			exit: process.listenerCount("exit"),
			cont: process.listenerCount("SIGCONT"),
		};
		const loaded = load();

		loaded.fire("session_start");
		assert.equal(process.listenerCount("exit"), before.exit + 1);
		assert.equal(process.listenerCount("SIGCONT"), before.cont + 1);

		loaded.fire("session_shutdown");
		assert.equal(process.listenerCount("exit"), before.exit);
		assert.equal(process.listenerCount("SIGCONT"), before.cont);
	});

	it("writes the default cursor shape (AC4)", () => {
		const loaded = load();
		loaded.fire("session_start");
		loaded.build();
		loaded.writes.length = 0;

		loaded.fire("session_shutdown");

		assert.deepEqual(loaded.writes, [DEFAULT]);
	});
});

describe("process handlers", () => {
	it("write the default cursor shape on exit (AC4)", () => {
		const loaded = load();
		const exitListeners = addedListeners(
			() => process.listeners("exit"),
			() => loaded.fire("session_start"),
		);
		loaded.build();
		loaded.writes.length = 0;

		assert.equal(exitListeners.length, 1);
		exitListeners[0]?.(0);
		loaded.fire("session_shutdown");

		assert.deepEqual(loaded.writes.slice(0, 1), [DEFAULT]);
	});

	it("reapply the mode's shape on SIGCONT", () => {
		const loaded = load();
		const contListeners = addedListeners(
			() => process.listeners("SIGCONT"),
			() => loaded.fire("session_start"),
		);
		const editor = loaded.build();
		editor.handleInput("\x1b");
		loaded.writes.length = 0;

		assert.equal(contListeners.length, 1);
		contListeners[0]?.("SIGCONT");
		loaded.fire("session_shutdown");

		assert.equal(loaded.writes[0], BLOCK);
	});
});
