/**
 * The battle, as the server has it, readable at density (JQ-312).
 *
 * JQ-311 put an authoritative board on screen. This makes it one you can play a
 * round on with twenty units a side, on a phone, with your thumb over the bottom
 * third of it — JQ-243's findings applied rather than re-derived.
 *
 * What this ticket changed, and why each is not a style preference:
 *
 *  1. **The map is the one the sim actually runs.** Two lanes divided west to
 *     east with a hotspot at each centre (JQ-376), not three stacked bands. The
 *     bands were still being drawn here after the sim stopped producing them, so
 *     the board was lying about where the round was being decided.
 *  2. **Marks clear 16 px on glass, not in map units.** The map shrinks to make
 *     room for the cast bar, so a radius in map units is not a size — see
 *     `marks.ts`. The scale is measured and the floor applied to it.
 *  3. **No per-unit health bars. Tap to inspect instead.** Twenty bars a side is
 *     forty moving two-pixel rectangles, which is texture, not information. A
 *     tap answers the question that was actually being asked — "what is that,
 *     and is it nearly dead" — for the one unit being asked about.
 *  4. **Energy rings only above 70%.** A ring on every mage all round is chrome
 *     you stop seeing. A ring that appears shortly before the ability fires is a
 *     warning, and both players get it.
 *  5. **Previews never claim a clear they cannot support.** `preview.ts` holds
 *     the rule; the map only draws its answer.
 *
 * Three things inherited from JQ-311 survive that rework and should keep
 * surviving: your base is always at the bottom (the seat decides the drawing,
 * never the state), base HP is on screen for both sides always, and the chip
 * corner of every zone is reserved in *world* space so the sim's placement and
 * this renderer agree about what may be drawn where.
 */

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';

import {
  type Box,
  type MapGeometry,
  type TargetRegion,
  TWO_LANE_MAP,
  ZONE_NAME,
  boxToScreen,
  chipBox,
  hotspotBox,
  targetRegions,
  toScreen,
} from '../geometry.ts';
import type {
  BaseHp,
  BattleEvent,
  BattleSnapshot,
  BattleUnit,
  LoadoutSpell,
  MapPoint,
  Side,
  ZoneState,
} from '../types.ts';
import { opposing } from '../types.ts';
import { nearestUnit, pointerToMap } from './hitTest.ts';
import { markRadii, showsEnergyRing } from './marks.ts';
import { type OutcomePreview, previewsFor } from './preview.ts';
import { UnitInspector } from './UnitInspector.tsx';
import { ZoneStrip } from './ZoneStrip.tsx';

/** How long an event stays on the board, in ticks. Two seconds at 20 Hz. */
const EVENT_LINGER_TICKS = 40;

export interface BattleMapProps {
  readonly snapshot: BattleSnapshot;
  readonly you: Side;
  readonly baseHp: Readonly<Record<Side, BaseHp>>;
  /** Set while a spell is armed: the map becomes a target picker. */
  readonly targeting?: LoadoutSpell | null;
  readonly onTarget?: (region: TargetRegion) => void;
  readonly onCancelTarget?: () => void;
  readonly map?: MapGeometry;
  /** Dims the whole board when the state on screen is known to be out of date. */
  readonly stale?: boolean;
}

