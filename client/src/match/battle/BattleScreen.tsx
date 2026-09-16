/**
 * The battle phase (JQ-311).
 *
 * It renders one authoritative snapshot and sends commands. It holds no model of
 * the battle, keeps no queue of casts in flight, and advances nothing on its own
 * — so a recovery snapshot can replace everything on screen without any local
 * state having to be reconciled with it.
 */

import { useState } from 'react';

import type { TargetRegion } from '../geometry.ts';
import type { BaseHp, BattleSnapshot, LoadoutSpell, MapPoint, Side } from '../types.ts';
import { BattleMap } from './BattleMap.tsx';
import { CastBar } from './CastBar.tsx';

export interface BattleScreenProps {
  readonly snapshot: BattleSnapshot;
  readonly you: Side;
  readonly round: number;
  readonly baseHp: Readonly<Record<Side, BaseHp>>;
  readonly onCast: (spell: LoadoutSpell, at: MapPoint, where: string) => void;
  readonly feedback: string | null;
  readonly stale: boolean;
}

export function BattleScreen({
  snapshot,
  you,
  round,
  baseHp,
  onCast,
  feedback,
  stale,
}: BattleScreenProps) {
  const [armed, setArmed] = useState<LoadoutSpell | null>(null);

  function target(region: TargetRegion): void {
    if (!armed) return;
    onCast(armed, region.at, region.label);
    setArmed(null);
  }

  return (
    <section className="battle" aria-label={`Round ${round} battle`}>
      <header className="battle-header">
        <h1>Round {round}</h1>
        <span className="battle-zone-score">
          {`Zones ${snapshot.zoneScore[you]} – ${snapshot.zoneScore[you === 'north' ? 'south' : 'north']}`}
        </span>
      </header>

      {/* The armed spell is handed over whole rather than reduced to a name and
          a radius: the map's outcome previews are computed from its resolved
          cost and magnitude, and a summary struck here would be a second place
          that decides what a spell does (JQ-312 AC 4). */}
      <BattleMap
        snapshot={snapshot}
        you={you}
        baseHp={baseHp}
        targeting={armed}
        onTarget={target}
        onCancelTarget={() => setArmed(null)}
        stale={stale}
      />

      <CastBar
        loadout={snapshot.loadout}
        energy={snapshot.energy}
        armed={armed}
        onArm={setArmed}
        feedback={feedback}
        // While the picture is stale a cast would be aimed at a board that has
        // moved. Say so by refusing it here rather than letting it fail later.
        disabled={stale}
      />
    </section>
  );
}
