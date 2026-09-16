import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { TWO_LANE_MAP, zoneCentre, zoneGeometry } from '../geometry.ts';
import type { BaseHp, BattleSnapshot, BattleUnit, LoadoutSpell, MapPoint, Side } from '../types.ts';
import { BattleMap } from './BattleMap.tsx';

const MAP = TWO_LANE_MAP;
const WEST = zoneGeometry(MAP, 'W');
const EAST = zoneGeometry(MAP, 'E');

const FULL_BASES: Record<Side, BaseHp> = {
  north: { hp: 1000, maxHp: 1000 },
  south: { hp: 1000, maxHp: 1000 },
};

function mage(id: string, side: Side, at: MapPoint, charge?: number): BattleUnit {
  return {
    id,
    kind: 'mage',
    side,
    typeName: 'Emberwright',
    position: at,
    hp: 120,
    maxHp: 120,
    protection: 6,
    ...(charge === undefined
      ? {}
      : { ability: { id: `${id}-a`, name: 'Ember Nova', charge } }),
  };
}

function summon(id: string, side: Side, at: MapPoint): BattleUnit {
  return {
    id,
    kind: 'summon',
    side,
    typeName: 'Flame Wisp',
    position: at,
    hp: 40,
    maxHp: 60,
    protection: 0,
  };
}

function snapshot(overrides: Partial<BattleSnapshot> = {}): BattleSnapshot {
  return {
    tick: 100,
    units: [],
    zones: [
      { id: 'W', heldBy: null },
      { id: 'E', heldBy: null },
    ],
    zoneScore: { north: 0, south: 0 },
    energy: 10,
    loadout: [],
    casts: [],
    events: [],
    ...overrides,
  };
}

function draw(snap: BattleSnapshot, props: Partial<Parameters<typeof BattleMap>[0]> = {}) {
  return render(<BattleMap snapshot={snap} you="south" baseHp={FULL_BASES} {...props} />);
}

describe('the board', () => {
  it('draws the two lanes the sim actually runs, with their hotspots', () => {
    draw(snapshot());

    expect(screen.getByTestId('zone-chip-W')).toBeInTheDocument();
    expect(screen.getByTestId('zone-chip-E')).toBeInTheDocument();
    // The three stacked bands are gone; a third chip would mean the client had
    // drifted back off the server's map (JQ-376).
    expect(screen.queryByTestId('zone-chip-A')).not.toBeInTheDocument();
  });

  it('keeps both bases on screen whatever else is happening', () => {
    draw(snapshot(), {
      baseHp: { north: { hp: 250, maxHp: 1000 }, south: { hp: 1000, maxHp: 1000 } },
    });

    const board = screen.getByRole('img', { name: /Battle at tick/ });
    expect(within(board).getByText('YOUR BASE')).toBeInTheDocument();
    expect(within(board).getByText('THEIR BASE')).toBeInTheDocument();
    expect(within(board).getByText('250 / 1000')).toBeInTheDocument();
  });

  it('names the holder of each lane from the authoritative state', () => {
    draw(
      snapshot({
        zones: [
          { id: 'W', heldBy: 'south' },
          { id: 'E', heldBy: 'north' },
        ],
      }),
    );

    expect(screen.getByTestId('zone-chip-W')).toHaveTextContent('West · Yours');
    expect(screen.getByTestId('zone-chip-E')).toHaveTextContent('East · Theirs');
  });
});

describe('unit marks', () => {
  it('draws no per-unit health bar, however hurt the unit is', () => {
    const { container } = draw(snapshot({ units: [summon('s1', 'south', zoneCentre(WEST))] }));

    // Forty moving two-pixel rectangles is texture, not information — the tap
    // panel answers the question instead (JQ-312 AC 2).
    expect(container.querySelector('.unit-hp')).toBeNull();
  });

  it('rings a mage only once its ability is nearly charged', () => {
    draw(
      snapshot({
        units: [
          mage('cold', 'south', { x: 60, y: 300 }, 0.4),
          mage('warm', 'south', { x: 90, y: 300 }, 0.75),
          mage('ready', 'south', { x: 120, y: 300 }, 1),
        ],
      }),
    );

    expect(screen.queryByTestId('energy-ring-cold')).not.toBeInTheDocument();
    expect(screen.getByTestId('energy-ring-warm')).toBeInTheDocument();
    expect(screen.getByTestId('energy-ring-ready')).toBeInTheDocument();
  });

  it('does not ring a summon, which has no ability to warn about', () => {
    draw(snapshot({ units: [summon('s1', 'south', zoneCentre(WEST))] }));

    expect(screen.queryByTestId('energy-ring-s1')).not.toBeInTheDocument();
  });
});