export function BattleMap({
  snapshot,
  you,
  baseHp,
  targeting = null,
  onTarget,
  onCancelTarget,
  map = TWO_LANE_MAP,
  stale = false,
}: BattleMapProps) {
  const them = opposing(you);
  const regions = targetRegions(you, map);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const scale = useMapScale(svgRef, map);
  const radii = markRadii(scale);
  const moving = useBoardMoving(snapshot);

  const [inspectedId, setInspectedId] = useState<string | null>(null);
  const inspected = snapshot.units.find((unit) => unit.id === inspectedId) ?? null;

  // A unit that dies while being inspected takes its panel with it, rather than
  // leaving a card describing something no longer on the board.
  useEffect(() => {
    if (inspectedId !== null && inspected === null) setInspectedId(null);
  }, [inspectedId, inspected]);

  const previews = targeting
    ? previewsFor({ snapshot, you, map, spell: targeting, stale, moving }, regions)
    : [];

  const inspect = useCallback(
    (event: React.MouseEvent<SVGRectElement>) => {
      const svg = svgRef.current;
      if (!svg) return;
      const at = pointerToMap(event.clientX, event.clientY, svg.getBoundingClientRect(), map, you);
      if (!at) return;

      const hit = nearestUnit(snapshot.units, at, radii.tap);
      setInspectedId(hit ? hit.id : null);
    },
    [snapshot.units, map, you, radii.tap],
  );

  const recent = snapshot.events.filter(
    (event) => snapshot.tick - event.tick <= EVENT_LINGER_TICKS,
  );

  return (
    <div className={stale ? 'battle-map is-stale' : 'battle-map'}>
      {/*
        The board and its panels share one box, and the panels are drawn *over*
        it rather than beside it. A panel that took its own height would shrink
        the map every time a unit was tapped — the marks would resize, the whole
        board would jump, and "fixed full-screen map, preserve camera transform"
        (JQ-312 AC 1) would be false of exactly the interaction the ticket adds.
      */}
      {/*
        The lane strip goes *above* the board, not below it.
        It exists to stay readable when a thumb is over the map — and a thumb on
        a phone reaches up from the bottom, so below the board it would sit in
        the one band of screen the hand is always in, right next to the cast bar
        it is reaching for. The top of the screen is the part a thumb never
        covers (JQ-312 AC 6, thumb occlusion).
      */}
      <ZoneStrip snapshot={snapshot} you={you} map={map} />

      <div className="battle-board">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${map.width} ${map.height}`}
        role="img"
        aria-label={`Battle at tick ${snapshot.tick}`}
        preserveAspectRatio="xMidYMid meet"
      >
        <rect x={0} y={0} width={map.width} height={map.height} className="map-ground" />

        {/* Their base at the top, yours at the bottom — always, on both phones. */}
        <BasePlate side="enemy" at={toScreen(map.bases[them], you, map)} map={map} hp={baseHp[them]} />
        <BasePlate side="own" at={toScreen(map.bases[you], you, map)} map={map} hp={baseHp[you]} />

        {/* Deployment strips stay drawn. They are where a plan you locked in is
            still standing, and collapsing them to a line loses the one part of
            the board that explains why the front is where it is. */}
        {(['north', 'south'] as const).map((side) => {
          const strip = map.deployment[side];
          const box = boxToScreen(
            {
              x: strip.extent.start,
              y: strip.lane.start,
              width: strip.extent.end - strip.extent.start,
              height: strip.lane.end - strip.lane.start,
            },
            you,
            map,
          );
          return (
            <g key={side} className={side === you ? 'map-strip is-own' : 'map-strip is-enemy'}>
              <rect x={box.x} y={box.y} width={box.width} height={box.height} />
              {/* Divided at the lane boundaries, so a column in the strip reads
                  as belonging to the lane it is about to walk into. */}
              {map.zones.map((zone) => {
                const edge = boxToScreen(
                  { x: zone.extent.end, y: strip.lane.start, width: 0, height: 0 },
                  you,
                  map,
                );
                return (
                  <line
                    key={zone.id}
                    className="map-strip-divide"
                    x1={edge.x}
                    y1={box.y}
                    x2={edge.x}
                    y2={box.y + box.height}
                  />
                );
              })}
            </g>
          );
        })}

        {map.zones.map((zone) => {
          const lane = boxToScreen(
            {
              x: zone.extent.start,
              y: zone.lane.start,
              width: zone.extent.end - zone.extent.start,
              height: zone.lane.end - zone.lane.start,
            },
            you,
            map,
          );
          const hotspot = boxToScreen(hotspotBox(map, zone), you, map);
          const state = snapshot.zones.find((entry) => entry.id === zone.id);
          const held = holdClass(state, you);

          return (
            <g key={zone.id} className={`battle-lane ${held}`}>
              <rect
                className="lane-ground"
                x={lane.x}
                y={lane.y}
                width={lane.width}
                height={lane.height}
              />
              {/* The hotspot is the thing being fought over. Drawn as its own
                  square because "held" is a mage standing in *this*, not
                  anywhere in the lane. */}
              <rect
                className="lane-hotspot"
                x={hotspot.x}
                y={hotspot.y}
                width={hotspot.width}
                height={hotspot.height}
              />
            </g>
          );
        })}

        {snapshot.casts.map((cast) => {
          const at = toScreen(cast.at, you, map);
          return (
            <circle
              key={cast.commandId}
              className={cast.castBy === you ? 'cast-mark is-yours' : 'cast-mark'}
              cx={at.x}
              cy={at.y}
              r={28}
            />
          );
        })}

        {recent.map((event) => (
          <EventMark
            key={event.id}
            event={event}
            you={you}
            map={map}
            radius={radii.mage}
            age={(snapshot.tick - event.tick) / EVENT_LINGER_TICKS}
          />
        ))}

        {snapshot.units.map((unit) => (
          <UnitMark
            key={unit.id}
            unit={unit}
            you={you}
            map={map}
            radii={radii}
            selected={unit.id === inspectedId}
          />
        ))}

        {/* Chips last, so they are on top of everything.
            JQ-287 already clears units out of this box in world space, which is
            what stops a formation forming up under a chip. Drawing them above
            the marks as well is the renderer's half of the same guarantee: a
            unit merely *walking* through the corner must not be able to hide
            the one thing on the board that says who is winning the lane. */}
        {map.zones.map((zone) => (
          <ZoneChip
            key={zone.id}
            zone={zone.id}
            state={snapshot.zones.find((entry) => entry.id === zone.id)}
            you={you}
            box={boxToScreen(chipBox(map, zone), you, map)}
          />
        ))}

        {targeting
          ? previews.map((preview) => {
              const at = toScreen(preview.region.at, you, map);
              const radius = targeting.radius ?? map.hotspotSize;
              return (
                <circle
                  key={preview.region.id}
                  className={
                    preview.estimate?.clearsZone
                      ? 'target-preview clears'
                      : preview.affordable
                        ? 'target-preview'
                        : 'target-preview is-short'
                  }
                  cx={at.x}
                  cy={at.y}
                  r={radius}
                />
              );
            })
          : null}

        {/* The tap layer sits above the marks so a tap anywhere on the board is
            resolved to the *nearest* unit rather than needing to land on one —
            at twenty a side no mark is a 44 px target, and asking a thumb to hit
            an 16 px circle is asking it to miss. */}
        {targeting ? null : (
          <rect
            className="map-tap-layer"
            x={0}
            y={0}
            width={map.width}
            height={map.height}
            onClick={inspect}
          />
        )}
      </svg>

      {targeting ? (
        <TargetPicker
          spell={targeting}
          previews={previews}
          onTarget={onTarget}
          onCancel={onCancelTarget}
        />
      ) : inspected ? (
        <UnitInspector unit={inspected} you={you} onClose={() => setInspectedId(null)} />
      ) : null}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ parts -- */

function UnitMark({
  unit,
  you,
  map,
  radii,
  selected,
}: {
  readonly unit: BattleUnit;
  readonly you: Side;
  readonly map: MapGeometry;
  readonly radii: { readonly mage: number; readonly summon: number };
  readonly selected: boolean;
}) {
  const at = toScreen(unit.position, you, map);
  const mine = unit.side === you;
  const radius = unit.kind === 'mage' ? radii.mage : radii.summon;
  const ring = showsEnergyRing(unit.ability?.charge);

  return (
    <g
      className={[
        'unit',
        mine ? 'is-yours' : 'is-theirs',
        unit.kind === 'mage' ? 'is-mage' : 'is-summon',
        selected ? 'is-selected' : '',
      ]
        .filter(Boolean)
        .join(' ')}
      data-testid={`unit-${unit.id}`}
    >
      {/* Shape carries the side as well as colour does, so the board is still
          readable to someone who cannot tell the two hues apart. */}
      {mine ? (
        <circle cx={at.x} cy={at.y} r={radius} />
      ) : (
        <rect
          x={at.x - radius}
          y={at.y - radius}
          width={radius * 2}
          height={radius * 2}
          transform={`rotate(45 ${at.x} ${at.y})`}
        />
      )}

      {ring ? (
        <circle
          className="unit-energy-ring"
          data-testid={`energy-ring-${unit.id}`}
          cx={at.x}
          cy={at.y}
          r={ringRadius(radius)}
        />
      ) : null}

      {selected ? (
        <circle className="unit-selected-ring" cx={at.x} cy={at.y} r={ringRadius(radius) + 4} />
      ) : null}

      {/* No health bar. The title is still here for pointer and screen-reader
          users; the tap panel is the answer on a phone. */}
      <title>{`${unit.typeName} — ${Math.round(unit.hp)}/${unit.maxHp}`}</title>
    </g>
  );
}

/**
 * An ability firing, a resummon, or a troop coming apart.
 *
 * Marks fade over `EVENT_LINGER_TICKS` rather than vanishing, so something that
 * happened while your thumb was over the board is still on screen when it moves.
 */
function EventMark({
  event,
  you,
  map,
  radius,
  age,
}: {
  readonly event: BattleEvent;
  readonly you: Side;
  readonly map: MapGeometry;
  readonly radius: number;
  readonly age: number;
}) {
  if (!SHOWN_EVENTS.includes(event.type)) return null;

  const at = toScreen(event.at, you, map);
  const mine = event.side === you;
  const fade = Math.max(0, 1 - age);

  return (
    <g
      className={`event-mark is-${event.type} ${mine ? 'is-yours' : 'is-theirs'}`}
      data-testid={`event-${event.type}`}
      opacity={fade}
    >
      {event.type === 'troopDissolve' ? (
        // A dissolve is a troop ceasing to exist, so it reads as a break, not a
        // flash: an open ring with a slash through it.
        <>
          <circle className="event-ring" cx={at.x} cy={at.y} r={radius * 2} />
          <line
            className="event-slash"
            x1={at.x - radius}
            y1={at.y - radius}
            x2={at.x + radius}
            y2={at.y + radius}
          />
        </>
      ) : (
        <circle className="event-ring" cx={at.x} cy={at.y} r={radius * (1 + age)} />
      )}
    </g>
  );
}

const SHOWN_EVENTS: readonly BattleEvent['type'][] = ['abilityCast', 'resummon', 'troopDissolve'];

/**
 * Where a ring sits around a mark. Proportional, not a flat four units: the
 * marks grow when the map is short (`marks.ts`), and a fixed gap would leave a
 * grown mark wearing its ring as a rim rather than as a halo around it.
 */
function ringRadius(markRadius: number): number {
  return markRadius + Math.max(4, markRadius * 0.28);
}

function BasePlate({
  side,
  at,
  map,
  hp,
}: {
  readonly side: 'own' | 'enemy';
  readonly at: MapPoint;
  readonly map: MapGeometry;
  readonly hp: BaseHp;
}) {
  const share = Math.max(0, hp.hp / hp.maxHp);
  const label = side === 'own' ? 'YOUR BASE' : 'THEIR BASE';
  // Compact, but never collapsed: the plate runs from the edge of the screen to
  // the far side of the base's own footprint, so "a unit has reached the base"
  // is something you can see rather than infer. `at` is already through the
  // camera, so the enemy plate is the one at the top for both seats.
  const height =
    side === 'enemy' ? at.y + map.baseFootprintRadius : map.height - at.y + map.baseFootprintRadius;
  const y = side === 'enemy' ? 0 : map.height - height;

  return (
    <g className={`base-plate ${side === 'own' ? 'is-own' : 'is-enemy'}`} data-testid={`base-${side}`}>
      <rect x={0} y={y} width={map.width} height={height} />
      <circle className="base-footprint" cx={at.x} cy={at.y} r={map.baseFootprintRadius} />
      <rect className="base-hp-track" x={12} y={y + height - 12} width={map.width - 24} height={6} />
      <rect
        className="base-hp-fill"
        x={12}
        y={y + height - 12}
        width={(map.width - 24) * share}
        height={6}
      />
      <text x={12} y={y + height - 18}>
        {label}
      </text>
      <text className="base-hp-value" x={map.width - 12} y={y + height - 18}>
        {`${Math.round(hp.hp)} / ${hp.maxHp}`}
      </text>
    </g>
  );
}

function holdClass(state: ZoneState | undefined, you: Side): string {
  if (!state || state.heldBy === null) return 'held-none';
  return state.heldBy === you ? 'held-you' : 'held-them';
}

function ZoneChip({
  zone,
  state,
  you,
  box,
}: {
  readonly zone: string;
  readonly state: ZoneState | undefined;
  readonly you: Side;
  readonly box: Box;
}) {
  const heldBy = state?.heldBy ?? null;
  const held = heldBy === null ? 'Open' : heldBy === you ? 'Yours' : 'Theirs';

  return (
    <g className={`zone-chip ${holdClass(state, you)}`} data-testid={`zone-chip-${zone}`}>
      <rect x={box.x} y={box.y} width={box.width} height={box.height} />
      <text x={box.x + 8} y={box.y + 17}>{`${ZONE_NAME[zone as 'W' | 'E'] ?? zone} · ${held}`}</text>
    </g>
  );
}

/**
 * The second tap of the two.
 *
 * Targets are regions, not pixels: a spell lands at a location, and on a phone
 * the location a thumb can actually pick is "the west lane" or "their base"
 * rather than a coordinate the player has to hit through their own finger.
 *
 * Each one carries what it would do, which is the JQ-312 half — the player is
 * choosing between outcomes, not between place names.
 */
function TargetPicker({
  spell,
  previews,
  onTarget,
  onCancel,
}: {
  readonly spell: LoadoutSpell;
  readonly previews: readonly OutcomePreview[];
  readonly onTarget?: (region: TargetRegion) => void;
  readonly onCancel?: () => void;
}) {
  return (
    <div className="targeting">
      <p className="cast-prompt" data-testid="cast-prompt">
        {`Where should ${spell.name} land?`}
      </p>
      <ul className="target-regions" aria-label={`Where should ${spell.name} land?`}>
        {previews.map((preview) => (
          <li key={preview.region.id}>
            <button
              type="button"
              className="target-region"
              disabled={!preview.affordable}
              onClick={() => onTarget?.(preview.region)}
            >
              <span className="target-region-label">{preview.region.label}</span>
              <span
                className={`target-region-outcome is-${preview.confidence}`}
                data-testid={`preview-${preview.region.id}`}
              >
                {preview.affordable
                  ? preview.summary
                  : `Needs ${preview.shortfall.toFixed(1)} more energy.`}
              </span>
            </button>
          </li>
        ))}
        <li>
          <button type="button" className="target-cancel" onClick={() => onCancel?.()}>
            Cancel
          </button>
        </li>
      </ul>
    </div>
  );
}

/* ------------------------------------------------------------------ hooks -- */

/**
 * Pixels per map unit, measured rather than assumed.
 *
 * The map's size on glass is decided by the layout around it — the header, the
 * zone strip, the cast bar — and those differ between a 375x667 phone and a
 * 393x852 one. `marks.ts` needs the real number to apply JQ-243's pixel floor,
 * so it is observed here and recomputed whenever the box changes.
 */
function useMapScale(
  ref: React.RefObject<SVGSVGElement | null>,
  map: MapGeometry,
): number {
  const [scale, setScale] = useState(0);

  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;

    const measure = () => {
      const rect = element.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return;
      // `xMidYMid meet` fits the whole viewBox, so the scale is the tighter axis.
      setScale(Math.min(rect.width / map.width, rect.height / map.height));
    };

    measure();

    // jsdom has no ResizeObserver. The initial measure is what tests read, and
    // a phone that never resizes mid-battle is the normal case anyway.
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref, map.width, map.height]);

  return scale;
}

/**
 * Whether anything moved since the previous snapshot.
 *
 * Feeds the preview's hedge: positions from a board in motion are already old by
 * the time a thumb reaches the button, and saying so is more honest than
 * presenting a number computed from them as settled.
 */
function useBoardMoving(snapshot: BattleSnapshot): boolean {
  const previous = useRef<BattleSnapshot | null>(null);
  const moving = useRef(false);

  if (previous.current && previous.current.tick !== snapshot.tick) {
    moving.current = snapshot.units.some((unit) => {
      const before = previous.current?.units.find((candidate) => candidate.id === unit.id);
      return (
        before !== undefined &&
        (before.position.x !== unit.position.x || before.position.y !== unit.position.y)
      );
    });
  }
  previous.current = snapshot;

  return moving.current;
}
