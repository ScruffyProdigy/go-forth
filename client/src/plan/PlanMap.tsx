/**
 * The plan as a board position, not a form (JQ-293).
 *
 * Geometry follows the JQ-243 plates, which were drawn at true device pixels:
 * a 375-wide portrait map, three zone bands of ~106 px, a base at each end and
 * a deployment strip in front of the player's. Mages are 26-28 px and summons
 * 18-22 px — roughly a 1.8x ratio, which is what makes "where are their mages"
 * answerable at a glance.
 *
 * This deliberately does not share code with JQ-294's battle renderer. The two
 * draw the same map in different states, and factoring across them before the
 * battle renderer exists would be guessing at the shared part.
 */

import { orderLabel, placements } from './derive.ts';
import { type PlanState, type ZoneId, ZONE_IDS } from './types.ts';

const WIDTH = 375;
const ENEMY_BASE_HEIGHT = 48;
const BAND_HEIGHT = 106;
/** Deep enough to show a formation, since the formation is part of the plan. */
const STRIP_HEIGHT = 60;
const OWN_BASE_HEIGHT = 56;
const STRIP_TOP = ENEMY_BASE_HEIGHT + BAND_HEIGHT * 3;
const OWN_BASE_TOP = STRIP_TOP + STRIP_HEIGHT;
const HEIGHT = OWN_BASE_TOP + OWN_BASE_HEIGHT;

// The plate sizes: mages 26-28 px across, summons 18-22 px, ~1.8x ratio.
const MAGE_RADIUS = 13;
const SUMMON_RADIUS = 8;

function bandTop(zone: ZoneId): number {
  return ENEMY_BASE_HEIGHT + ZONE_IDS.indexOf(zone) * BAND_HEIGHT;
}

function bandCentre(zone: ZoneId): number {
  return bandTop(zone) + BAND_HEIGHT / 2;
}

/** Where a troop's lane line ends, in map coordinates. */
function laneEndY(towards: ZoneId | 'ownBase' | 'enemyBase'): number {
  if (towards === 'ownBase') return OWN_BASE_TOP + 14;
  if (towards === 'enemyBase') return ENEMY_BASE_HEIGHT - 10;
  return bandCentre(towards);
}

/**
 * Order labels sit at the destination, which is roomy inside a zone band. The
 * two base orders get their own line clear of the base's own name, so "Defend
 * base" never lands on top of "YOUR BASE".
 */
function orderLabelY(towards: ZoneId | 'ownBase' | 'enemyBase'): number {
  if (towards === 'ownBase') return OWN_BASE_TOP + 14;
  if (towards === 'enemyBase') return ENEMY_BASE_HEIGHT - 6;
  return bandCentre(towards) - 10;
}

export interface PlanMapProps {
  readonly plan: PlanState;
  /** Marks the troop being edited in a drill-down, so the map answers "which one is that". */
  readonly highlightMageId?: string;
}

export function PlanMap({ plan, highlightMageId }: PlanMapProps) {
  const laid = placements(plan);
  const sightings = plan.opponentLastKnown ?? [];

  return (
    <svg
      className="plan-map"
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      role="img"
      aria-label="The plan as a board position"
      preserveAspectRatio="xMidYMid meet"
    >
      <rect x={0} y={0} width={WIDTH} height={HEIGHT} className="map-ground" />

      <g className="map-base map-base-enemy">
        <rect x={0} y={0} width={WIDTH} height={ENEMY_BASE_HEIGHT} />
        <text x={WIDTH / 2} y={ENEMY_BASE_HEIGHT / 2 + 4}>
          THEIR BASE
        </text>
      </g>

      {ZONE_IDS.map((zone) => {
        const sighting = sightings.find((entry) => entry.zone === zone);
        return (
          <g key={zone} className="map-band">
            <rect x={0} y={bandTop(zone)} width={WIDTH} height={BAND_HEIGHT} />
            <text className="map-band-label" x={14} y={bandTop(zone) + 22}>
              {zone}
            </text>
            {sighting ? (
              <text className="map-sighting" x={WIDTH - 14} y={bandTop(zone) + 22}>
                {`last seen ${sighting.mages}m · ${sighting.summons}s`}
              </text>
            ) : null}
          </g>
        );
      })}

      <g className="map-strip">
        <rect x={0} y={STRIP_TOP} width={WIDTH} height={STRIP_HEIGHT} />
      </g>

      <g className="map-base map-base-own">
        <rect x={0} y={OWN_BASE_TOP} width={WIDTH} height={OWN_BASE_HEIGHT} />
        <text x={WIDTH / 2} y={OWN_BASE_TOP + 34}>
          YOUR BASE
        </text>
      </g>

      {laid.map(({ troop, mage, lane, towards, formation }) => {
        const x = lane * WIDTH;
        // Formation follows the order: summons in front (towards the enemy,
        // which is up the screen) for Hold and Defend; mages close behind the
        // line for Push, so they keep resummoning at the front.
        const summonY = STRIP_TOP + (formation === 'summonsForward' ? 18 : 26);
        const mageY = STRIP_TOP + (formation === 'summonsForward' ? 42 : 40);
        const highlighted = highlightMageId === mage.id;

        return (
          <g
            key={mage.id}
            className={highlighted ? 'map-troop map-troop-highlighted' : 'map-troop'}
          >
            <line className="map-lane" x1={x} y1={summonY} x2={x} y2={laneEndY(towards)} />
            <text className="map-order" x={x} y={orderLabelY(towards)}>
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
