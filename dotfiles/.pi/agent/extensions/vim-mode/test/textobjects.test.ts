import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Cursor } from "../protocol.ts";
import { nextBoundary, prevBoundary } from "../text.ts";
import { runMotion } from "../motions.ts";
import { selectTextObject, type TextRange } from "../textobjects.ts";
import { parseBuffer } from "./harness.ts";
import { runCase, selectRange } from "./oracle.ts";

const THUMB = "👍🏽";

interface ObjectCase {
	name: string;
	/** Buffer before the keys; `|` marks the cursor. */
	buffer: string;
	/** The object keys without the count, e.g. `iw` or `a"`. */
	object: string;
	count?: number;
	/** The range marked with `«` and `»` in the buffer text, or null when there is no object. */
	expect: string | null;
}

/** Every object the extension supports. Each one needs a case. */
const OBJECTS = [
	...["iw", "aw", "iW", "aW", 'i"', 'a"', "i'", "a'", "i`", "a`"],
	...["i(", "a(", "i)", "a)", "ib", "ab", "i[", "a[", "i]", "a]"],
	...["i{", "a{", "i}", "a}", "iB", "aB", "i<", "a<", "i>", "a>"],
];

const CASES: readonly ObjectCase[] = [
	{
		name: "iw selects the word under the cursor",
		buffer: "foo |bar baz",
		object: "iw",
		expect: "foo «bar» baz",
	},
	{ name: "iw from the first letter", buffer: "|foo bar", object: "iw", expect: "«foo» bar" },
	{ name: "iw from the last letter", buffer: "fo|o bar", object: "iw", expect: "«foo» bar" },
	{
		name: "iw selects the blanks between words",
		buffer: "foo|   bar",
		object: "iw",
		expect: "foo«   »bar",
	},
	{ name: "iw selects a punctuation run", buffer: "a|..b", object: "iw", expect: "a«..»b" },
	{ name: "iw selects a one-character word", buffer: "a |b c", object: "iw", expect: "a «b» c" },
	{ name: "iw selects indent", buffer: "|  foo", object: "iw", expect: "«  »foo" },
	{
		name: "iw stops at the line end",
		buffer: "foo |bar\nbaz",
		object: "iw",
		expect: "foo «bar»\nbaz",
	},
	{
		name: "iw selects é as part of a word",
		buffer: "|café bar",
		object: "iw",
		expect: "«café» bar",
	},
	{
		name: "iw selects a CJK run apart from Latin",
		buffer: "ab|漢字ひ",
		object: "iw",
		expect: "ab«漢字»ひ",
	},
	{
		name: "iw selects an emoji apart from letters",
		buffer: `a|${THUMB}b`,
		object: "iw",
		expect: `a«${THUMB}»b`,
	},
	{
		name: "2iw adds the blanks after the word",
		buffer: "|foo bar baz",
		object: "iw",
		count: 2,
		expect: "«foo »bar baz",
	},
	{
		name: "3iw selects two words and the blanks between",
		buffer: "|foo bar baz",
		object: "iw",
		count: 3,
		expect: "«foo bar» baz",
	},
	{
		name: "2iw from blanks selects the blanks and a word",
		buffer: "foo| bar baz",
		object: "iw",
		count: 2,
		expect: "foo« bar» baz",
	},
	{
		name: "3iw crosses lines",
		buffer: "fo|o\nbar baz",
		object: "iw",
		count: 3,
		expect: "«foo\nbar »baz",
	},
	{ name: "iw on an empty line", buffer: "a\n|\nb", object: "iw", expect: "a\n«»\nb" },
	{
		name: "aw selects the word and the blanks after it",
		buffer: "foo |bar baz",
		object: "aw",
		expect: "foo «bar »baz",
	},
	{
		name: "aw at the last word takes the blanks before it",
		buffer: "foo |bar",
		object: "aw",
		expect: "foo« bar»",
	},
	{
		name: "aw from blanks selects them and the next word",
		buffer: "foo| bar baz",
		object: "aw",
		expect: "foo« bar» baz",
	},
	{
		name: "aw selects a punctuation run and the blanks after it",
		buffer: "a|.. b",
		object: "aw",
		expect: "a«.. »b",
	},
	{ name: "aw at the line start", buffer: "|foo bar", object: "aw", expect: "«foo »bar" },
	{ name: "aw on the only word", buffer: "|foo", object: "aw", expect: "«foo»" },
	{ name: "aw keeps the indent", buffer: "  fo|o", object: "aw", expect: "  «foo»" },
	{
		name: "aw takes an emoji and the blanks after it",
		buffer: `a |${THUMB} b`,
		object: "aw",
		expect: `a «${THUMB} »b`,
	},
	{
		name: "2aw selects two words",
		buffer: "|a b c d",
		object: "aw",
		count: 2,
		expect: "«a b »c d",
	},
	{
		name: "2aw on the last words takes the blanks before them",
		buffer: "a b |c d",
		object: "aw",
		count: 2,
		expect: "a b« c d»",
	},
	{
		name: "aw takes the blanks before the last word on the line",
		buffer: "foo |bar\nbaz",
		object: "aw",
		expect: "foo« bar»\nbaz",
	},
	{
		name: "iW selects a whole run of non-blanks",
		buffer: "foo |bar.baz qux",
		object: "iW",
		expect: "foo «bar.baz» qux",
	},
	{
		name: "aW selects the run and the blanks after it",
		buffer: "foo |bar.baz qux",
		object: "aW",
		expect: "foo «bar.baz »qux",
	},
	{
		name: "2iW selects a run and the blanks after it",
		buffer: "|a.b c.d",
		object: "iW",
		count: 2,
		expect: "«a.b »c.d",
	},
	{
		name: "2aW selects two runs",
		buffer: "|a.b c.d e.f",
		object: "aW",
		count: 2,
		expect: "«a.b c.d »e.f",
	},
	{
		name: "aW selects a CJK and Latin run",
		buffer: "|ab漢字 x",
		object: "aW",
		expect: "«ab漢字 »x",
	},
	{
		name: "i\" selects inside double quotes",
		buffer: "say \"he|llo\" now",
		object: "i\"",
		expect: "say \"«hello»\" now",
	},
	{
		name: "i\" finds double quotes after the cursor",
		buffer: "|say \"hello\" now",
		object: "i\"",
		expect: "say \"«hello»\" now",
	},
	{
		name: "i\" on the opening quote of double quotes",
		buffer: "say |\"hello\" now",
		object: "i\"",
		expect: "say \"«hello»\" now",
	},
	{
		name: "i\" on the closing quote of double quotes",
		buffer: "say \"hello|\" now",
		object: "i\"",
		expect: "say \"«hello»\" now",
	},
	{
		name: "a\" takes the blanks after double quotes",
		buffer: "say \"he|llo\" now",
		object: "a\"",
		expect: "say «\"hello\" »now",
	},
	{
		name: "a\" takes the blanks before double quotes at the line end",
		buffer: "say \"he|llo\"",
		object: "a\"",
		expect: "say« \"hello\"»",
	},
	{
		name: "a\" without blanks around double quotes",
		buffer: "(\"he|llo\")",
		object: "a\"",
		expect: "(«\"hello\"»)",
	},
	{
		name: "2i\" includes double quotes",
		buffer: "say \"he|llo\" now",
		object: "i\"",
		count: 2,
		expect: "say «\"hello\"» now",
	},
	{
		name: "i\" on empty double quotes",
		buffer: "say \"|\" now",
		object: "i\"",
		expect: "say \"«»\" now",
	},
	{ name: "i\" without double quotes fails", buffer: "foo |bar", object: "i\"", expect: null },
	{
		name: "i\" with one double quotes fails",
		buffer: "say \"he|llo",
		object: "i\"",
		expect: null,
	},
	{
		name: "i' selects inside single quotes",
		buffer: "say 'he|llo' now",
		object: "i'",
		expect: "say '«hello»' now",
	},
	{
		name: "i' finds single quotes after the cursor",
		buffer: "|say 'hello' now",
		object: "i'",
		expect: "say '«hello»' now",
	},
	{
		name: "i' on the opening quote of single quotes",
		buffer: "say |'hello' now",
		object: "i'",
		expect: "say '«hello»' now",
	},
	{
		name: "i' on the closing quote of single quotes",
		buffer: "say 'hello|' now",
		object: "i'",
		expect: "say '«hello»' now",
	},
	{
		name: "a' takes the blanks after single quotes",
		buffer: "say 'he|llo' now",
		object: "a'",
		expect: "say «'hello' »now",
	},
	{
		name: "a' takes the blanks before single quotes at the line end",
		buffer: "say 'he|llo'",
		object: "a'",
		expect: "say« 'hello'»",
	},
	{
		name: "a' without blanks around single quotes",
		buffer: "('he|llo')",
		object: "a'",
		expect: "(«'hello'»)",
	},
	{
		name: "2i' includes single quotes",
		buffer: "say 'he|llo' now",
		object: "i'",
		count: 2,
		expect: "say «'hello'» now",
	},
	{
		name: "i' on empty single quotes",
		buffer: "say '|' now",
		object: "i'",
		expect: "say '«»' now",
	},
	{ name: "i' without single quotes fails", buffer: "foo |bar", object: "i'", expect: null },
	{ name: "i' with one single quotes fails", buffer: "say 'he|llo", object: "i'", expect: null },
	{
		name: "i` selects inside backticks",
		buffer: "say `he|llo` now",
		object: "i`",
		expect: "say `«hello»` now",
	},
	{
		name: "i` finds backticks after the cursor",
		buffer: "|say `hello` now",
		object: "i`",
		expect: "say `«hello»` now",
	},
	{
		name: "i` on the opening quote of backticks",
		buffer: "say |`hello` now",
		object: "i`",
		expect: "say `«hello»` now",
	},
	{
		name: "i` on the closing quote of backticks",
		buffer: "say `hello|` now",
		object: "i`",
		expect: "say `«hello»` now",
	},
	{
		name: "a` takes the blanks after backticks",
		buffer: "say `he|llo` now",
		object: "a`",
		expect: "say «`hello` »now",
	},
	{
		name: "a` takes the blanks before backticks at the line end",
		buffer: "say `he|llo`",
		object: "a`",
		expect: "say« `hello`»",
	},
	{
		name: "a` without blanks around backticks",
		buffer: "(`he|llo`)",
		object: "a`",
		expect: "(«`hello`»)",
	},
	{
		name: "2i` includes backticks",
		buffer: "say `he|llo` now",
		object: "i`",
		count: 2,
		expect: "say «`hello`» now",
	},
	{ name: "i` on empty backticks", buffer: "say `|` now", object: "i`", expect: "say `«»` now" },
	{ name: "i` without backticks fails", buffer: "foo |bar", object: "i`", expect: null },
	{ name: "i` with one backticks fails", buffer: "say `he|llo", object: "i`", expect: null },
	{
		name: "i\" skips an escaped quote",
		buffer: "a \"b\\\"c| d\" e",
		object: "i\"",
		expect: "a \"«b\\\"c d»\" e",
	},
	{
		name: "i\" pairs quotes from the line start",
		buffer: "\"a\" |b \"c\"",
		object: "i\"",
		expect: "\"a\"« b »\"c\"",
	},
	{
		name: "i\" on the second string's opening quote",
		buffer: "\"a\" |\"c\"",
		object: "i\"",
		expect: "\"a\" \"«c»\"",
	},
	{
		name: "i\" keeps an emoji inside",
		buffer: `x "a|${THUMB}b" y`,
		object: "i\"",
		expect: `x "«a${THUMB}b»" y`,
	},
	{
		name: "i\" ignores other quote kinds",
		buffer: "say \"it's| ok\" now",
		object: "i\"",
		expect: "say \"«it's ok»\" now",
	},
	{
		name: "i' ignores double quotes and apostrophes before the string",
		buffer: "say \"it's\" 'a|b'",
		object: "i'",
		expect: "say \"it's\" '«ab»'",
	},
	{
		name: "i( selects inside the pair",
		buffer: "foo (b|ar) baz",
		object: "i(",
		expect: "foo («bar») baz",
	},
	{
		name: "a( selects the pair",
		buffer: "foo (b|ar) baz",
		object: "a(",
		expect: "foo «(bar)» baz",
	},
	{
		name: "i( on the opening bracket",
		buffer: "foo |(bar) baz",
		object: "i(",
		expect: "foo («bar») baz",
	},
	{
		name: "i( on the closing bracket",
		buffer: "foo (bar|) baz",
		object: "i(",
		expect: "foo («bar») baz",
	},
	{
		name: "i( finds the next pair on the line",
		buffer: "|foo (bar) baz",
		object: "i(",
		expect: "foo («bar») baz",
	},
	{ name: "i( without a pair fails", buffer: "|foo bar", object: "i(", expect: null },
	{ name: "i( with an unclosed bracket fails", buffer: "foo (ba|r", object: "i(", expect: null },
	{ name: "i( on an empty pair", buffer: "x (|)", object: "i(", expect: "x («»)" },
	{
		name: "2i( selects the enclosing pair",
		buffer: "(a (b|) c)",
		object: "i(",
		count: 2,
		expect: "(«a (b) c»)",
	},
	{
		name: "2a( selects the enclosing pair with its brackets",
		buffer: "(a (b|) c)",
		object: "a(",
		count: 2,
		expect: "«(a (b) c)»",
	},
	{
		name: "i( picks the inner of nested pairs",
		buffer: "(a (b|) c)",
		object: "i(",
		expect: "(a («b») c)",
	},
	{
		name: "i( fails when the count exceeds the nesting",
		buffer: "(a|)",
		object: "i(",
		count: 2,
		expect: null,
	},
	{
		name: "i( keeps an emoji inside",
		buffer: `(a|${THUMB}b)`,
		object: "i(",
		expect: `(«a${THUMB}b»)`,
	},
	{
		name: "i[ selects inside the pair",
		buffer: "foo [b|ar] baz",
		object: "i[",
		expect: "foo [«bar»] baz",
	},
	{
		name: "a[ selects the pair",
		buffer: "foo [b|ar] baz",
		object: "a[",
		expect: "foo «[bar]» baz",
	},
	{
		name: "i[ on the opening bracket",
		buffer: "foo |[bar] baz",
		object: "i[",
		expect: "foo [«bar»] baz",
	},
	{
		name: "i[ on the closing bracket",
		buffer: "foo [bar|] baz",
		object: "i[",
		expect: "foo [«bar»] baz",
	},
	{
		name: "i[ finds the next pair on the line",
		buffer: "|foo [bar] baz",
		object: "i[",
		expect: "foo [«bar»] baz",
	},
	{ name: "i[ without a pair fails", buffer: "|foo bar", object: "i[", expect: null },
	{ name: "i[ with an unclosed bracket fails", buffer: "foo [ba|r", object: "i[", expect: null },
	{ name: "i[ on an empty pair", buffer: "x [|]", object: "i[", expect: "x [«»]" },
	{
		name: "2i[ selects the enclosing pair",
		buffer: "[a [b|] c]",
		object: "i[",
		count: 2,
		expect: "[«a [b] c»]",
	},
	{
		name: "2a[ selects the enclosing pair with its brackets",
		buffer: "[a [b|] c]",
		object: "a[",
		count: 2,
		expect: "«[a [b] c]»",
	},
	{
		name: "i[ picks the inner of nested pairs",
		buffer: "[a [b|] c]",
		object: "i[",
		expect: "[a [«b»] c]",
	},
	{
		name: "i[ fails when the count exceeds the nesting",
		buffer: "[a|]",
		object: "i[",
		count: 2,
		expect: null,
	},
	{
		name: "i[ keeps an emoji inside",
		buffer: `[a|${THUMB}b]`,
		object: "i[",
		expect: `[«a${THUMB}b»]`,
	},
	{
		name: "i{ selects inside the pair",
		buffer: "foo {b|ar} baz",
		object: "i{",
		expect: "foo {«bar»} baz",
	},
	{
		name: "a{ selects the pair",
		buffer: "foo {b|ar} baz",
		object: "a{",
		expect: "foo «{bar}» baz",
	},
	{
		name: "i{ on the opening bracket",
		buffer: "foo |{bar} baz",
		object: "i{",
		expect: "foo {«bar»} baz",
	},
	{
		name: "i{ on the closing bracket",
		buffer: "foo {bar|} baz",
		object: "i{",
		expect: "foo {«bar»} baz",
	},
	{
		name: "i{ finds the next pair on the line",
		buffer: "|foo {bar} baz",
		object: "i{",
		expect: "foo {«bar»} baz",
	},
	{ name: "i{ without a pair fails", buffer: "|foo bar", object: "i{", expect: null },
	{ name: "i{ with an unclosed bracket fails", buffer: "foo {ba|r", object: "i{", expect: null },
	{ name: "i{ on an empty pair", buffer: "x {|}", object: "i{", expect: "x {«»}" },
	{
		name: "2i{ selects the enclosing pair",
		buffer: "{a {b|} c}",
		object: "i{",
		count: 2,
		expect: "{«a {b} c»}",
	},
	{
		name: "2a{ selects the enclosing pair with its brackets",
		buffer: "{a {b|} c}",
		object: "a{",
		count: 2,
		expect: "«{a {b} c}»",
	},
	{
		name: "i{ picks the inner of nested pairs",
		buffer: "{a {b|} c}",
		object: "i{",
		expect: "{a {«b»} c}",
	},
	{
		name: "i{ fails when the count exceeds the nesting",
		buffer: "{a|}",
		object: "i{",
		count: 2,
		expect: null,
	},
	{
		name: "i{ keeps an emoji inside",
		buffer: `{a|${THUMB}b}`,
		object: "i{",
		expect: `{«a${THUMB}b»}`,
	},
	{
		name: "i< selects inside the pair",
		buffer: "foo <b|ar> baz",
		object: "i<",
		expect: "foo <«bar»> baz",
	},
	{
		name: "a< selects the pair",
		buffer: "foo <b|ar> baz",
		object: "a<",
		expect: "foo «<bar>» baz",
	},
	{
		name: "i< on the opening bracket",
		buffer: "foo |<bar> baz",
		object: "i<",
		expect: "foo <«bar»> baz",
	},
	{
		name: "i< on the closing bracket",
		buffer: "foo <bar|> baz",
		object: "i<",
		expect: "foo <«bar»> baz",
	},
	{
		name: "i< finds the next pair on the line",
		buffer: "|foo <bar> baz",
		object: "i<",
		expect: "foo <«bar»> baz",
	},
	{ name: "i< without a pair fails", buffer: "|foo bar", object: "i<", expect: null },
	{ name: "i< with an unclosed bracket fails", buffer: "foo <ba|r", object: "i<", expect: null },
	{ name: "i< on an empty pair", buffer: "x <|>", object: "i<", expect: "x <«»>" },
	{
		name: "2i< selects the enclosing pair",
		buffer: "<a <b|> c>",
		object: "i<",
		count: 2,
		expect: "<«a <b> c»>",
	},
	{
		name: "2a< selects the enclosing pair with its brackets",
		buffer: "<a <b|> c>",
		object: "a<",
		count: 2,
		expect: "«<a <b> c>»",
	},
	{
		name: "i< picks the inner of nested pairs",
		buffer: "<a <b|> c>",
		object: "i<",
		expect: "<a <«b»> c>",
	},
	{
		name: "i< fails when the count exceeds the nesting",
		buffer: "<a|>",
		object: "i<",
		count: 2,
		expect: null,
	},
	{
		name: "i< keeps an emoji inside",
		buffer: `<a|${THUMB}b>`,
		object: "i<",
		expect: `<«a${THUMB}b»>`,
	},
	{ name: "ib is i(", buffer: "foo (b|ar) baz", object: "ib", expect: "foo («bar») baz" },
	{ name: "ab is a(", buffer: "foo (b|ar) baz", object: "ab", expect: "foo «(bar)» baz" },
	{ name: "i) is i(", buffer: "foo (b|ar) baz", object: "i)", expect: "foo («bar») baz" },
	{ name: "a) is a(", buffer: "foo (b|ar) baz", object: "a)", expect: "foo «(bar)» baz" },
	{ name: "i] is i[", buffer: "foo [b|ar] baz", object: "i]", expect: "foo [«bar»] baz" },
	{ name: "a] is a[", buffer: "foo [b|ar] baz", object: "a]", expect: "foo «[bar]» baz" },
	{ name: "iB is i{", buffer: "foo {b|ar} baz", object: "iB", expect: "foo {«bar»} baz" },
	{ name: "aB is a{", buffer: "foo {b|ar} baz", object: "aB", expect: "foo «{bar}» baz" },
	{ name: "i} is i{", buffer: "foo {b|ar} baz", object: "i}", expect: "foo {«bar»} baz" },
	{ name: "a} is a{", buffer: "foo {b|ar} baz", object: "a}", expect: "foo «{bar}» baz" },
	{ name: "i> is i<", buffer: "foo <b|ar> baz", object: "i>", expect: "foo <«bar»> baz" },
	{ name: "a> is a<", buffer: "foo <b|ar> baz", object: "a>", expect: "foo «<bar>» baz" },
	{
		name: "i( ignores other bracket kinds inside",
		buffer: "(a [b|] {c})",
		object: "i(",
		expect: "(«a [b] {c}»)",
	},
	{ name: "i( ignores an escaped bracket", buffer: "(a\\)b|)", object: "i(", expect: "(«a\\)b»)" },
	{ name: "i( spans lines", buffer: "f(a,\n  b|\n)", object: "i(", expect: "f(«a,\n  b\n»)" },
	{
		name: "i( drops the line breaks around an indented block",
		buffer: "f(\n  a|\n)",
		object: "i(",
		expect: "f(\n«  a\n»)",
	},
	{
		name: "i{ drops the lines around a block",
		buffer: "if (x) {\n  foo|\n}",
		object: "i{",
		expect: "if (x) {\n«  foo\n»}",
	},
	{
		name: "a{ takes the braces of a block",
		buffer: "if (x) {\n  foo|\n}",
		object: "a{",
		expect: "if (x) «{\n  foo\n}»",
	},
	{
		name: "i{ skips the indent before the closing brace",
		buffer: "if (x) {\n  foo|\n  }",
		object: "i{",
		expect: "if (x) {\n«  foo\n»  }",
	},
	{
		name: "i{ from the indent of the body",
		buffer: "if (x) {\n|  foo\n}",
		object: "i{",
		expect: "if (x) {\n«  foo\n»}",
	},
	{
		name: "i{ on the closing brace line",
		buffer: "if (x) {\n  foo\n|}",
		object: "i{",
		expect: "if (x) {\n«  foo\n»}",
	},
	{
		name: "i{ on the opening brace line",
		buffer: "if (x) |{\n  foo\n}",
		object: "i{",
		expect: "if (x) {\n«  foo\n»}",
	},
	{
		name: "i( takes text after the bracket on its line",
		buffer: "a (b\nc|) d",
		object: "i(",
		expect: "a («b\nc») d",
	},
	{ name: "a( crosses lines", buffer: "a (b\nc|) d", object: "a(", expect: "a «(b\nc)» d" },
	{ name: "i{ nests", buffer: "{ a { b| } c }", object: "i{", expect: "{ a {« b »} c }" },
	{
		name: "2i{ nests",
		buffer: "{ a { b| } c }",
		object: "i{",
		count: 2,
		expect: "{« a { b } c »}",
	},
	{
		name: "iw on an empty last line reaches back over the previous line break",
		buffer: "a\n\n|",
		object: "iw",
		expect: "a\n«\n»",
	},
	{
		name: "aW on an empty line reaches the next empty line",
		buffer: "x\n|\n\ny",
		object: "aW",
		expect: "x\n«\n»\ny",
	},
	{
		name: "i( skips a bracket inside quotes when looking for the closing one",
		buffer: '(x b| "a)" y)',
		object: "i(",
		expect: '(«x b "a)" y»)',
	},
	{
		name: "i( skips a quoted character literal when looking for the closing bracket",
		buffer: "(x b| ')' y)",
		object: "i(",
		expect: "(«x b ')' y»)",
	},
];

