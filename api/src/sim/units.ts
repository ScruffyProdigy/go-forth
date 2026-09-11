/**
 * Unit types — the card, not the instance on the field.
 *
 * The stat block is design doc §4.4, minus the parts later slices own: the
 * energy gauge and the ability are slice C, resummon pace is read by slice D.
 * They are declared here because the *type* carries them; nothing in slice A
 * reads them.
 *
 * A card's `schools` is a list because dual-school cards are the design's
 * scarce fixing (§4.1) — a Furnace Golem is Fire/Artifice and counts for both.
 */
import type { School } from './schools.js';

export type UnitKind = 'mage' | 'summon';

export interface UnitType {
  id: string;
  kind: UnitKind;
  /** One school for a mono card, two for a dual. Never empty. */
  schools: School[];
  maxHp: number;
  damage: number;
  /** Attack reach in map units. Melee is a short range, not a special case. */
  range: number;
  /** Map units per second. Converted to per-tick by the loop. */
  speed: number;
  attackCooldownSeconds: number;
  /** Mages only: how many summons this mage sustains (§4.2). */
  supportCapacity?: number;
  /** Mages only: seconds per resummon (§4.5). Slice D reads it. */
  resummonPaceSeconds?: number;
}

export type UnitTypeCatalog = Readonly<Record<string, UnitType>>;

function validateUnitType(type: UnitType): void {
  if (type.schools.length === 0) {
    throw new Error(`unit type ${type.id} belongs to no school`);
  }
  if (!(type.maxHp > 0)) {
    throw new Error(`unit type ${type.id} has maxHp ${type.maxHp}; it must be positive`);
  }
  if (!(type.damage >= 0)) {
    throw new Error(`unit type ${type.id} has negative damage`);
  }
  if (!(type.range >= 0)) {
    throw new Error(`unit type ${type.id} has a negative range`);
  }
  if (!(type.speed >= 0)) {
    throw new Error(`unit type ${type.id} has a negative speed`);
  }
  if (!(type.attackCooldownSeconds > 0)) {
    throw new Error(
      `unit type ${type.id} has an attack cooldown of ${type.attackCooldownSeconds}; ` +
        'a cooldown of zero would fire every tick',
    );
  }
  if (type.kind === 'mage' && !(type.supportCapacity !== undefined && type.supportCapacity > 0)) {
    throw new Error(`mage type ${type.id} has no support capacity, so it could hold no summons`);
  }
}

/** Indexes the battle's cards by id, rejecting incoherent ones up front. */
export function buildUnitTypeCatalog(types: readonly UnitType[]): UnitTypeCatalog {
  const catalog: Record<string, UnitType> = {};

  for (const type of types) {
    if (catalog[type.id]) {
      throw new Error(`unit type ${type.id} is defined twice`);
    }
    validateUnitType(type);
    catalog[type.id] = Object.freeze({ ...type, schools: Object.freeze([...type.schools]) as School[] });
  }

  return Object.freeze(catalog);
}
