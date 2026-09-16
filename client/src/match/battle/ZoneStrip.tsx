/**
 * The lanes, indexed, above the board (JQ-312 AC 3).
 *
 * The chips on the map say who holds what, but they are inside the lanes, and a
 * thumb reaching for the cast bar covers the bottom third of a phone. This is
 * the same facts in a fixed row at the *top* of the screen — the one band a
 * thumb never reaches — so "am I still holding West" is answerable without
 * lifting your hand off the controls.
 *
 * Indexed by zone, in map order, and derived from `map.zones` rather than from a
 * literal list: the map went from three lanes to two once already (JQ-376), and
 * a strip that hard-coded the count would have been the thing that broke.
 *
 * It shows occupancy as well as the holder, because the two differ and the
 * difference is the whole rule: units in a lane are not holding it — a *mage*
 * standing in its hotspot is. A lane you have four summons in and no mage reads
 * as "Open", and a player who cannot see why would think the board was wrong.
 */

import { type MapGeometry, ZONE_NAME, hotspotContains, zoneContaining } from '../geometry.ts';
import type { BattleSnapshot, Side } from '../types.ts';
import { opposing } from '../types.ts';

export interface ZoneStripProps {
  readonly snapshot: BattleSnapshot;
  readonly you: Side;
  readonly map: MapGeometry;
}

export function ZoneStrip({ snapshot, you, map }: ZoneStripProps) {
  const them = opposing(you);

  return (
    <ul className="zone-strip" aria-label="Lanes">
      {map.zones.map((zone) => {
        const state = snapshot.zones.find((entry) => entry.id === zone.id);
        const heldBy = state?.heldBy ?? null;
        const held = heldBy === null ? 'Open' : heldBy === you ? 'Yours' : 'Theirs';
        const holdClass = heldBy === null ? 'held-none' : heldBy === you ? 'held-you' : 'held-them';

        const living = snapshot.units.filter(
          (unit) => unit.hp > 0 && zoneContaining(map, unit.position) === zone.id,
        );
        const yours = living.filter((unit) => unit.side === you).length;
        const theirs = living.filter((unit) => unit.side === them).length;
        const onSpot = living.filter(
          (unit) => unit.kind === 'mage' && hotspotContains(map, zone, unit.position),
        );

        return (
          <li
            key={zone.id}
            className={`zone-strip-entry ${holdClass}`}
            data-testid={`zone-strip-${zone.id}`}
          >
            <span className="zone-strip-name">{ZONE_NAME[zone.id]}</span>
            <span className="zone-strip-held">{held}</span>
            <span className="zone-strip-counts">
              {`${yours} v ${theirs}`}
              {/* Named explicitly, because "nobody is on the hotspot" is the
                  most common reason a lane you have units in scores nothing. */}
              {onSpot.length === 0 ? (
                <span className="zone-strip-empty-spot"> · hotspot empty</span>
              ) : null}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