describe('tap to inspect', () => {
  it('shows nothing until something is tapped', () => {
    draw(snapshot({ units: [summon('s1', 'south', zoneCentre(WEST))] }));

    expect(screen.queryByTestId('unit-inspector')).not.toBeInTheDocument();
  });

  it('answers “what is that, and is it nearly dead” for the unit tapped', () => {
    const { container } = draw(snapshot({ units: [summon('s1', 'south', zoneCentre(WEST))] }));

    tapMap(container, zoneCentre(WEST));

    const panel = screen.getByTestId('unit-inspector');
    expect(panel).toHaveTextContent('Flame Wisp');
    expect(within(panel).getByTestId('inspector-health')).toHaveTextContent('40 / 60');
  });

  it('says how close an ability is rather than showing the raw gauge', () => {
    const { container } = draw(
      snapshot({ units: [mage('m1', 'north', zoneCentre(EAST), 0.8)] }),
    );

    tapMap(container, zoneCentre(EAST));

    const ability = screen.getByTestId('inspector-ability');
    expect(ability).toHaveTextContent('Ember Nova');
    expect(ability).toHaveTextContent('80% charged');
    expect(ability).toHaveTextContent('about to fire');
  });

  it('closes when empty ground is tapped', () => {
    const { container } = draw(snapshot({ units: [summon('s1', 'south', zoneCentre(WEST))] }));

    tapMap(container, zoneCentre(WEST));
    expect(screen.getByTestId('unit-inspector')).toBeInTheDocument();

    tapMap(container, { x: 187.5, y: 60 });
    expect(screen.queryByTestId('unit-inspector')).not.toBeInTheDocument();
  });

  it('states protection only when the server stated it', () => {
    const unstated: BattleUnit = { ...summon('s1', 'south', zoneCentre(WEST)), protection: undefined };
    const { container } = draw(snapshot({ units: [unstated] }));

    tapMap(container, zoneCentre(WEST));

    // Showing an absent value as "0 protection" would be the client inventing
    // the fact the outcome preview deliberately refuses to invent.
    expect(screen.getByTestId('inspector-health')).not.toHaveTextContent('protection');
  });
});

describe('the lane strip', () => {
  it('repeats each lane’s state where a thumb cannot cover it', () => {
    draw(
      snapshot({
        zones: [
          { id: 'W', heldBy: 'south' },
          { id: 'E', heldBy: null },
        ],
        units: [mage('m1', 'south', zoneCentre(WEST))],
      }),
    );

    expect(screen.getByTestId('zone-strip-W')).toHaveTextContent('Yours');
    expect(screen.getByTestId('zone-strip-E')).toHaveTextContent('Open');
  });

  it('explains a lane full of your units that is scoring nothing', () => {
    // Four summons in the lane and no mage on the spot holds nothing, and a
    // player who cannot see why would think the board was wrong.
    const corner = { x: WEST.extent.start + 20, y: WEST.lane.start + 20 };
    draw(
      snapshot({
        zones: [
          { id: 'W', heldBy: null },
          { id: 'E', heldBy: null },
        ],
        units: [summon('s1', 'south', corner), summon('s2', 'south', corner)],
      }),
    );

    expect(screen.getByTestId('zone-strip-W')).toHaveTextContent('2 v 0');
    expect(screen.getByTestId('zone-strip-W')).toHaveTextContent('hotspot empty');
  });

  it('stops saying the hotspot is empty once a mage is standing on it', () => {
    draw(snapshot({ units: [mage('m1', 'south', zoneCentre(WEST))] }));

    expect(screen.getByTestId('zone-strip-W')).not.toHaveTextContent('hotspot empty');
  });
});

