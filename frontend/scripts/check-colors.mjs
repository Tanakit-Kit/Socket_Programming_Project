import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import postcss from 'postcss';
import tailwind from '@tailwindcss/postcss';

const from = fileURLToPath(new URL('../app/globals.css', import.meta.url));
const source = await readFile(from, 'utf8');
const page = await readFile(new URL('../app/page.tsx', import.meta.url), 'utf8');
const tokens = [...page.matchAll(/\b(?:text|placeholder)-(content(?:-strong)?|heading|secondary|accent|muted|error(?:-strong)?|inverse|group-label|offline|input-hint)\b/g)];
const processor = postcss([tailwind()]);
for (let pass = 0; pass < 2; pass++) {
  const result = await processor.process(source, { from });
  const definitions = new Set();
  result.root.walkDecls(/^--/, declaration => definitions.add(declaration.prop));
  for (const [utility] of tokens) {
    let found = false;
    result.root.walkRules(rule => {
      if (rule.selector !== `.${utility}` && rule.selector !== `.${utility}::placeholder`) return;
      found = true;
      rule.walkDecls('color', declaration => {
        for (const [, variable] of declaration.value.matchAll(/var\((--[\w-]+)/g)) {
          assert(definitions.has(variable), `${utility}: missing ${variable}`);
        }
      });
    });
    assert(found, `Missing utility ${utility}`);
  }
}
console.log('Text color utilities and palette variables survive fresh and repeated compilation.');
