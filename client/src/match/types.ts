/**
 * What the client believes is true about a match (JQ-311).
 *
 * The battle is server-authoritative (README): the client renders state it was
 * given and never simulates ahead of it. So these are *render* types — the shape
 * the screens consume — and deliberately not a wire format. JQ-309 owns the
 * contract, and its ticket warns specifically against letting the sim's
 * `serialize_battle` become the wire shape; `session.ts` is the seam where a
 * real transport translates into these.
 *
 * Two shapes here are not invented, because the server side of them already
 * exists and disagreeing with it would just be a rename later:
 *
 * - `Side` is the sim's own `north`/`south` (`api/app/sim/types.py`), portrait,
 *   north at the top of the screen.
 * - `CastCommand` carries the sim's `SpellInjection` minus its `side`, plus a
 *   client-minted `commandId`. The missing field is the point: the server fills
 *   `side` in from the seat, because a client that could name its own side could
 *   cast as its opponent. Deduplicating on the id is JQ-310; what matters here
 *   is that one exists.
 */

import type { PlanState, ZoneId } from '../plan/types.ts';

/** The sim's two sides. North is the top of a portrait screen. */
export type Side = 'north' | 'south';

export function opposing(side: Side): Side {
  return side === 'north' ? 'south' : 'north';
}

/** A point in map space — the sim's coordinates, not screen pixels. */
export interface MapPoint {
  readonly x: number;
  readonly y: number;
}

/* ------------------------------------------------------------ connection -- */

/**
 * The connection is its own axis, not a phase.
 *
 * A dropped connection does not mean the match stopped — it means this client
 * stopped hearing about it. Keeping the two separate is what lets a reconnecting
 * client keep the last authoritative picture on screen, clearly marked stale,
 * instead of blanking to a spinner and losing the player's place (JQ-311 AC 4).
 */
export type ConnectionState =
  | { readonly kind: 'connecting' }
  /** The seat token was refused. Terminal unless `retryable`. */
  | { readonly kind: 'claimFailed'; readonly reason: string; readonly retryable: boolean }
  | { readonly kind: 'live' }
  | { readonly kind: 'reconnecting'; readonly attempt: number }
  /** We left, or the server closed the session for good. */
  | { readonly kind: 'ended'; readonly reason: 'left' | 'closed' };

/* ----------------------------------------------------------------- bases -- */

export interface BaseHp {
  readonly hp: number;
  readonly maxHp: number;
}

/* ---------------------------------------------------------------- phases -- */

/**
 * Planning hands the client a server-supplied opening plan. It is a `PlanState`
 * because that is what the delivered JQ-293 screen renders; the translation from
 * whatever JQ-309 sends lives in the session, not in the screen.
 */
export interface PlanningPhase {
  readonly kind: 'planning';
  readonly plan: PlanState;
  /** True once we have locked in and are waiting on the other seat. */
  readonly locked: boolean;
  /**
   * Your own troops, already on the field, once the plan is locked.
   *
   * A player who locks in first gets the board rather than a spinner — their
   * troops taking the positions the plan just gave them (JQ-293, JQ-311 AC 4).
   * It carries *only* your side: the opponent's plan is hidden until the battle
   * starts, and a snapshot that included it would leak it to anyone reading the
   * network tab.
   */
  readonly deployment: BattleSnapshot | null;
}

export interface BattlePhase {
  readonly kind: 'battle';
  readonly battle: BattleSnapshot;
}

export interface RoundOverPhase {
  readonly kind: 'roundOver';
  readonly result: RoundResult;
}

export interface MatchOverPhase {
  readonly kind: 'matchOver';
  readonly result: MatchResult;
}

export type MatchPhase = PlanningPhase | BattlePhase | RoundOverPhase | MatchOverPhase;

/* -------------------------------------------------------------- the match -- */

export interface MatchSnapshot {
  /**
   * Identifies this run of the demo. A new test mints a new one, which is what
   * "a new test creates a fresh run" means concretely (JQ-311 AC 5): nothing is
   * carried over, not even by accident.
   */
  readonly runId: string;
  readonly matchId: string;
  /** Which side this client is sitting on. Everything else is relative to it. */
  readonly you: Side;
  readonly round: number;
  /**
   * Rounds already taken, per side. The opening demo plays one round, but the
   * match rule it belongs to is first to three — so the number is shown, not
   * assumed (JQ-311, Ryan's 2026-09-13 correction).
   */
  readonly roundsWon: Readonly<Record<Side, number>>;
  /** Base damage persists between rounds, so this is match state, not round state. */
  readonly baseHp: Readonly<Record<Side, BaseHp>>;
  readonly phase: MatchPhase;
  /**
   * The opening demo runs on a test profile rather than a real ladder match.
   * Carried in the snapshot so the label on screen is the server's claim about
   * the run and not a build-time guess.
   */
  readonly testProfile: boolean;
}

/**
 * Everything a screen needs: the last authoritative snapshot, and whether it can
 * still be trusted to be current.
 */
export interface MatchView {
  readonly connection: ConnectionState;
  /** Null only before the first snapshot arrives. */
  readonly snapshot: MatchSnapshot | null;
  /** Set while the connection is not `live`: this picture may have moved on. */
  readonly stale: boolean;
}

/* ---------------------------------------------------------------- battle -- */

export type UnitKind = 'mage' | 'summon';

