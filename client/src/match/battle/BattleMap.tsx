/**
 * The battle, as the server has it (JQ-311).
 *
 * Scope, deliberately narrow: JQ-311 integrates a battle map, it does not design
 * one. **JQ-312 owns readability at density** — occupancy chips, mage energy
 * rings, tap-to-inspect, the twenty-a-side case from JQ-243. This draws the
 * authoritative state plainly enough to play the opening round and be reviewed
 * on a phone, and it holds the seam that work slots into.
 *
 * Three things here are not placeholders and should survive that replacement:
 *
 *  1. **Your base is always at the bottom.** Both phones look at one world; the
 *     seat decides which way it is drawn (`toScreen`). Nothing in the state is
 *     flipped — only the drawing.
 *  2. **Base HP is on screen for both sides, always.** The match is won by three
 *     rounds *or* a destroyed base, and base damage persists between rounds, so
 *     a player who cannot see the bases cannot see the game they are playing
 *     (Ryan, 2026-09-13).
 *  3. **The top-left 115x25 of every zone band is reserved** for that zone's
 *     state chip, and nothing else is ever drawn there — JQ-287 places units
 *     around that reservation, so a renderer that used it would collide with the
 *     sim's own layout.
 */

import {
  THREE_ZONE_MAP,
  type MapGeometry,
  type TargetRegion,
  targetRegions,
  toScreen,
} from '../geometry.ts';
import type { BaseHp, BattleSnapshot, Side, ZoneState } from '../types.ts';
import { opposing } from '../types.ts';

/** JQ-287 reserves this box at each zone band's top-left for the state chip. */
const CHIP_WIDTH = 115;
const CHIP_HEIGHT = 25;

const MAGE_RADIUS = 13;
/** 16 px across is the JQ-243 floor for the smallest mark on a phone. */
const SUMMON_RADIUS = 8;