interface Span {
	start: Cursor;
	/** The first position left out. */
	end: Cursor;
}

function parseRange(marked: string): Span {
	const start = marked.indexOf("«");
	const end = marked.indexOf("»");
	const position = (offset: number, text: string): Cursor => {
		const lines = text.slice(0, offset).split("\n");
		return { line: lines.length - 1, col: lines.at(-1)?.length ?? 0 };
	};
	const plain = plainText(marked);
	return { start: position(start, marked), end: position(end - 1, plain) };
}

function plainText(marked: string): string {
	return marked.replace("«", "").replace("»", "");
}

/** The span an operator takes: an inclusive end on a line end stops there. */
function spanOf(lines: readonly string[], { start, end, inclusive }: TextRange): Span {
	const text = lines[end.line] ?? "";
	if (!inclusive || end.col >= text.length) return { start, end };
	return { start, end: { line: end.line, col: nextBoundary(text, end.col) } };
}

/** The last position Visual mode selects, which Neovim reports as the end mark. */
function selectedEnd(lines: readonly string[], { end, inclusive }: TextRange): Cursor {
	if (inclusive || (end.line === 0 && end.col === 0)) return end;
	if (end.col > 0) {
		return { line: end.line, col: prevBoundary(lines[end.line] ?? "", end.col) };
	}
	return { line: end.line - 1, col: (lines[end.line - 1] ?? "").length };
}

