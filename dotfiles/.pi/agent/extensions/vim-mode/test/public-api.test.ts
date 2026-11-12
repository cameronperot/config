import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it } from "node:test";
import ts from "typescript";

const SOURCE_DIR = join(import.meta.dirname, "..");

/** Describes every construct that reaches past Pi's public API or hides a type error. */
function violations(fileName: string, source: string): string[] {
	const file = ts.createSourceFile(fileName, source, ts.ScriptTarget.Latest, true);
	const found: string[] = [];

	function report(node: ts.Node, message: string): void {
		const { line } = file.getLineAndCharacterOfPosition(node.getStart(file));
		found.push(`${fileName}:${line + 1} ${message}`);
	}

	function visit(node: ts.Node): void {
		if (ts.isElementAccessExpression(node)) {
			const key = node.argumentExpression;
			if (
				ts.isStringLiteralLike(key) ||
				ts.isNoSubstitutionTemplateLiteral(key) ||
				ts.isTemplateExpression(key)
			) {
				report(node, "element access with a literal key");
			}
		}
		if (node.kind === ts.SyntaxKind.AnyKeyword) report(node, "the any type");
		if (ts.isAsExpression(node)) {
			let inner = node.expression;
			while (ts.isParenthesizedExpression(inner)) inner = inner.expression;
			if (
				ts.isAsExpression(inner) &&
				(inner.type.kind === ts.SyntaxKind.UnknownKeyword ||
					inner.type.kind === ts.SyntaxKind.NeverKeyword)
			) {
				report(node, "double assertion");
			}
		}
		ts.forEachChild(node, visit);
	}

	visit(file);
	return found;
}

describe("public API only (AC6)", () => {
	it("flags each forbidden construct in a fixture", () => {
		const fixtures: [string, string][] = [
			["single-quoted key", "const a = e['state'];"],
			["double-quoted key", 'const a = e["state"];'],
			["template key", "const a = e[`state`];"],
			["interpolated template key", "const a = e[`st${n}`];"],
			["any", "const a = x as any;"],
			["any annotation", "let a: any;"],
			["double assertion via unknown", "const a = x as unknown as T;"],
			["double assertion via never", "const a = x as never as T;"],
			["parenthesized double assertion", "const a = (x as unknown) as T;"],
		];
		for (const [name, source] of fixtures) {
			assert.equal(violations("fixture.ts", source).length, 1, name);
		}
	});

	it("accepts the allowed forms in a fixture", () => {
		const allowed =
			"const a = e[key]; const b = x as T; const c = list[0]; const d = x satisfies T;";
		assert.deepEqual(violations("fixture.ts", allowed), []);
	});

	it("finds no violation in the extension sources", () => {
		const files = readdirSync(SOURCE_DIR).filter((name) => name.endsWith(".ts"));
		assert.ok(files.includes("editor.ts"));

		const found = files.flatMap((name) =>
			violations(name, readFileSync(join(SOURCE_DIR, name), "utf8")),
		);

		assert.deepEqual(found, []);
	});
});