describe('what just happened', () => {
  it('shows an ability firing, a resummon and a troop coming apart', () => {
    draw(
      snapshot({
        tick: 100,
        events: [
          { id: 'e1', type: 'abilityCast', tick: 98, at: zoneCentre(WEST), side: 'south', subject: 'Ember Nova' },
          { id: 'e2', type: 'resummon', tick: 95, at: zoneCentre(WEST), side: 'south' },
          { id: 'e3', type: 'troopDissolve', tick: 90, at: zoneCentre(EAST), side: 'north', count: 3 },
        ],
      }),
    );

    expect(screen.getByTestId('event-abilityCast')).toBeInTheDocument();
    expect(screen.getByTestId('event-resummon')).toBeInTheDocument();
    expect(screen.getByTestId('event-troopDissolve')).toBeInTheDocument();
  });

  it('lets an old event fall off the board', () => {
    draw(
      snapshot({
        tick: 200,
        events: [
          { id: 'e1', type: 'abilityCast', tick: 100, at: zoneCentre(WEST), side: 'south' },
        ],
      }),
    );

    expect(screen.queryByTestId('event-abilityCast')).not.toBeInTheDocument();
  });
});

describe('aiming a spell', () => {
  const fireball: LoadoutSpell = {
    spellId: 'fireball',
    name: 'Fireball',
    cost: 3,
    effect: 'A burst.',
    magnitude: 80,
    radius: 60,
  };

  it('offers the map’s own landmarks, each carrying what it would do', () => {
    draw(
      snapshot({
        units: [summon('e1', 'north', zoneCentre(WEST))],
      }),
      { targeting: fireball },
    );

    expect(screen.getByTestId('cast-prompt')).toHaveTextContent('Where should Fireball land?');
    expect(screen.getByTestId('preview-zone-W')).toHaveTextContent('Clears the lane');
    expect(screen.getByTestId('preview-zone-E')).toHaveTextContent('Nothing in range');
  });

  it('says what a region is short by instead of only greying it out', () => {
    draw(snapshot({ energy: 1 }), { targeting: fireball });

    expect(screen.getByTestId('preview-zone-W')).toHaveTextContent('Needs 2.0 more energy');
    expect(screen.getByRole('button', { name: /West lane/ })).toBeDisabled();
  });

  it('offers no estimate for a spell the server has not resolved', () => {
    const unresolved: LoadoutSpell = { spellId: 'f', name: 'Fireball', cost: 3, effect: 'A burst.' };
    draw(snapshot({ units: [summon('e1', 'north', zoneCentre(WEST))] }), { targeting: unresolved });

    expect(screen.getByTestId('preview-zone-W')).toHaveTextContent('not resolved');
  });

  it('turns the tap layer off while aiming, so a tap picks a target', () => {
    const { container } = draw(snapshot(), { targeting: fireball });

    expect(container.querySelector('.map-tap-layer')).toBeNull();
  });
});

/* ------------------------------------------------------------------ helpers -- */

/**
 * jsdom gives every element a zero-size bounding box, so the component's own
 * `getBoundingClientRect` would refuse the tap. Stubbing it to a 375x475 phone
 * is what lets the coordinate path be exercised at all — and `hitTest.test.ts`
 * covers the arithmetic itself against several rects.
 */
function tapMap(container: HTMLElement, at: MapPoint): void {
  const svg = container.querySelector('svg');
  const layer = container.querySelector('.map-tap-layer');
  if (!svg || !layer) throw new Error('no tap layer on the board');

  const width = 375;
  const height = 475;
  const scale = Math.min(width / MAP.width, height / MAP.height);
  const offsetX = (width - MAP.width * scale) / 2;

  svg.getBoundingClientRect = () =>
    ({ left: 0, top: 0, width, height, right: width, bottom: height, x: 0, y: 0 }) as DOMRect;

  fireEvent.click(layer, {
    clientX: at.x * scale + offsetX,
    clientY: at.y * scale,
  });
}