function deleteSpan(lines: readonly string[], { start, end }: Span): string[] {
	const head = (lines[start.line] ?? "").slice(0, start.col);
	const tail = (lines[end.line] ?? "").slice(end.col);
	return [...lines.slice(0, start.line), head + tail, ...lines.slice(end.line + 1)];
}

const isEmpty = ({ start, end }: Span): boolean =>
	start.line === end.line && start.col === end.col;

function keysFor({ object, count }: ObjectCase): string {
	return `${count ?? ""}${object}`;
}

describe("text object case coverage", () => {
	it("gives every object a case", () => {
		const missing = OBJECTS.filter((object) => !CASES.some((entry) => entry.object === object));

		assert.deepEqual(missing, []);
	});

	it("gives the word and bracket objects a counted case", () => {
		const counted = (object: string): boolean =>
			CASES.some((entry) => entry.object === object && entry.count !== undefined);
		const missing = ["iw", "aw", "iW", "aW", "i(", "a(", "i[", "a[", "i{", "a{", "i<", "a<"].filter(
			(object) => !counted(object),
		);

		assert.deepEqual(missing, []);
	});

	it("has unique case names", () => {
		const names = CASES.map(({ name }) => name);

		assert.equal(new Set(names).size, names.length);
	});
});

describe("text object ranges", () => {
	for (const entry of CASES) {
		it(entry.name, () => {
			const { text, cursor } = parseBuffer(entry.buffer);
			const lines = text.split("\n");

			const range = selectTextObject(lines, cursor, entry.object, entry.count ?? null);

			if (entry.expect === null || range === null) {
				assert.equal(range, null);
				assert.equal(entry.expect, null);
			} else {
				assert.equal(plainText(entry.expect), text, "expectation text differs from the buffer");
				assert.deepEqual(spanOf(lines, range), parseRange(entry.expect));
			}
		});
	}
});

