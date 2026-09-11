import { describe, expect, it } from 'vitest';

import { createEventEmitter, unitDefeated } from './events.js';
import type { UnitRef } from './types.js';

const hound: UnitRef = { unitId: 'n-t1-u2', troopId: 'n-t1', side: 'north', typeId: 'cinder-hound' };
const adept: UnitRef = { unitId: 's-t1-u1', troopId: 's-t1', side: 'south', typeId: 'ember-adept' };

describe('the event envelope', () => {
  it('fills a zero swing so every event carries one', () => {
    const emitter = createEventEmitter();

    emitter.emit({ type: 'unitDefeated', tick: 4, position: { x: 1, y: 2 } });

    expect(emitter.events[0].swing).toEqual({
      zoneScore: { north: 0, south: 0 },
      baseHp: { north: 0, south: 0 },
      unitsRemoved: [],
    });
  });

  it('fills empty actors so every event carries them', () => {
    const emitter = createEventEmitter();

    emitter.emit({ type: 'unitDefeated', tick: 4, position: { x: 1, y: 2 } });

    expect(emitter.events[0].actors).toEqual({ source: null, targets: [] });
  });

  it('keeps the tick and position it was given', () => {
    const emitter = createEventEmitter();

    emitter.emit({ type: 'unitDefeated', tick: 9, position: { x: 30, y: 120 } });

    expect(emitter.events[0].tick).toBe(9);
    expect(emitter.events[0].position).toEqual({ x: 30, y: 120 });
  });

  it('keeps events in the order they were emitted', () => {
    const emitter = createEventEmitter();

    emitter.emit({ type: 'unitDefeated', tick: 1, position: { x: 0, y: 0 } });
    emitter.emit({ type: 'unitDefeated', tick: 2, position: { x: 0, y: 0 } });

    expect(emitter.events.map((event) => event.tick)).toEqual([1, 2]);
  });

  it('freezes what it emitted, so a later system cannot rewrite history', () => {
    const emitter = createEventEmitter();
    emitter.emit({ type: 'unitDefeated', tick: 1, position: { x: 0, y: 0 } });

    expect(() => {
      (emitter.events[0] as { tick: number }).tick = 99;
    }).toThrow();
  });

  it('hands the buffer over on drain and starts empty again', () => {
    const emitter = createEventEmitter();
    emitter.emit({ type: 'unitDefeated', tick: 1, position: { x: 0, y: 0 } });

    const drained = emitter.drain();

    expect(drained).toHaveLength(1);
    expect(emitter.events).toHaveLength(0);
  });
});

describe('unitDefeated', () => {
  it('records the defeated unit as removed by the swing', () => {
    const emitter = createEventEmitter();

    emitter.emit(unitDefeated({ tick: 12, position: { x: 5, y: 6 }, unit: hound, killer: adept }));

    const [event] = emitter.events;
    expect(event.type).toBe('unitDefeated');
    expect(event.swing.unitsRemoved).toEqual([hound]);
  });

  it('names the killer as the source and the defeated unit as the target', () => {
    const emitter = createEventEmitter();

    emitter.emit(unitDefeated({ tick: 12, position: { x: 5, y: 6 }, unit: hound, killer: adept }));

    expect(emitter.events[0].actors).toEqual({ source: adept, targets: [hound] });
  });

  it('leaves the source null when nothing killed the unit', () => {
    const emitter = createEventEmitter();

    emitter.emit(unitDefeated({ tick: 12, position: { x: 5, y: 6 }, unit: hound, killer: null }));

    expect(emitter.events[0].actors.source).toBeNull();
  });

  it('leaves zone score and base HP untouched — a defeat moves neither on its own', () => {
    const emitter = createEventEmitter();

    emitter.emit(unitDefeated({ tick: 12, position: { x: 5, y: 6 }, unit: hound, killer: adept }));

    expect(emitter.events[0].swing.zoneScore).toEqual({ north: 0, south: 0 });
    expect(emitter.events[0].swing.baseHp).toEqual({ north: 0, south: 0 });
  });
});