export interface BattleMapProps {
  readonly snapshot: BattleSnapshot;
  readonly you: Side;
  readonly baseHp: Readonly<Record<Side, BaseHp>>;
  /** Set while a spell is armed: the map becomes a target picker. */
  readonly targeting?: { readonly spellName: string; readonly radius: number } | null;
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
  map = THREE_ZONE_MAP,
  stale = false,
}: BattleMapProps) {
  const them = opposing(you);
  const regions = targetRegions(you, map);

  return (
    <div className={stale ? 'battle-map is-stale' : 'battle-map'}>
      <svg
        viewBox={`0 0 ${map.width} ${map.height}`}
        role="img"
        aria-label={`Battle at tick ${snapshot.tick}`}
        preserveAspectRatio="xMidYMid meet"
      >
        <rect x={0} y={0} width={map.width} height={map.height} className="map-ground" />

        {/* Their base at the top, yours at the bottom — always, on both phones. */}
        <BaseBand
          side="enemy"
          y={0}
          height={map.bases.north.y * 2}
          width={map.width}
          hp={baseHp[them]}
        />
        <BaseBand
          side="own"
          y={map.height - (map.height - map.bases.south.y) * 2}
          height={(map.height - map.bases.south.y) * 2}
          width={map.width}
          hp={baseHp[you]}
        />

        {map.zones.map((zone) => {
          const band = zoneBandOnScreen(zone.lane, you, map);
          const state = snapshot.zones.find((entry) => entry.id === zone.id);
          return (
            <g key={zone.id} className="battle-band">
              <rect x={0} y={band.top} width={map.width} height={band.height} />
              <ZoneChip zone={zone.id} state={state} you={you} top={band.top} />
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

        {snapshot.units.map((unit) => {
          const at = toScreen(unit.position, you, map);
          const mine = unit.side === you;
          const radius = unit.kind === 'mage' ? MAGE_RADIUS : SUMMON_RADIUS;
          const hurt = unit.hp < unit.maxHp;

          return (
            <g
              key={unit.id}
              className={`unit ${mine ? 'is-yours' : 'is-theirs'} ${
                unit.kind === 'mage' ? 'is-mage' : 'is-summon'
              }`}
            >
              {/* Shape carries the side as well as colour does, so the board is
                  still readable to someone who cannot tell the two hues apart. */}
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
              {unit.kind === 'mage' ? (
                <circle className="unit-ring" cx={at.x} cy={at.y} r={radius + 4} />
              ) : null}
              {hurt ? (
                <rect
                  className="unit-hp"
                  x={at.x - radius}
                  y={at.y + radius + 2}
                  width={radius * 2 * (unit.hp / unit.maxHp)}
                  height={2}
                />
              ) : null}
              <title>{`${unit.typeName} — ${Math.round(unit.hp)}/${unit.maxHp}`}</title>
            </g>
          );
        })}

        {targeting
          ? regions.map((region) => {
              const at = toScreen(region.at, you, map);
              return (
                <circle
                  key={region.id}
                  className="target-preview"
                  cx={at.x}
                  cy={at.y}
                  r={targeting.radius}
                />
              );
            })
          : null}
      </svg>

      {/*
        Targets are regions, not pixels. A spell lands at a location, and on a
        phone the location a thumb can actually pick is "zone B" or "their base"
        — five targets that clear 44 px by a wide margin, rather than a
        coordinate the player has to hit through their own finger.

        The prompt sits directly above them, and Cancel directly beside them:
        the second tap of the two is decided here, so everything it needs is
        here rather than further down the screen.
      */}
      {targeting ? (
        <div className="targeting">
          <p className="cast-prompt" data-testid="cast-prompt">
            {`Where should ${targeting.spellName} land?`}
          </p>
          <ul className="target-regions" aria-label={`Where should ${targeting.spellName} land?`}>
            {regions.map((region) => (
              <li key={region.id}>
                <button type="button" className="target-region" onClick={() => onTarget?.(region)}>
                  {region.label}
                </button>
              </li>
            ))}
            <li>
              <button type="button" className="target-cancel" onClick={() => onCancelTarget?.()}>
                Cancel
              </button>
            </li>
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function BaseBand({
  side,
  y,
  height,
  width,
  hp,
}: {
  readonly side: 'own' | 'enemy';
  readonly y: number;
  readonly height: number;
  readonly width: number;
  readonly hp: BaseHp;
}) {
  const share = Math.max(0, hp.hp / hp.maxHp);
  const label = side === 'own' ? 'YOUR BASE' : 'THEIR BASE';

  return (
    <g className={`base-band ${side === 'own' ? 'is-own' : 'is-enemy'}`}>
      <rect x={0} y={y} width={width} height={height} />
      <rect className="base-hp-track" x={12} y={y + height / 2} width={width - 24} height={6} />
      <rect
        className="base-hp-fill"
        x={12}
        y={y + height / 2}
        width={(width - 24) * share}
        height={6}
      />
      <text x={12} y={y + height / 2 - 6}>
        {label}
      </text>
      <text className="base-hp-value" x={width - 12} y={y + height / 2 - 6}>
        {`${Math.round(hp.hp)} / ${hp.maxHp}`}
      </text>
    </g>
  );
}

function ZoneChip({
  zone,
  state,
  you,
  top,
}: {
  readonly zone: string;
  readonly state: ZoneState | undefined;
  readonly you: Side;
  readonly top: number;
}) {
  const heldBy = state?.heldBy ?? null;
  const held = heldBy === null ? 'Contested' : heldBy === you ? 'Yours' : 'Theirs';

  return (
    <g className={`zone-chip held-${heldBy === null ? 'none' : heldBy === you ? 'you' : 'them'}`}>
      <rect x={0} y={top} width={CHIP_WIDTH} height={CHIP_HEIGHT} />
      <text x={8} y={top + 17}>{`${zone} · ${held}`}</text>
    </g>
  );
}

function zoneBandOnScreen(
  lane: { readonly start: number; readonly end: number },
  you: Side,
  map: MapGeometry,
) {
  const height = lane.end - lane.start;
  const top = you === 'south' ? lane.start : map.height - lane.end;
  return { top, height };
}
