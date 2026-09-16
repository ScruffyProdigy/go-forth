/**
 * The plan as a board position, not a form (JQ-293; geometry corrected by JQ-312).
 *
 * It used to draw its own map: three zone bands of ~106 px stacked down a
 * 375-wide portrait board, sized off the JQ-243 plates. That map no longer
 * exists. JQ-376 replaced the stacked bands with two lanes divided west to east,
 * each scored by a mage standing in a hotspot at its centre, and a plan screen
 * still showing bands would have had a player choosing orders against a board
 * the battle then contradicts.
 *
 * So the geometry now comes from `match/geometry.ts` — the same `TWO_LANE_MAP`
 * the battle renderer draws and the sim runs. The original note here said this
 * deliberately shared no code with the battle renderer, because factoring across
 * them before that renderer existed would have been guessing at the shared part.
 * It exists now, and the shared part turned out to be exactly this: *where the
 * map's features are*. What each screen does with them still differs, and that
 * is still not shared.
 *
 * The plan board is always drawn from your own seat, so no camera transform is
 * needed here — your base is at the bottom because you are south of it.
 */

import {
  TWO_LANE_MAP,
  ZONE_NAME,
  hotspotBox,
  zoneCentre,
} from '../match/geometry.ts';
import { orderLabel, placements } from './derive.ts';
import { type PlanState, type ZoneId, ZONE_IDS } from './types.ts';

const MAP = TWO_LANE_MAP;

// The plate sizes: mages 26 px across, summons 16 px — a 1.6x ratio, which is
// what makes "where are their mages" answerable at a glance.
const MAGE_RADIUS = 13;
const SUMMON_RADIUS = 8;

/** Where a troop's lane line ends. A Hold aims at its lane's hotspot. */
function destination(towards: ZoneId | 'ownBase' | 'enemyBase') {
  if (towards === 'ownBase') return { x: MAP.width / 2, y: MAP.bases.south.y - 26 };
  if (towards === 'enemyBase') return { x: MAP.width / 2, y: MAP.bases.north.y + 26 };
  const zone = MAP.zones.find((candidate) => candidate.id === towards);
  return zone ? zoneCentre(zone) : { x: MAP.width / 2, y: MAP.height / 2 };
}

export interface PlanMapProps {
  readonly plan: PlanState;
  /** Marks the troop being edited in a drill-down, so the map answers "which one is that". */
  readonly highlightMageId?: string;
}

export function PlanMap({ plan, highlightMageId }: PlanMapProps) {
  const laid = placements(plan);
  const sightings = plan.opponentLastKnown ?? [];
  const strip = MAP.deployment.south;

  return (
    <svg
      className="plan-map"
      viewBox={`0 0 ${MAP.width} ${MAP.height}`}
      role="img"
      aria-label="The plan as a board position"
      preserveAspectRatio="xMidYMid meet"
    >
      <rect x={0} y={0} width={MAP.width} height={MAP.height} className="map-ground" />

      <g className="map-base map-base-enemy">
        <rect
          x={0}
          y={0}
          width={MAP.width}
          height={MAP.bases.north.y + MAP.baseFootprintRadius}
        />
        <text x={MAP.width / 2} y={MAP.bases.north.y + 4}>
          THEIR BASE
        </text>
      </g>

      {ZONE_IDS.map((zoneId) => {
        const zone = MAP.zones.find((candidate) => candidate.id === zoneId);
        if (!zone) return null;

        const spot = hotspotBox(MAP, zone);
        const sighting = sightings.find((entry) => entry.zone === zoneId);
        const width = zone.extent.end - zone.extent.start;

        return (
          <g key={zoneId} className="map-lane">
            <rect
              x={zone.extent.start}
              y={zone.lane.start}
              width={width}
              height={zone.lane.end - zone.lane.start}
            />
            {/* The hotspot, drawn because it is the thing the lane is scored
                on: a plan that sends nobody who can stand in it scores nothing,
                and that should be visible while the order is being chosen. */}
            <rect
              className="map-hotspot"
              x={spot.x}
              y={spot.y}
              width={spot.width}
              height={spot.height}
            />
            <text className="map-lane-label" x={zone.extent.start + 10} y={zone.lane.start + 22}>
              {ZONE_NAME[zoneId]}
            </text>
            {sighting ? (
              <text
                className="map-sighting"
                x={zone.extent.end - 10}
                y={zone.lane.start + 22}
              >
                {`last seen ${sighting.mages}m · ${sighting.summons}s`}
              </text>
            ) : null}
          </g>
        );
      })}

      <g className="map-strip">
        <rect
          x={0}
          y={strip.lane.start}
          width={MAP.width}
          height={strip.lane.end - strip.lane.start}
        />
      </g>

      <g className="map-base map-base-own">
        <rect
          x={0}
          y={MAP.bases.south.y - MAP.baseFootprintRadius}
          width={MAP.width}
          height={MAP.height - MAP.bases.south.y + MAP.baseFootprintRadius}
        />
        <text x={MAP.width / 2} y={MAP.bases.south.y + 8}>
          YOUR BASE
        </text>
      </g>

      {laid.map(({ troop, mage, lane, towards, formation }) => {
        const x = lane * MAP.width;
        const end = destination(towards);
        // Formation follows the order: summons in front (towards the enemy,
        // which is up the screen) for Hold and Defend; mages close behind the
        // line for Push, so they keep resummoning at the front.
        const summonY = strip.lane.start + (formation === 'summonsForward' ? 18 : 26);
        const mageY = strip.lane.start + (formation === 'summonsForward' ? 42 : 40);
        const highlighted = highlightMageId === mage.id;

        return (
          <g
            key={mage.id}
            className={highlighted ? 'map-troop map-troop-highlighted' : 'map-troop'}
          >
            {/* The line runs to where the order actually sends the troop, which
                is now sideways as often as forwards. */}
            <line className="map-lane-line" x1={x} y1={summonY} x2={end.x} y2={end.y} />
            <text className="map-order" x={end.x} y={end.y - 12}>
              {orderLabel(troop.order)}
            </text>

            {troop.summonIds.map((summonId, index) => {
              const pitch = SUMMON_RADIUS * 2 + 2;
              const spread = (index - (troop.summonIds.length - 1) / 2) * pitch;
              return (
                <circle
                  key={`${summonId}-${index}`}
                  className="map-summon"
                  cx={x + spread}
                  cy={summonY}
                  r={SUMMON_RADIUS}
                />
              );
            })}

            <circle className="map-mage-halo" cx={x} cy={mageY} r={MAGE_RADIUS + 4} />
            <circle className="map-mage" cx={x} cy={mageY} r={MAGE_RADIUS} />
            <title>{`${mage.name} — ${orderLabel(troop.order)}`}</title>
          </g>
        );
      })}
    </svg>
  );
}
