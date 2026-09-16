/**
 * The player-spell resolver (JQ-297) — the TypeScript half.
 *
 * The server's `api/app/sim/loadout.py` is authoritative and this reproduces it.
 * Not because two copies are desirable, but because the alternative is a network
 * round trip on every tap of the plan screen: choosing a troop changes which
 * spells are legal and what each one costs, and a menu that greys out a beat
 * later is a menu the player has already tapped.
 *
 * **What keeps the copy honest is `conformance/spell-resolver.json`.** It is
 * generated from the Python implementation and checked in; `spellResolver.test.ts`
 * runs every case in it through the functions below and compares. So this file
 * cannot drift quietly, and it cannot be fixed by editing the fixture — the
 * Python suite pins the same file from the other side.
 *
 * Read the Python module for *why* the rules are what they are. Kept here, in
 * short:
 *
 * - A deployed mage counts once per tag it carries. Two copies of one mage are
 *   two mages. Tag combinations are never counted and summons never appear.
 * - Each number of each effect has its own bounded curve keyed on one tag:
 *   `min(cap, perMage * max(0, support - threshold))`, added to the base. There
 *   is no multiplier anywhere, and no school-resonance term — JQ-292 replaced
 *   player-spell resonance scaling with this.
 * - A signature granted twice is one menu entry.
 * - Independent access is explicit roster data. A tag never grants it, and a tag
 *   never implies faction membership: nothing here reads a school.
 */

/* --------------------------------------------------------------- the schema -- */

export interface DeployedMage {
  readonly instanceId: string;
  readonly typeId: string;
  readonly name: string;
  readonly tags: readonly string[];
}

export type SpellAccess =
  | { readonly kind: 'fallback' }
  | { readonly kind: 'signature'; readonly mageTypeId: string }
  | { readonly kind: 'independent'; readonly requiresTag: string | null; readonly minimum: number };

/**
 * One number of one effect, and the tag whose count raises it. `field` is a
 * dotted path into the effect — `radius`, or `damage.amount` for the amount
 * inside an area attack's damage profile.
 */
export interface EffectScaling {
  readonly effectIndex: number;
  readonly field: string;
  readonly tag: string;
  readonly perMage: number;
  readonly cap: number;
  readonly threshold: number;
}

/** An effect is carried as data. The client renders it; only the server runs it. */
export interface SpellEffect {
  readonly kind: string;
  readonly [field: string]: unknown;
}

export interface SpellDefinition {
  readonly id: string;
  readonly name: string;
  readonly cost: number;
  readonly text: string;
  readonly access: SpellAccess;
  readonly effects: readonly SpellEffect[];
  readonly scaling?: readonly EffectScaling[];
}

/* --------------------------------------------------------------- the result -- */

export interface TagSupport {
  readonly tag: string;
  readonly count: number;
}

export interface ScaledField {
  readonly effectIndex: number;
  readonly field: string;
  readonly tag: string;
  readonly support: number;
  readonly base: number;
  readonly bonus: number;
  readonly value: number;
  readonly capped: boolean;
}

export interface SpellContributor {
  readonly mageId: string;
  readonly mageName: string;
  readonly tag: string;
}

export interface ResolvedSpell {
  readonly spellId: string;
  readonly name: string;
  readonly cost: number;
  readonly access: 'signature' | 'independent' | 'fallback';
  readonly effects: readonly SpellEffect[];
  readonly scaled: readonly ScaledField[];
  readonly contributors: readonly SpellContributor[];
  /** Instance ids of the mages whose signature put this on the menu. */
  readonly grantedBy: readonly string[];
}

export interface MenuEntry {
  readonly eligible: boolean;
  /** Why it is greyed. Shown rather than hidden, so the link teaches itself. */
  readonly reason: string | null;
  readonly spell: ResolvedSpell;
}

export interface LoadoutMenu {
  readonly tagSupport: readonly TagSupport[];
  readonly entries: readonly MenuEntry[];
}

export interface SlotOutcome {
  readonly index: number;
  readonly spellId: string | null;
  readonly eligible: boolean;
  readonly reason: string | null;
  /** Filled with something no longer legal. Blocks lock-in until replaced. */
  readonly stranded: boolean;
}

export interface LoadoutSnapshot {
  readonly namespace: string;
  readonly tagSupport: readonly TagSupport[];
  readonly spells: readonly ResolvedSpell[];
  /** The ids the sim holds this seat's resolved copies under. */
  readonly simSpellIds: readonly string[];
}

