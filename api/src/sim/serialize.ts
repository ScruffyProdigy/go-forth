/**
 * Canonical text for a battle result.
 *
 * The determinism requirement is byte-identical *state and events*, which needs
 * one agreed rendering: two runs are compared by comparing this text. It is also
 * what the headless demo prints, so a fresh process can be checked against an
 * in-process run without a second format existing.
 *
 * Line-delimited JSON, with the survivors sorted by id — array order is an
 * implementation detail of how units died, and comparing it would fail runs that
 * are in fact identical.
 */
import type { BattleResult } from './runBattle.js';

function eventLine(event: BattleResult['events'][number]): string {
  return JSON.stringify({
    event: event.type,
    tick: event.tick,
    position: { x: event.position.x, y: event.position.y },
    actors: {
      source: event.actors.source?.unitId ?? null,
      targets: event.actors.targets.map((target) => target.unitId),
    },
    swing: {
      zoneScore: event.swing.zoneScore,
      baseHp: event.swing.baseHp,
      unitsRemoved: event.swing.unitsRemoved.map((unit) => unit.unitId),
    },
  });
}

export function serializeBattle(result: BattleResult): string {
  const header = JSON.stringify({
    seed: result.seed,
    map: result.map.id,
    tickRate: result.config.tickRate,
    outcome: result.outcome,
    ticks: result.finalState.tick,
  });

  const survivors = [...result.finalState.units]
    .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))
    .map((unit) => ({
      id: unit.id,
      side: unit.side,
      typeId: unit.typeId,
      hp: unit.hp,
      position: { x: unit.position.x, y: unit.position.y },
    }));

  const footer = JSON.stringify({
    finalUnits: survivors,
    bases: { north: result.finalState.bases.north.hp, south: result.finalState.bases.south.hp },
    zoneScore: result.finalState.zoneScore,
  });

  return [header, ...result.events.map(eventLine), footer].join('\n');
}

/**
 * A short fingerprint of a battle, for comparing runs at a glance.
 *
 * FNV-1a, written out rather than taken from `node:crypto`: the sim imports
 * nothing from Node, and `purity.test.ts` enforces that.
 */
export function digestBattle(result: BattleResult): string {
  const text = serializeBattle(result);
  let hash = 0x811c9dc5;

  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }

  return (hash >>> 0).toString(16).padStart(8, '0');
}
