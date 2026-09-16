"""The game wire contract: every byte that crosses between server and client.

This module is the answer to JQ-309's sharpest acceptance criterion — *"never
accidentally expose `serialize_battle` as the wire format"* — and the reason it
exists as its own file rather than as a `to_json` on each sim type.

## Why `serialize_battle` must never be the wire format

`sim/serialize.py` renders a battle as canonical text so that two runs can be
compared byte for byte. That is a **determinism harness**, and its requirements
are the opposite of a wire format's at three separate points:

1. **It is total.** It carries every unit, both bases, the whole event stream.
   A client must not be sent the opponent's energy or the opponent's unlocked
   plan — those are hidden information, and a snapshot containing them leaks
   them to anyone with the network tab open, whatever the UI chooses to draw.
2. **It is frozen for a different reason.** Its shape may not change without
   invalidating saved comparisons; the wire's shape may not change without
   breaking deployed clients. Tying the two together means every rendering
   tweak is a determinism event and every determinism fix is a client release.
3. **It is a whole battle, not a moment.** It is written from a finished
   `BattleResult`. A live session sends a *tick*.

The failure mode is not that someone decides to use it — it is that
`serialize_battle(result)` is right there, produces plausible JSON, and saves an
afternoon. `tests/match/test_wire.py` asserts this module never imports it.

## Divergences from the client's current render types

`client/src/match/types.ts` was written against JQ-311's fixtures, before
JQ-376 replaced the three-zone map with two lanes. Two names disagree, and the
**server's are authoritative** — the sim is where a zone and an order actually
mean something:

| client (JQ-311 fixture)  | server (authoritative)              | why               |
|--------------------------|-------------------------------------|-------------------|
| `ZoneId` of `A`, `B`, `C`| zone ids from the map: `"W"`, `"E"` | JQ-376: two lanes |
| `Order.kind` of `hold`   | `holdZone`                          | `sim/orders.py` spells it so |

Neither is renamed here to match the stale fixture. The client adopting them is
JQ-311's follow-up; a server that renamed its lanes to keep a fixture happy
would be the tail wagging the dog.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from app.sim.map import MapConfig
from app.sim.types import SIDES, Side, Vec2
from app.sim.world import World, is_alive
from app.sim.zones import zone_occupancy

#: Bumped when a field changes meaning or leaves. Sent on every snapshot so a
#: client that has been open across a deploy can say so rather than mis-render.
WIRE_VERSION = 1


def point(value: Vec2) -> dict[str, float]:
    """A map-space point. Map units, never screen pixels — the client scales."""
    return {"x": value.x, "y": value.y}


# --------------------------------------------------------------------- bases --


def base_hp(world: World, map_config: MapConfig) -> dict[Side, dict[str, float]]:
    """Both bases, both sides.

    Not hidden information: a base's health is the match's central fact under
    the 2026-09-13 rule, and a player who cannot see the opponent's base cannot
    tell a push from a rout. Walked through `SIDES` rather than by iterating
    `world.bases`, per the hash-ordering rule in `sim/rng.py`.
    """
    return {side: {"hp": world.bases[side].hp, "maxHp": map_config.bases[side].max_hp} for side in SIDES}


# --------------------------------------------------------------------- units --


def battle_units(world: World) -> list[dict[str, Any]]:
    """Every living unit, both sides.

    Positions are not hidden: this is a real-time battle on a shared map, and
    fog of war is not a mechanic Go Forth! has. What *is* hidden — energy, the
    unlocked plan, the opponent's loadout — is withheld field by field
    elsewhere in this module rather than by filtering units here.

    Sorted by id so two clients rendering the same tick agree on draw order,
    and so a diff between two snapshots is about the game rather than about
    which unit happened to die first.
    """
    return [
        {
            "id": unit.id,
            "kind": unit.kind,
            "side": unit.side,
            "typeName": unit.type_id,
            "position": point(unit.position),
            "hp": unit.hp,
            "maxHp": unit.max_hp,
        }
        for unit in sorted((u for u in world.units if is_alive(u)), key=lambda u: u.id)
    ]


def zone_states(world: World, map_config: MapConfig) -> list[dict[str, Any]]:
    """Who holds each lane, in map order.

    Read from `zone_occupancy` rather than from `world.zone_holders` so the
    client is shown the same derivation the scoring phase uses. Holding is not
    sticky: a lane stops being held the tick its holder steps off, and a client
    that kept the last holder on screen would be inventing one.
    """
    return [
        {"id": occupancy.zone.id, "heldBy": occupancy.holder}
        for occupancy in zone_occupancy(world, map_config)
    ]


# -------------------------------------------------------------------- loadout --


@dataclass(frozen=True, slots=True)
class LoadoutSpell:
    """A spell in a seat's round loadout, with the cost the server resolved.

    The resolved cost, never the catalogue's printed one: what a fielded mage's
    tags do to a spell's price is the server's answer, and a client pricing off
    the card would let a player spend energy they do not have.
    """

    spell_id: str
    name: str
    cost: float
    effect: str

    def to_json(self) -> dict[str, Any]:
        return {"spellId": self.spell_id, "name": self.name, "cost": self.cost, "effect": self.effect}


@dataclass(frozen=True, slots=True)
class ResolvedCast:
    """A cast the server accepted, as it appears in authoritative state.

    Both sides' casts travel: a spell landing on the map is a visible event, and
    hiding the opponent's would make the battle unreadable. What does not travel
    is anything about a cast that was *refused* — a rejection is answered to the
    seat that asked and to nobody else.
    """

    command_id: str
    spell_id: str
    spell_name: str
    cast_by: Side
    at: Vec2
    #: The tick the server scheduled it on, and its place among the round's
    #: accepted casts. Both the server's, never the client's (JQ-310): a client
    #: that could name either could schedule a cast the opponent cannot see
    #: coming, or push itself ahead of a cast that arrived first.
    tick: int
    order: int

    def to_json(self) -> dict[str, Any]:
        return {
            "commandId": self.command_id,
            "spellId": self.spell_id,
            "spellName": self.spell_name,
            "castBy": self.cast_by,
            "at": point(self.at),
            "tick": self.tick,
            "order": self.order,
        }


def battle_snapshot(
    *,
    world: World,
    map_config: MapConfig,
    you: Side,
    energy: float,
    loadout: Sequence[LoadoutSpell],
    casts: Sequence[ResolvedCast],
    only_your_units: bool = False,
) -> dict[str, Any]:
    """One tick, as one seat sees it.

    `energy` and `loadout` are **this seat's**. The opponent's energy is hidden
    information — knowing it tells you exactly which spell is coming — so it is
    not in the payload at all rather than present and ignored.

    `only_your_units` is the deployment preview a player gets after locking in
    and before the battle starts: their own troops taking the positions the plan
    gave them. The opponent's plan is hidden until the battle begins, so at that
    moment it is not merely undrawn — it is not in the snapshot to be found.
    """
    units = battle_units(world)
    if only_your_units:
        units = [unit for unit in units if unit["side"] == you]

    return {
        "tick": world.tick,
        "units": units,
        "zones": zone_states(world, map_config),
        "zoneScore": {side: world.zone_score[side] for side in SIDES},
        "energy": energy,
        "loadout": [spell.to_json() for spell in loadout],
        "casts": [cast.to_json() for cast in casts],
    }


# --------------------------------------------------------------------- phases --


def planning_phase(
    *,
    plan: Mapping[str, Any],
    locked: bool,
    deployment: Mapping[str, Any] | None,
    loadout: Sequence[LoadoutSpell] = (),
    energy: float = 0.0,
) -> dict[str, Any]:
    """The plan screen, as one seat sees it.

    `plan` is **this seat's own**: the suggested default until they lock in, and
    what they actually locked in afterwards. That swap is what makes a refresh
    mid-planning survivable — a player who reloads after locking has to be shown
    the army they committed to, not the suggestion they replaced, or they will
    conclude their lock-in was lost and try to make it again (JQ-310).

    `loadout` is the resolved equipped spells, with the costs the *server* read
    off the fielded mages, and is empty until the seat locks. It rides here as
    well as in `battle_snapshot` so a reclaim during planning already knows what
    a cast will cost, rather than learning it when the battle starts.

    Nothing about the opponent is in this payload at any point — not their plan,
    not their loadout, not whether they have locked. Hidden simultaneous choice
    is the phase's whole mechanic, and a field a UI merely declines to draw is
    still a field in the network tab.
    """
    return {
        "kind": "planning",
        "plan": dict(plan),
        "locked": locked,
        "deployment": deployment,
        "loadout": [spell.to_json() for spell in loadout],
        "energy": energy,
    }


def battle_phase(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return {"kind": "battle", "battle": dict(snapshot)}


def round_over_phase(result: Mapping[str, Any]) -> dict[str, Any]:
    return {"kind": "roundOver", "result": dict(result)}


def match_over_phase(result: Mapping[str, Any]) -> dict[str, Any]:
    return {"kind": "matchOver", "result": dict(result)}


# -------------------------------------------------------------------- results --

#: Why a round stopped. `baseDestroyed` is not one of these — it ends the match
#: rather than the round, and lives in `RoundEnding` as its own kind so the two
#: can never be rendered the same way.
RoundReason = Literal["zoneControl", "annihilation", "timeUp"]


def round_complete(winner: Side | None, reason: RoundReason) -> dict[str, Any]:
    return {"kind": "roundComplete", "winner": winner, "reason": reason}


def base_destroyed(winner: Side | None) -> dict[str, Any]:
    """A base fell. This ends the **match**, not the round (Ryan, 2026-09-13).

    Its own ending kind rather than a `reason` on `roundComplete`, because the
    two are different events: presenting base destruction as one round lost
    would misreport the game's central rule, and a client given a `reason`
    string would have to know which strings were terminal.

    `winner` is null when **both** bases fell on the same tick — reachable,
    since two spells can land on one tick with nothing serialising them. It
    stays this kind rather than gaining one of its own: what a client has to
    know is that the match is over and how, and `winner: null` already means "a
    draw" everywhere else on this wire.
    """
    return {"kind": "baseDestroyed", "winner": winner}


def round_result(
    *,
    round_number: int,
    ending: Mapping[str, Any],
    bases: Mapping[Side, Mapping[str, float]],
    zones: Sequence[Mapping[str, Any]],
    zone_score: Mapping[Side, float],
) -> dict[str, Any]:
    return {
        "round": round_number,
        "ending": dict(ending),
        # Base HP as the round ended. It carries into the next round unchanged:
        # nothing heals a base between rounds.
        "baseHp": {side: dict(values) for side, values in bases.items()},
        "zones": [dict(zone) for zone in zones],
        "zoneScore": dict(zone_score),
    }


def match_result(
    *,
    ending: Mapping[str, Any],
    rounds_won: Mapping[Side, int],
    bases: Mapping[Side, Mapping[str, float]],
    last_round: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "ending": dict(ending),
        "roundsWon": dict(rounds_won),
        "baseHp": {side: dict(values) for side, values in bases.items()},
        "lastRound": dict(last_round),
    }


def match_ending_base_destroyed(winner: Side | None) -> dict[str, Any]:
    """Null `winner` is a mutual destruction — see `base_destroyed`."""
    return {"kind": "baseDestroyed", "winner": winner}


def match_ending_rounds_won(winner: Side) -> dict[str, Any]:
    return {"kind": "roundsWon", "winner": winner}


def match_ending_test_complete(round_winner: Side | None) -> dict[str, Any]:
    """The test profile stopped after its rounds. **Nobody has won a match.**

    The distinction this kind exists to keep: a one-round demo that reported
    `roundsWon` would be indistinguishable downstream from a best-of-five
    somebody actually took.
    """
    return {"kind": "testComplete", "roundWinner": round_winner}


def match_ending_abandoned(winner: Side | None) -> dict[str, Any]:
    return {"kind": "abandoned", "winner": winner}


# ------------------------------------------------------------------- snapshot --


def match_snapshot(
    *,
    run_id: str,
    match_id: str,
    you: Side,
    round_number: int,
    rounds_won: Mapping[Side, int],
    bases: Mapping[Side, Mapping[str, float]],
    phase: Mapping[str, Any],
    test_profile: bool,
) -> dict[str, Any]:
    """Everything one seat knows about the match right now.

    `testProfile` rides in the snapshot rather than being a build-time constant
    in the client, so the label on screen is the *server's* claim about this run.
    """
    return {
        "wireVersion": WIRE_VERSION,
        "runId": run_id,
        "matchId": match_id,
        "you": you,
        "round": round_number,
        "roundsWon": dict(rounds_won),
        "baseHp": {side: dict(values) for side, values in bases.items()},
        "phase": dict(phase),
        "testProfile": test_profile,
    }


# -------------------------------------------------------------------- commands --

#: Why a cast was refused. A closed set: the client renders a sentence per
#: reason, so a new one must be added on both sides deliberately.
CastRejection = Literal[
    "notEnoughEnergy",
    "notEquipped",
    "outOfBounds",
    "roundOver",
    "notYourSeat",
    "notConnected",
    #: The cast named a tick too far from the server's to honour — a tap that
    #: sat in a dead socket, or a client clock that has run away (JQ-310).
    "stale",
    #: A cast that arrived outside the battle phase altogether. Distinct from
    #: `roundOver`, which means the round you were casting into has just ended:
    #: one is a client that is behind, the other is a client that is confused,
    #: and a player deserves to be told which.
    "wrongPhase",
]


#: How long a client-minted `commandId` may be. It is a correlation id, and a
#: UUID is 36 characters; anything longer is not a client labelling its own
#: casts. Bounded because the id becomes a key in the per-match command ledger,
#: which is to say a dictionary a client fills in (JQ-310).
MAX_COMMAND_ID_LENGTH = 64


class CommandError(Exception):
    """A client message this server will not act on."""


@dataclass(frozen=True, slots=True)
class CastCommand:
    """A cast the client is asking for.

    The sim's `SpellInjection` is `(tick, spell_id, location, side)`. A client
    sends the first three and **never the fourth**: `side` is filled in on the
    server from the seat, because a client trusted to name its own side is a
    client that can cast as its opponent.

    No damage or effect payload crosses either — the sim looks effects up in its
    own catalogue, so a client that lies about a spell's payload changes nothing.

    `command_id` is the client's, so a retry is recognisable as the same cast
    rather than as a second one. Acting on that is JQ-310; carrying it is here.
    """

    command_id: str
    spell_id: str
    at: Vec2
    #: The tick the player was looking at when they tapped. Advisory: the server
    #: schedules on its own next tick, and this only says how stale the tap was.
    tick: int


def _require_text(raw: Any, field: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise CommandError(f"{field} is required")
    return raw.strip()


def _require_number(raw: Any, field: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise CommandError(f"{field} must be a number")
    value = float(raw)
    # NaN and the infinities parse out of JSON in Python and would reach the sim
    # as a position no comparison is true about.
    if value != value or value in (float("inf"), float("-inf")):
        raise CommandError(f"{field} must be a finite number")
    return value


def parse_cast_command(raw: Any) -> CastCommand:
    if not isinstance(raw, dict):
        raise CommandError("cast requires an object")
    at = raw.get("at")
    if not isinstance(at, dict):
        raise CommandError("cast.at is required")
    command_id = _require_text(raw.get("commandId"), "cast.commandId")
    if len(command_id) > MAX_COMMAND_ID_LENGTH:
        raise CommandError(f"cast.commandId must be at most {MAX_COMMAND_ID_LENGTH} characters")
    return CastCommand(
        command_id=command_id,
        spell_id=_require_text(raw.get("spellId"), "cast.spellId"),
        at=Vec2(_require_number(at.get("x"), "cast.at.x"), _require_number(at.get("y"), "cast.at.y")),
        tick=int(_require_number(raw.get("tick", 0), "cast.tick")),
    )


# ------------------------------------------------------------ server messages --


def state_message(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return {"type": "state", "state": dict(snapshot)}


def cast_outcome_message(
    kind: Literal["accepted", "rejected"],
    command_id: str,
    reason: str | None = None,
) -> dict[str, Any]:
    """The answer to one cast.

    A stream rather than view state: each cast gets exactly one answer, and
    folding it into the snapshot would make "which of my three casts failed"
    unanswerable. There is no `pending` from the server — pending is what the
    client calls a cast it has sent and not yet heard about.
    """
    message: dict[str, Any] = {"type": "castOutcome", "outcome": kind, "commandId": command_id}
    if reason is not None:
        message["reason"] = reason
    return message


def error_message(error: str) -> dict[str, Any]:
    return {"type": "error", "error": error}


def claim_failed_message(reason: str, *, retryable: bool) -> dict[str, Any]:
    """A seat the socket may not have.

    `retryable` separates "the Lobby was briefly unreachable" from "this is not
    your seat". The client shows a retry button for the first and never for the
    second, so guessing here would either strand a player or invite them to hammer
    a door that will not open.
    """
    return {"type": "claimFailed", "reason": reason, "retryable": retryable}