export interface LoadoutRules {
  readonly slots: number;
  readonly reselectEachRound: boolean;
  readonly snapshotAtLockIn: boolean;
}

export const DEFAULT_LOADOUT_RULES: LoadoutRules = {
  slots: 2,
  reselectEachRound: true,
  snapshotAtLockIn: true,
};

/** A loadout the server would refuse. Thrown by `snapshotLoadout`. */
export class LoadoutError extends Error {}

/* ------------------------------------------------------------- field paths -- */

function readField(effect: SpellEffect, path: string): number {
  let node: unknown = effect;
  for (const part of path.split('.')) {
    node = (node as Record<string, unknown>)[part];
  }
  return node as number;
}

/**
 * A copy of `effect` with the dotted field set. Copied rather than mutated: one
 * definition's base effects are resolved against many plans, and a write in
 * place would leak one resolution's numbers into the next.
 */
function writeField(effect: SpellEffect, path: string, value: number): SpellEffect {
  const [head, ...rest] = path.split('.');
  if (rest.length === 0) return { ...effect, [head]: value };
  const child = effect[head] as SpellEffect;
  return { ...effect, [head]: writeField(child, rest.join('.'), value) };
}

/* ---------------------------------------------------------------- counting -- */

/**
 * How many deployed mages carry each tag, sorted by tag.
 *
 * Once per mage per tag — a mage listing a tag twice still counts once for it.
 * Sorted so the order does not depend on which mage was tapped first, matching
 * the server, whose containers would otherwise iterate in a per-process order.
 */
export function tagSupport(mages: readonly DeployedMage[]): TagSupport[] {
  const counts = new Map<string, number>();
  for (const mage of mages) {
    for (const tag of new Set(mage.tags)) {
      counts.set(tag, (counts.get(tag) ?? 0) + 1);
    }
  }
  return [...counts.entries()]
    .map(([tag, count]) => ({ tag, count }))
    .sort((a, b) => (a.tag < b.tag ? -1 : a.tag > b.tag ? 1 : 0));
}

function supportMap(support: readonly TagSupport[]): Map<string, number> {
  return new Map(support.map((entry) => [entry.tag, entry.count]));
}

/** The tags a spell's numbers key off, in first-mention order. */
export function spellReads(definition: SpellDefinition): string[] {
  const found: string[] = [];
  for (const entry of definition.scaling ?? []) {
    if (!found.includes(entry.tag)) found.push(entry.tag);
  }
  return found;
}

/**
 * Every (mage, tag) pair feeding this spell, in plan order then the spell's tag
 * order. Carriers are listed even where a threshold means they add nothing yet:
 * "one more Evocation mage and this starts working" is what the screen has to be
 * able to say.
 */
function contributorsOf(
  definition: SpellDefinition,
  mages: readonly DeployedMage[],
): SpellContributor[] {
  const reads = spellReads(definition);
  const found: SpellContributor[] = [];
  for (const mage of mages) {
    for (const tag of reads) {
      if (mage.tags.includes(tag)) {
        found.push({ mageId: mage.instanceId, mageName: mage.name, tag });
      }
    }
  }
  return found;
}

function grantedBy(definition: SpellDefinition, mages: readonly DeployedMage[]): string[] {
  if (definition.access.kind !== 'signature') return [];
  const { mageTypeId } = definition.access;
  return mages.filter((mage) => mage.typeId === mageTypeId).map((mage) => mage.instanceId);
}

/* --------------------------------------------------------------- resolving -- */

export function resolveSpell(
  definition: SpellDefinition,
  mages: readonly DeployedMage[],
  support: Map<string, number> = supportMap(tagSupport(mages)),
): ResolvedSpell {
  const effects = [...definition.effects];
  const scaled: ScaledField[] = [];

  for (const entry of definition.scaling ?? []) {
    const count = support.get(entry.tag) ?? 0;
    const base = readField(definition.effects[entry.effectIndex], entry.field);
    const raw = entry.perMage * Math.max(0, count - entry.threshold);
    const bonus = Math.min(entry.cap, raw);
    // `>=` rather than `>`: a curve landing exactly on its cap is bound by it,
    // and a screen saying "one more mage helps" when it does not is worse than
    // one that says nothing.
    const capped = entry.cap > 0 && raw >= entry.cap;
    effects[entry.effectIndex] = writeField(effects[entry.effectIndex], entry.field, base + bonus);
    scaled.push({
      effectIndex: entry.effectIndex,
      field: entry.field,
      tag: entry.tag,
      support: count,
      base,
      bonus,
      value: base + bonus,
      capped,
    });
  }

  return {
    spellId: definition.id,
    name: definition.name,
    cost: definition.cost,
    access: definition.access.kind,
    effects,
    scaled,
    contributors: contributorsOf(definition, mages),
    grantedBy: grantedBy(definition, mages),
  };
}

