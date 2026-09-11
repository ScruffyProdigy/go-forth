/**
 * Schools, and the one record slices C and D trade through.
 *
 * Resonance (design doc §4.11) scales a school's energy gain, resummon pace, and
 * its own stat axis. Energy is slice C's territory and resonance is slice D's,
 * which would put both slices in the same energy-gain code. The multiplier table
 * is the seam that avoids it: resolved once here at battle start, read by every
 * system, written by nobody.
 *
 * **Slice C reads it. Slice D populates it** — by computing the resonance curve
 * inside `resolveSchoolMultipliers` from the mages deployed at battle start.
 * Slice A ships identity values, so the hook is live but changes nothing yet.
 * If work on energy gain starts reaching into resonance, or work on resonance
 * starts editing energy gain, this seam has been crossed.
 */

export type School = 'fire' | 'stone' | 'artifice' | 'time' | 'necromancy' | 'neutral';

export const SCHOOLS: readonly School[] = [
  'fire',
  'stone',
  'artifice',
  'time',
  'necromancy',
  'neutral',
] as const;

export interface SchoolMultipliers {
  /** Scales how fast a unit's energy gauge fills (§4.4). Slice C's lever. */
  readonly energyGainMultiplier: number;
  /** Scales seconds-per-resummon for this school's mages (§4.5). Slice D's lever. */
  readonly resummonPaceMultiplier: number;
  /** Scales this school's own stat axis — Fire speed and damage, Stone HP, and so on (§4.11). */
  readonly statAxisMultiplier: number;
}

export interface SchoolConfig {
  id: School;
  /**
   * Optional overrides. Slice D fills these from the resonance curve; until then
   * everything resolves to identity.
   */
  multipliers?: Partial<SchoolMultipliers>;
}

export const IDENTITY_MULTIPLIERS: SchoolMultipliers = Object.freeze({
  energyGainMultiplier: 1,
  resummonPaceMultiplier: 1,
  statAxisMultiplier: 1,
});

/** A multiplier per school, frozen: resolved once at battle start, never after. */
export type SchoolMultiplierTable = Readonly<Record<School, SchoolMultipliers>>;

const LEVERS = [
  'energyGainMultiplier',
  'resummonPaceMultiplier',
  'statAxisMultiplier',
] as const satisfies readonly (keyof SchoolMultipliers)[];

function merge(school: School, overrides: Partial<SchoolMultipliers>): SchoolMultipliers {
  const resolved = { ...IDENTITY_MULTIPLIERS };

  for (const lever of LEVERS) {
    const value = overrides[lever];
    if (value === undefined) continue;
    if (!Number.isFinite(value) || value <= 0) {
      throw new Error(`${school} ${lever} must be a positive number, got ${value}`);
    }
    resolved[lever] = value;
  }

  return Object.freeze(resolved);
}

/** Builds the battle's multiplier table. Call once, at battle start. */
export function resolveSchoolMultipliers(
  schoolConfigs: readonly SchoolConfig[],
): SchoolMultiplierTable {
  const overrides = new Map<School, Partial<SchoolMultipliers>>();

  for (const config of schoolConfigs) {
    if (overrides.has(config.id)) {
      throw new Error(`school ${config.id} is configured twice`);
    }
    overrides.set(config.id, config.multipliers ?? {});
  }

  const table = {} as Record<School, SchoolMultipliers>;
  for (const school of SCHOOLS) {
    table[school] = merge(school, overrides.get(school) ?? {});
  }

  return Object.freeze(table);
}
