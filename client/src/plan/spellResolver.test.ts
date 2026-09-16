/**
 * The client's resolver reproduces the server's, case for case.
 *
 * Half of a two-sided agreement (JQ-297). `conformance/spell-resolver.json` is
 * generated from `api/app/sim/loadout.py` and checked in; the Python suite fails
 * if the file stops describing the server, and this fails if TypeScript stops
 * reproducing the file. Neither side can be made green by editing the fixture.
 *
 * Read through `node:fs` rather than imported, deliberately. The fixture lives
 * outside `client/`, an `import` of it would need Vite's `fs.allow` opened up
 * for a test, and — more to the point — reading it at runtime is what makes a
 * *missing* fixture a loud failure instead of a build-time resolution error
 * nobody connects to the server.
 *
 * Found by walking up from the working directory rather than from
 * `import.meta.url`: these tests run under jsdom, where `import.meta.url` is an
 * `http://` URL and `fileURLToPath` throws on it. The walk also means the suite
 * runs the same from `client/` and from the repository root.
 *
 * Floats are compared by parsed value, not by bytes. Python writes `35.0` where
 * JavaScript writes `35`; `JSON.parse` erases the difference, which is exactly
 * what `api/CONVENTIONS.md` says to rely on rather than chasing byte equality
 * between two languages.
 */

import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { describe, expect, it } from 'vitest';

import {
  type DeployedMage,
  type LoadoutRules,
  type SpellDefinition,
  LoadoutError,
  resolveMenu,
  resolveSlots,
  snapshotLoadout,
  tagSupport,
} from './spellResolver.ts';

interface ConformanceCase {
  readonly name: string;
  readonly why: string;
  readonly mages: readonly DeployedMage[];
  readonly rosterAccess: readonly string[];
  readonly selection: readonly (string | null)[];
  readonly expected: {
    readonly menu: unknown;
    readonly slots: readonly unknown[];
    readonly snapshot: unknown;
    readonly snapshotError: string | null;
  };
}

interface ConformanceFixture {
  readonly version: number;
  readonly rules: LoadoutRules;
  readonly namespace: string;
  readonly spells: readonly SpellDefinition[];
  readonly cases: readonly ConformanceCase[];
}

function findFixture(): string {
  let directory = process.cwd();
  for (;;) {
    const candidate = join(directory, 'conformance', 'spell-resolver.json');
    if (existsSync(candidate)) return candidate;
    const parent = dirname(directory);
    if (parent === directory) {
      throw new Error(
        'conformance/spell-resolver.json not found. Generate it with ' +
          '`cd api && python -m app.scripts.export_conformance`.',
      );
    }
    directory = parent;
  }
}

const FIXTURE_PATH = findFixture();

const fixture: ConformanceFixture = JSON.parse(readFileSync(FIXTURE_PATH, 'utf8'));

/** The fixture's shape, as this file reads it. A mismatch is a stale client. */
const SUPPORTED_VERSION = 1;

/**
 * The menu, as the fixture records it. Built rather than compared field by
 * field, so a field the resolver stopped emitting fails instead of passing by
 * being absent on both sides — the blind spot `api/CONVENTIONS.md` calls out.
 */
function menuJson(entry: ReturnType<typeof resolveMenu>): unknown {
  return {
    tagSupport: entry.tagSupport.map((support) => ({ tag: support.tag, count: support.count })),
    entries: entry.entries.map((item) => ({
      eligible: item.eligible,
      reason: item.reason,
      spell: {
        spellId: item.spell.spellId,
        name: item.spell.name,
        cost: item.spell.cost,
        access: item.spell.access,
        effects: item.spell.effects,
        scaled: item.spell.scaled,
        contributors: item.spell.contributors,
        grantedBy: item.spell.grantedBy,
      },
    })),
  };
}

describe('the shared conformance fixture', () => {
  it('is the version this resolver was written against', () => {
    expect(fixture.version).toBe(SUPPORTED_VERSION);
  });

  it('carries cases to run', () => {
    // A fixture that regenerated to nothing would make every test below pass
    // vacuously, which is the one way this suite could go green while broken.
    expect(fixture.cases.length).toBeGreaterThan(8);
    expect(fixture.spells.length).toBeGreaterThan(2);
  });
});