function eligibility(
  definition: SpellDefinition,
  mages: readonly DeployedMage[],
  rosterAccess: readonly string[],
  support: Map<string, number>,
): { eligible: boolean; reason: string | null } {
  const access = definition.access;

  if (access.kind === 'fallback') return { eligible: true, reason: null };

  if (access.kind === 'signature') {
    const present = mages.some((mage) => mage.typeId === access.mageTypeId);
    return { eligible: present, reason: present ? null : 'needs its mage on the field' };
  }

  // Roster first, and it never says "and you also lack the tag" — that would
  // enumerate a roster the player does not own, one greyed card at a time.
  if (!rosterAccess.includes(definition.id)) {
    return { eligible: false, reason: 'is not on this roster' };
  }
  if (access.requiresTag === null) return { eligible: true, reason: null };

  const count = support.get(access.requiresTag) ?? 0;
  if (count >= access.minimum) return { eligible: true, reason: null };
  return {
    eligible: false,
    reason:
      access.minimum === 1
        ? `needs a fielded ${access.requiresTag} mage`
        : `needs ${access.minimum} fielded ${access.requiresTag} mages`,
  };
}

export interface ResolveMenuInput {
  readonly mages: readonly DeployedMage[];
  readonly rosterAccess?: readonly string[];
  readonly definitions: readonly SpellDefinition[];
}

/**
 * The whole menu for one plan, in catalog order.
 *
 * One entry per definition, so two deployed copies of a mage put their shared
 * signature on the menu once. Ineligible spells are resolved too — a greyed card
 * shows the numbers it *would* have at this plan's tag support, which is what
 * lets the screen show what fielding the missing mage buys.
 */
export function resolveMenu({ mages, rosterAccess = [], definitions }: ResolveMenuInput): LoadoutMenu {
  const support = tagSupport(mages);
  const lookup = supportMap(support);

  return {
    tagSupport: support,
    entries: definitions.map((definition) => ({
      ...eligibility(definition, mages, rosterAccess, lookup),
      spell: resolveSpell(definition, mages, lookup),
    })),
  };
}

/* ------------------------------------------------------------------- slots -- */

/**
 * Each slot of a selection against a menu, in screen order.
 *
 * A slot holding something the current troops no longer support is `stranded`
 * and blocks lock-in. Reported rather than silently cleared: the player chose
 * that spell and should be told it went away, not discover an empty slot.
 */
export function resolveSlots(
  menu: LoadoutMenu,
  selection: readonly (string | null)[],
  rules: LoadoutRules = DEFAULT_LOADOUT_RULES,
): SlotOutcome[] {
  if (selection.length > rules.slots) {
    throw new LoadoutError(`a plan carries at most ${rules.slots} spells`);
  }

  return selection.map((spellId, index) => {
    if (spellId === null) {
      return { index, spellId: null, eligible: true, reason: null, stranded: false };
    }
    const entry = menu.entries.find((candidate) => candidate.spell.spellId === spellId);
    if (entry === undefined) {
      return {
        index,
        spellId,
        eligible: false,
        reason: 'is not a spell on this roster',
        stranded: true,
      };
    }
    return {
      index,
      spellId,
      eligible: entry.eligible,
      reason: entry.reason,
      stranded: !entry.eligible,
    };
  });
}

/**
 * Last round's slots, with the ones that are still legal kept.
 *
 * The other half of "both slots reselected each round": the slots are chosen
 * again, but a player who fielded the same troops does not retype the same two
 * spells. A choice that is no longer eligible becomes an *empty* slot rather
 * than a stranded one — a new round has no selection to strand, and this is
 * what the player is handed to edit.
 */
