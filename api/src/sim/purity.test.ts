/**
 * The sim is a pure module. This test is what makes that a fact rather than a
 * convention: it walks the import graph reachable from `index.ts` and fails if
 * anything in it can reach outside the sim.
 */
import { readFileSync } from 'node:fs';
import { dirname, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const SIM_DIR = dirname(fileURLToPath(import.meta.url));
const ENTRY = resolve(SIM_DIR, 'index.ts');

const IMPORT_PATTERN = /(?:from|import)\s+['"]([^'"]+)['"]/g;

/** Strips comments, so the prose about what the sim must not do is not mistaken for doing it. */
function code(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^[ \t]*\/\/.*$/gm, '');
}

function importsOf(source: string): string[] {
  return [...code(source).matchAll(IMPORT_PATTERN)].map((match) => match[1]);
}

interface Module {
  path: string;
  source: string;
  specifiers: string[];
}

/** Every module `runBattle` can reach, the entry point included. */
function importGraph(): Module[] {
  const seen = new Map<string, Module>();
  const queue = [ENTRY];

  while (queue.length > 0) {
    const path = queue.shift() as string;
    if (seen.has(path)) continue;

    const source = readFileSync(path, 'utf8');
    const specifiers = importsOf(source);
    seen.set(path, { path, source, specifiers });

    for (const specifier of specifiers) {
      if (!specifier.startsWith('.')) continue;
      queue.push(resolve(dirname(path), specifier.replace(/\.js$/, '.ts')));
    }
  }

  return [...seen.values()];
}

const GRAPH = importGraph();

describe('the sim import graph', () => {
  it('reaches more than the entry point, so the walk is actually walking', () => {
    expect(GRAPH.length).toBeGreaterThan(5);
  });

  it('pulls in nothing from node — no node:fs, no node: anything', () => {
    const offenders = GRAPH.flatMap((module) =>
      module.specifiers
        .filter((specifier) => specifier.startsWith('node:') || specifier === 'fs')
        .map((specifier) => `${relative(SIM_DIR, module.path)} imports ${specifier}`),
    );

    expect(offenders).toEqual([]);
  });

  it('pulls in nothing from the client, and nothing outside the sim at all', () => {
    const offenders = GRAPH.flatMap((module) =>
      module.specifiers
        .filter((specifier) => {
          if (!specifier.startsWith('.')) return true;
          const resolved = resolve(dirname(module.path), specifier);
          return !resolved.startsWith(SIM_DIR);
        })
        .map((specifier) => `${relative(SIM_DIR, module.path)} imports ${specifier}`),
    );

    expect(offenders).toEqual([]);
  });
});

describe('the sim source', () => {
  const forbidden: Array<[string, RegExp]> = [
    ['Math.random — the sim draws from its seeded PRNG', /\bMath\.random\b/],
    ['Date — the sim has no wall clock, only ticks', /\bnew Date\b|\bDate\.now\b/],
    ['performance.now — the sim has no wall clock, only ticks', /\bperformance\.now\b/],
    ['process — the sim takes its configuration as arguments', /\bprocess\./],
    ['console — the sim returns its events, it does not print them', /\bconsole\./],
    ['require — the sim is ESM and imports nothing outside itself', /\brequire\s*\(/],
  ];

  for (const [why, pattern] of forbidden) {
    it(`never uses ${why}`, () => {
      const offenders = GRAPH.filter((module) => pattern.test(code(module.source))).map((module) =>
        relative(SIM_DIR, module.path),
      );

      expect(offenders).toEqual([]);
    });
  }
});