export interface BattleUnit {
  readonly id: string;
  readonly kind: UnitKind;
  readonly side: Side;
  readonly typeName: string;
  readonly position: MapPoint;
  readonly hp: number;
  readonly maxHp: number;
}

/**
 * Who is holding a zone right now.
 *
 * Null is contested *or* empty, and it is not sticky — a zone stops being held
 * the moment the holder is outnumbered. This mirrors JQ-287's `zone_holders`
 * exactly, on purpose: the client's job is to show the server's answer, and a
 * client that kept the last holder on screen would be inventing one.
 */
export interface ZoneState {
  readonly id: ZoneId;
  readonly heldBy: Side | null;
}

/**
 * A cast the server has accepted, as it appears in the authoritative state.
 *
 * This is why the client does not keep its own list of casts in flight: on
 * recovery the server's snapshot is the whole truth, and anything the client
 * still believed about a cast is dropped rather than replayed (JQ-311 AC 4 —
 * "no automatic replay of accepted casts").
 */
export interface ResolvedCast {
  readonly commandId: string;
  readonly spellId: string;
  readonly spellName: string;
  readonly castBy: Side;
  readonly at: MapPoint;
  readonly tick: number;
}

export interface BattleSnapshot {
  readonly tick: number;
  readonly units: readonly BattleUnit[];
  readonly zones: readonly ZoneState[];
  /** Points accrued for zone control, per side — the round's running score. */
  readonly zoneScore: Readonly<Record<Side, number>>;
  /** Your energy pool. The opponent's is not sent — it is hidden information. */
  readonly energy: number;
  /** The spells you took into this round, with the cost the server resolved. */
  readonly loadout: readonly LoadoutSpell[];
  /** Accepted casts, both sides, as the server has them. */
  readonly casts: readonly ResolvedCast[];
}

export interface LoadoutSpell {
  readonly spellId: string;
  readonly name: string;
  /** The resolved cost, not the catalogue cost — contributors can change it. */
  readonly cost: number;
  readonly effect: string;
}

/* ----------------------------------------------------------------- casts -- */

/**
 * A cast the client is asking for.
 *
 * The sim's `SpellInjection` is (tick, spell_id, location, side). A client sends
 * the first three and never the fourth: `side` is filled in on the server from
 * the seat, because a client trusted to name its own side is a client that can
 * cast as its opponent. No damage or effect payload crosses either — the sim
 * looks effects up in its own catalogue (confirmed with JQ-288, 2026-09-14).
 *
 * `commandId` is ours, so a retry is recognisable as the same cast rather than a
 * second one. Deduplicating on it is JQ-310.
 */
export interface CastCommand {
  readonly commandId: string;
  readonly spellId: string;
  readonly at: MapPoint;
  /** The tick the player was looking at when they tapped. */
  readonly tick: number;
}

export type CastRejection =
  | 'notEnoughEnergy'
  | 'notEquipped'
  | 'outOfBounds'
  | 'roundOver'
  | 'notConnected';

export const CAST_REJECTION_TEXT: Record<CastRejection, string> = {
  notEnoughEnergy: 'Not enough energy yet.',
  notEquipped: 'That spell is not in this round’s loadout.',
  outOfBounds: 'That target is off the map.',
  roundOver: 'The round is already over.',
  notConnected: 'Not connected — the cast was not sent.',
};

/**
 * What became of a cast. `pending` exists so the cast bar can say "sent" without
 * pretending the server agreed: an optimistic client that drew the effect first
 * would be simulating ahead of the server, which this one never does.
 */
export type CastOutcome =
  | { readonly kind: 'pending'; readonly commandId: string }
  | { readonly kind: 'accepted'; readonly commandId: string }
  | { readonly kind: 'rejected'; readonly commandId: string; readonly reason: CastRejection };

/* ---------------------------------------------------------------- results -- */

/**
 * Why a round stopped, and the distinction Ryan's 2026-09-13 correction turns on:
 * a base destroyed ends the *match* on the spot, an ordinary round only ends the
 * round. Rendering them the same way would misreport the game's central rule.
 */
export type RoundEnding =
  | {
      readonly kind: 'roundComplete';
      readonly winner: Side | null;
      readonly reason: 'zoneControl' | 'annihilation' | 'timeUp';
    }
  | { readonly kind: 'baseDestroyed'; readonly winner: Side };

export interface RoundResult {
  readonly round: number;
  readonly ending: RoundEnding;
  /** Base HP as the round ended. It carries into the next round. */
  readonly baseHp: Readonly<Record<Side, BaseHp>>;
  readonly zones: readonly ZoneState[];
  readonly zoneScore: Readonly<Record<Side, number>>;
}

export type MatchEnding =
  | { readonly kind: 'baseDestroyed'; readonly winner: Side }
  | { readonly kind: 'roundsWon'; readonly winner: Side }
  /** The opening demo stops after one round: nobody has won the match yet. */
  | { readonly kind: 'testComplete'; readonly roundWinner: Side | null }
  | { readonly kind: 'abandoned'; readonly winner: Side | null };

export interface MatchResult {
  readonly ending: MatchEnding;
  readonly roundsWon: Readonly<Record<Side, number>>;
  readonly baseHp: Readonly<Record<Side, BaseHp>>;
  /**
   * The round that just finished. The opening demo is one round, so the result
   * screen has to say both things at once — how the round went, and what that
   * did or did not do to the match.
   */
  readonly lastRound: RoundResult;
}