describe("text object ranges against Neovim", () => {
	for (const entry of CASES) {
		it(entry.name, () => {
			const { text, cursor } = parseBuffer(entry.buffer);
			const lines = text.split("\n");
			const range = selectTextObject(lines, cursor, entry.object, entry.count ?? null);
			const keys = keysFor(entry);

			// An empty range or no object selects nothing, which Visual mode cannot express
			if (range === null || isEmpty(spanOf(lines, range))) {
				assert.deepEqual(runCase(text, cursor, `d${keys}`).lines, lines, `d${keys} changes text`);
				return;
			}

			const selected = selectRange(text, cursor, keys);
			assert.deepEqual(
				selected,
				{ start: range.start, end: selectedEnd(lines, range) },
				`v${keys} selects another range`,
			);
			// A delete across lines may turn linewise, which is the operator's rule, not the object's
			if (range.start.line === range.end.line) {
				const expected = deleteSpan(lines, spanOf(lines, range));
				assert.deepEqual(runCase(text, cursor, `d${keys}`).lines, expected);
			}
		});
	}
});

describe("long lines", () => {
	const lines = ["a".repeat(10_000)];
	const cursor = { line: 0, col: 0 };

	it("moves by word in bounded time", () => {
		const started = performance.now();
		const result = runMotion("w", { lines, cursor, count: null, wantedCol: 0, lastFind: null });
		assert.equal(result.cursor.col, 9_999);
		assert.ok(performance.now() - started < 1000, "w over a 10,000-character word");
	});

	it("selects a word in bounded time", () => {
		const started = performance.now();
		const range = selectTextObject(lines, cursor, "iw", 1);
		assert.deepEqual(range?.end, { line: 0, col: 9_999 });
		assert.ok(performance.now() - started < 1000, "iw over a 10,000-character word");
	});
});