export function preservedSelection(
  menu: LoadoutMenu,
  previous: readonly (string | null)[],
  rules: LoadoutRules = DEFAULT_LOADOUT_RULES,
): (string | null)[] {
  if (!rules.reselectEachRound) return [...previous.slice(0, rules.slots)];

  const eligible = menu.entries.filter((entry) => entry.eligible).map((entry) => entry.spell.spellId);
  const kept = previous
    .slice(0, rules.slots)
    .map((spellId) => (spellId !== null && eligible.includes(spellId) ? spellId : null));
  while (kept.length < rules.slots) kept.push(null);
  return kept;
}

/* ---------------------------------------------------------------- snapshot -- */

export interface SnapshotInput extends ResolveMenuInput {
  readonly namespace: string;
  readonly selection: readonly (string | null)[];
  readonly rules?: LoadoutRules;
}

/**
 * Freeze this plan's spells for the round, or throw on an illegal selection.
 *
 * The client's copy of what the server does at lock-in. Useful before locking
 * in — it answers "would this be accepted, and at what numbers" without a round
 * trip — but it is not the authority: the server takes its own snapshot from
 * the plan it received, and that is what the battle runs.
 *
 * `snapshotAtLockIn: false` is refused rather than ignored, matching the server.
 */
export function snapshotLoadout({
  namespace,
  mages,
  selection,
  rosterAccess = [],
  definitions,
  rules = DEFAULT_LOADOUT_RULES,
}: SnapshotInput): LoadoutSnapshot {
  // Mirrors the server's refusal. Resolving live is not something either side
  // can honour alone — the battle's spell catalog is built once from the
  // snapshot — so the flag says so rather than looking configurable.
  if (!rules.snapshotAtLockIn) {
    throw new LoadoutError(
      'snapshotAtLockIn is off, and resolving a loadout live is not implemented',
    );
  }

  const menu = resolveMenu({ mages, rosterAccess, definitions });
  const outcomes = resolveSlots(menu, selection, rules);

  for (const outcome of outcomes) {
    if (outcome.stranded) {
      throw new LoadoutError(`spell ${outcome.index + 1} — ${outcome.spellId} ${outcome.reason}`);
    }
  }

  const spells: ResolvedSpell[] = [];
  for (const outcome of outcomes) {
    if (outcome.spellId === null) continue;
    // A spell chosen in both slots is one entry in the battle's catalog.
    if (spells.some((spell) => spell.spellId === outcome.spellId)) continue;
    const entry = menu.entries.find((candidate) => candidate.spell.spellId === outcome.spellId);
    if (entry !== undefined) spells.push(entry.spell);
  }

  return {
    namespace,
    tagSupport: menu.tagSupport,
    spells,
    simSpellIds: spells.map((spell) => `${namespace}:${spell.spellId}`),
  };
}

/* ----------------------------------------------------------------- display -- */

/**
 * A field path as a sentence reads it: `damage.amount` -> `damage amount`,
 * `damagePerSecond` -> `damage per second`.
 *
 * The whole path rather than its last segment — a bare `amount` next to a
 * `radius` says nothing about which of a spell's numbers moved. Camel case is
 * split so this reads the same as the server's sentence, whose paths arrive in
 * snake case.
 */
function label(path: string): string {
  return path
    .replace(/[._]/g, ' ')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .toLowerCase();
}

function num(value: number): string {
  // Matches Python's `:g`: 54.0 prints as `54` on both sides.
  return String(Number(value.toPrecision(6)));
}

/**
 * One sentence naming a spell's resolved numbers and what raised them.
 *
 * A local stand-in for the sentence the server sends on the wire, for previews
 * taken before lock-in. Deliberately *not* pinned by the conformance fixtures:
 * wording is display, and a reworded card should not fail a cross-language
 * build. What it will not do is guess at outcomes — it reports what the numbers
 * are and says nothing about what they would kill.
 */
export function effectSummary(spell: ResolvedSpell, text: string): string {
  if (spell.scaled.length === 0) return text;

  const parts = spell.scaled.map((entry) => {
    if (entry.bonus === 0) return `${label(entry.field)} ${num(entry.value)}`;
    const tail = entry.capped ? ', at its cap' : '';
    const plural = entry.support === 1 ? '' : 's';
    return (
      `${label(entry.field)} ${num(entry.value)} ` +
      `(+${num(entry.bonus)} from ${entry.support} ${entry.tag} mage${plural}${tail})`
    );
  });

  return `${text} ${parts.join('; ')}.`;
}
