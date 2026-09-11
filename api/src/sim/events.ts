/**
 * The event stream.
 *
 * Designed here, in the first slice, rather than retrofitted: adding emission
 * across three already-written systems later is the cost the parent ticket warns
 * about. Every system emits through the one emitter in the tick context, and
 * every event carries the same envelope — when it happened, where, who was
 * involved, and what it moved.
 *
 * The **swing** is the part that makes the stream worth reading. A highlight reel
 * or a post-battle summary wants "what changed because of this", not "a thing
 * occurred", so every event carries zone-score and base-HP deltas and the units
 * it removed — zeroed when it moved none.
 *
 * `unitDefeated` is the only type slice A has anything to say with. Orders and
 * zone flips arrive with JQ-287, ability casts with JQ-288, resummons and
 * dissolves with JQ-289 — each adding its own member to `BattleEventType`.
 */
import type { Side, UnitRef, Vec2 } from './types.js';

export type BattleEventType = 'unitDefeated';

export interface EventActors {
  /** Who caused it. Null when nothing did — attrition, expiry, a dissolve. */
  readonly source: UnitRef | null;
  /** Who it happened to. */
  readonly targets: readonly UnitRef[];
}

/** What the event moved. Zeroed on an event that moved nothing. */
export interface EventSwing {
  readonly zoneScore: Readonly<Record<Side, number>>;
  readonly baseHp: Readonly<Record<Side, number>>;
  readonly unitsRemoved: readonly UnitRef[];
}

export interface BattleEvent {
  readonly type: BattleEventType;
  readonly tick: number;
  readonly position: Vec2;
  readonly actors: EventActors;
  readonly swing: EventSwing;
}

/** What a system hands the emitter. Everything the envelope adds is optional. */
export interface BattleEventDraft {
  type: BattleEventType;
  tick: number;
  position: Vec2;
  actors?: Partial<EventActors>;
  swing?: Partial<EventSwing>;
}

export interface EventEmitter {
  /** Records an event, filling in the rest of the envelope. */
  emit(draft: BattleEventDraft): BattleEvent;
  /** Everything emitted since the last drain, in emission order. */
  readonly events: readonly BattleEvent[];
  /** Hands the buffer over and starts a fresh one. */
  drain(): BattleEvent[];
}

function completeSwing(swing: Partial<EventSwing> | undefined): EventSwing {
  return Object.freeze({
    zoneScore: Object.freeze({ north: 0, south: 0, ...swing?.zoneScore }),
    baseHp: Object.freeze({ north: 0, south: 0, ...swing?.baseHp }),
    unitsRemoved: Object.freeze([...(swing?.unitsRemoved ?? [])]),
  });
}

function completeActors(actors: Partial<EventActors> | undefined): EventActors {
  return Object.freeze({
    source: actors?.source ?? null,
    targets: Object.freeze([...(actors?.targets ?? [])]),
  });
}

/** The single emitter every system writes through. One per battle. */
export function createEventEmitter(): EventEmitter {
  let buffer: BattleEvent[] = [];

  return {
    emit(draft: BattleEventDraft): BattleEvent {
      const event: BattleEvent = Object.freeze({
        type: draft.type,
        tick: draft.tick,
        position: Object.freeze({ x: draft.position.x, y: draft.position.y }),
        actors: completeActors(draft.actors),
        swing: completeSwing(draft.swing),
      });
      buffer.push(event);
      return event;
    },
    get events(): readonly BattleEvent[] {
      return buffer;
    },
    drain(): BattleEvent[] {
      const drained = buffer;
      buffer = [];
      return drained;
    },
  };
}

/** The first event type: a unit reached 0 HP and left the field. */
export function unitDefeated(input: {
  tick: number;
  position: Vec2;
  unit: UnitRef;
  killer: UnitRef | null;
}): BattleEventDraft {
  return {
    type: 'unitDefeated',
    tick: input.tick,
    position: input.position,
    actors: { source: input.killer, targets: [input.unit] },
    swing: { unitsRemoved: [input.unit] },
  };
}
