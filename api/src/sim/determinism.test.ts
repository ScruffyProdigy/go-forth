/**
 * Determinism: identical inputs and seed produce byte-identical state and event
 * output — in this process, and in a fresh one.
 *
 * The fresh-process half is not paranoia. Module-level state, iteration order
 * that happens to be stable within a warm process, and anything seeded off the
 * clock all survive an in-process comparison and fail a cold one.
 */
import { execFileSync } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import { placeholderBattle } from './fixtures.js';
import { THREE_ZONE_MAP } from './map.js';
import { runBattle } from './runBattle.js';
import { digestBattle, serializeBattle } from './serialize.js';

const API_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const TSX = resolve(API_DIR, 'node_modules', '.bin', 'tsx');
const DEMO = resolve(API_DIR, 'src', 'scripts', 'battleDemo.ts');

const SEED = 20260911;

function run(seed = SEED) {
  return runBattle(THREE_ZONE_MAP, [], placeholderBattle(), seed);
}

function demoOutput(seed: number): string {
  return execFileSync(TSX, [DEMO, '--seed', String(seed)], {
    cwd: API_DIR,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'ignore'],
  }).trimEnd();
}

describe('two runs in one process', () => {
  it('produce identical event output', () => {
    expect(JSON.stringify(run().events)).toBe(JSON.stringify(run().events));
  });

  it('produce identical state, tick by tick and not just at the end', () => {
    expect(JSON.stringify(run().ticks)).toBe(JSON.stringify(run().ticks));
  });

  it('produce the same digest', () => {
    expect(digestBattle(run())).toBe(digestBattle(run()));
  });

  it('actually depend on the seed — a different seed gives a different battle', () => {
    expect(serializeBattle(run(SEED))).not.toBe(serializeBattle(run(SEED + 1)));
  });
});

describe('a fresh process', () => {
  it('reproduces the in-process run byte for byte', () => {
    expect(demoOutput(SEED)).toBe(serializeBattle(run(SEED)));
  }, 60_000);

  it('reproduces itself, run twice', () => {
    expect(demoOutput(SEED + 1)).toBe(demoOutput(SEED + 1));
  }, 60_000);
});