describe.each(fixture.cases)('$name', (testCase: ConformanceCase) => {
  const definitions = fixture.spells;

  it(`resolves the menu the server does — ${testCase.why}`, () => {
    const menu = resolveMenu({
      mages: testCase.mages,
      rosterAccess: testCase.rosterAccess,
      definitions,
    });

    expect(menuJson(menu)).toEqual(testCase.expected.menu);
  });

  it('resolves the slots the server does', () => {
    const menu = resolveMenu({
      mages: testCase.mages,
      rosterAccess: testCase.rosterAccess,
      definitions,
    });

    expect(resolveSlots(menu, testCase.selection, fixture.rules)).toEqual(testCase.expected.slots);
  });

  it('agrees on whether lock-in would be accepted', () => {
    const take = () =>
      snapshotLoadout({
        namespace: fixture.namespace,
        mages: testCase.mages,
        selection: testCase.selection,
        rosterAccess: testCase.rosterAccess,
        definitions,
        rules: fixture.rules,
      });

    if (testCase.expected.snapshotError !== null) {
      expect(take).toThrow(LoadoutError);
      expect(take).toThrow(testCase.expected.snapshotError);
      return;
    }

    const snapshot = take();
    expect({
      namespace: snapshot.namespace,
      tagSupport: snapshot.tagSupport.map((s) => ({ tag: s.tag, count: s.count })),
      spells: snapshot.spells.map((spell) => ({
        spellId: spell.spellId,
        name: spell.name,
        cost: spell.cost,
        access: spell.access,
        effects: spell.effects,
        scaled: spell.scaled,
        contributors: spell.contributors,
        grantedBy: spell.grantedBy,
      })),
      simSpellIds: snapshot.simSpellIds,
    }).toEqual(testCase.expected.snapshot);
  });
});

/*
 * The cases above pin agreement with the server. These pin the properties the
 * fixture *cannot* — a rule that holds for inputs nobody generated a case for.
 */

describe('counting', () => {
  const dual: DeployedMage = { instanceId: 'm1', typeId: 'adept', name: 'A', tags: ['evocation', 'reckless'] };

  it('counts each mage once per tag and never counts a combination', () => {
    expect(tagSupport([dual])).toEqual([
      { tag: 'evocation', count: 1 },
      { tag: 'reckless', count: 1 },
    ]);
  });

  it('counts a tag listed twice on one mage once', () => {
    const sloppy: DeployedMage = { ...dual, tags: ['evocation', 'evocation'] };
    expect(tagSupport([sloppy])).toEqual([{ tag: 'evocation', count: 1 }]);
  });

  it('counts two instances of one mage type twice', () => {
    expect(tagSupport([dual, { ...dual, instanceId: 'm2' }])).toEqual([
      { tag: 'evocation', count: 2 },
      { tag: 'reckless', count: 2 },
    ]);
  });
});

describe('resolving one spell against many plans', () => {
  it('never mutates the definition it was given', () => {
    // A definition is resolved for both seats and again on every tap. A write in
    // place would make the second resolution start from the first's numbers, and
    // the bug would look like a slow drift rather than a wrong formula.
    const before = JSON.stringify(fixture.spells);

    for (const testCase of fixture.cases) {
      resolveMenu({
        mages: testCase.mages,
        rosterAccess: testCase.rosterAccess,
        definitions: fixture.spells,
      });
    }

    expect(JSON.stringify(fixture.spells)).toBe(before);
  });
});

describe('slots', () => {
  it('refuses more spells than the rules allow', () => {
    const menu = resolveMenu({ mages: [], definitions: fixture.spells });
    expect(() => resolveSlots(menu, ['spark', 'spark', 'spark'], fixture.rules)).toThrow(LoadoutError);
  });
});

describe('the snapshot policy', () => {
  it('refuses to resolve live rather than silently ignoring the flag', () => {
    // The server refuses the same way. A flag that looked configurable on one
    // side and was ignored on the other is the drift these fixtures exist to
    // prevent, in the one place a fixture cannot see it.
    expect(() =>
      snapshotLoadout({
        namespace: 'north',
        mages: [],
        selection: [null, null],
        definitions: fixture.spells,
        rules: { ...fixture.rules, snapshotAtLockIn: false },
      }),
    ).toThrow(LoadoutError);
  });
});
