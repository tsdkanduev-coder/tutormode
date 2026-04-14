import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkMath from "remark-math";
import { processMarkdownContent } from "../lib/latex.ts";

test("processMarkdownContent normalizes lone-dollar display math blocks", () => {
  const input = [
    "В треугольниках ABC и DEF известно:",
    "",
    "$",
    "\\angle A = 40^\\circ, \\quad \\angle B = 70^\\circ",
    "$",
  ].join("\n");

  const normalized = processMarkdownContent(input);

  assert.match(normalized, /\n\$\$\n\\angle A = 40\^\\circ, \\quad \\angle B = 70\^\\circ\n\$\$/);
  assert.doesNotMatch(normalized, /^\$\s*$/m);
});

test("processMarkdownContent converts bracketed display math into $$ blocks", () => {
  const input = [
    "## Задача",
    "Даны треугольники \\(ABC\\) и \\(MNK\\):",
    "",
    "\\[",
    "\\angle A = 55^\\circ,\\quad \\angle C = 45^\\circ",
    "\\]",
  ].join("\n");

  const normalized = processMarkdownContent(input);

  assert.match(normalized, /^## Задача/m);
  assert.match(normalized, /Даны треугольники\s+\$ABC\$\s+и\s+\$MNK\$/);
  assert.match(normalized, /\n\$\$\n\\angle A = 55\^\\circ,\\quad \\angle C = 45\^\\circ\n\$\$/);
  assert.doesNotMatch(normalized, /\n\$\n\\angle A = 55\^\\circ/);
  assert.doesNotMatch(normalized, /^# # /m);
});

test("remark-math renders multiline $$ blocks through KaTeX", () => {
  const content = [
    "В треугольниках ABC и DEF известно:",
    "",
    "$$",
    "\\angle A = 40^\\circ, \\quad \\angle B = 70^\\circ",
    "$$",
  ].join("\n");

  const html = renderToStaticMarkup(
    React.createElement(
      ReactMarkdown,
      {
        remarkPlugins: [remarkMath],
        rehypePlugins: [rehypeKatex],
      },
      content,
    ),
  );

  assert.match(html, /katex-display/);
  assert.match(html, /application\/x-tex/);
  assert.match(html, /<mi mathvariant="normal">∠<\/mi>/);
  assert.doesNotMatch(html, /<p>\$\$/);
});
