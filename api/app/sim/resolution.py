"""Applying effects to the world — the one place an effect becomes damage.

Abilities and spells are different triggers on the same machinery, and this is
the machinery. A spell is "an effect fired at a location by an external
trigger", so it arrives here with an explicit origin and no caster; an ability
arrives with a caster and an origin derived from it. Below that line nothing
knows which it was.

Dispatch is a lookup table keyed by effect class, not a chain of `isinstance`
branches. A new primitive is a dataclass in `effects.py` and a row here; there
is deliberately nowhere for per-card behaviour to accumulate.

Nothing here reads the caster's *side* from anything the client sent. An
injection carries `(tick, spellId, location, side)` and the effects come from
the sim's own catalog, so a lying client can pick a bad target but cannot
invent damage.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.sim.config import to_ticks
from app.sim.context import TickContext
from app.sim.effects import (
    AreaDamage,
    Burn,
    BurningGround,
    DamageProfile,
    DashToTarget,
    Effect,
    EnergyRefill,
    Knockback,
)
from app.sim.energy import DAMAGE_DEALT, DAMAGE_TAKEN
from app.sim.events import EventSwing, unit_defeated
from app.sim.geometry import distance, move_toward
from app.sim.statuses import BURNING_GROUND, BurnStatus, GroundHazard
from app.sim.types import SIDES, Side, UnitRef, Vec2, opposing
from app.sim.world import Unit, World, unit_ref


@dataclass
class EffectOutcome:
    """What a cast moved. Becomes the `swing` on the event it is reported with."""

    damage_dealt: float = 0.0
    units_removed: list[UnitRef] = field(default_factory=list)
    #: Base-HP deltas, negative for damage. Only sides that were hit appear.
    base_hp: dict[Side, float] = field(default_factory=dict)


@dataclass
class Cast:
    """One resolution of one bundle of effects."""

    world: World
    ctx: TickContext
    #: Whose cast it is. Everything on the other side is an enemy.
    side: Side
    #: Where the effects are centred.
    origin: Vec2
    #: The unit that cast it, if a unit did. A spell has none.
    caster: Unit | None = None
    #: The enemy the cast was aimed at, for effects that need one.
    target: Unit | None = None
    #: Whether `origin` rides along with the caster. A self-centred cast that
    #: opens with a dash should land the rest of itself where the dash ended,
    #: not where it started; a cast aimed at a target should not.
    follows_caster: bool = False
    outcome: EffectOutcome = field(default_factory=EffectOutcome)


def swing_of(outcome: EffectOutcome) -> EventSwing:
    """The event envelope's swing, built from what a cast actually moved."""
    base_hp = {side: outcome.base_hp.get(side, 0.0) for side in SIDES}
    return EventSwing(base_hp=base_hp, units_removed=tuple(outcome.units_removed))


def _source_ref(cast: Cast) -> UnitRef | None:
    return unit_ref(cast.caster) if cast.caster is not None else None


def _is_alive(unit: Unit) -> bool:
    return unit.hp > 0


def _enemies_within(cast: Cast, center: Vec2, radius: float) -> list[Unit]:
    """Living enemies inside a disc, in world order — which is deterministic."""
    return [
        unit
        for unit in cast.world.units
        if unit.side != cast.side and _is_alive(unit) and distance(center, unit.position) <= radius
    ]


def _allies_within(cast: Cast, center: Vec2, radius: float) -> list[Unit]:
    return [
        unit
        for unit in cast.world.units
        if unit.side == cast.side and _is_alive(unit) and distance(center, unit.position) <= radius
    ]


def damage_unit(cast: Cast, victim: Unit, amount: float, source: UnitRef | None) -> None:
    """Takes HP off a unit and reports the defeat if that finished it.

    The same path every blow takes, so a kill by burn, by spell and by ability
    all reach the stream as the same `unitDefeated` the auto-attack emits.
    Damage dealt feeds the caster's energy meter here rather than at the call
    sites, which is what keeps Fire's "charge off damage dealt" rule true of
    ability damage as well as of weapon swings.
    """
    if amount <= 0 or not _is_alive(victim):
        return

    victim.hp -= amount
    victim.energy_meters[DAMAGE_TAKEN] += amount
    cast.outcome.damage_dealt += amount

    caster = cast.caster
    if caster is not None and _is_alive(caster):
        caster.energy_meters[DAMAGE_DEALT] += amount

    if victim.hp <= 0:
        victim.hp = 0
        ref = unit_ref(victim)
        cast.outcome.units_removed.append(ref)
        cast.ctx.emitter.emit(
            **unit_defeated(
                tick=cast.world.tick,
                position=victim.position,
                unit=ref,
                killer=source,
            )
        )


def _damage_base(cast: Cast, radius: float, profile: DamageProfile) -> None:
    """Chips the enemy base when the blast reaches it.

    Bases take damage here so `bonus_vs_base` means something, but nothing
    *ends* on it: base destruction is slice B's ending (JQ-287), and a battle
    whose base hits zero here simply runs on with a base at zero.
    """
    enemy_side = opposing(cast.side)
    base = cast.world.bases[enemy_side]
    if distance(cast.origin, base.position) > radius:
        return

    dealt = min(base.hp, profile.against_base())
    if dealt <= 0:
        return

    base.hp -= dealt
    cast.outcome.base_hp[enemy_side] = cast.outcome.base_hp.get(enemy_side, 0.0) - dealt


def _push_away(origin: Vec2, position: Vec2, step: float, width: float, height: float) -> Vec2:
    """Shoves a point directly away from `origin`, kept on the map.

    A unit standing exactly on the origin has no direction to be pushed in, and
    inventing one from the RNG would make a knockback shift every later draw in
    the battle. It stays put.
    """
    gap = distance(origin, position)
    if gap == 0:
        return position

    scale = step / gap
    return Vec2(
        min(width, max(0.0, position.x + (position.x - origin.x) * scale)),
        min(height, max(0.0, position.y + (position.y - origin.y) * scale)),
    )


def _apply_burn(cast: Cast, victim: Unit, damage_per_tick: float, ticks: int, bonus_vs_mage: float) -> None:
    existing = victim.burn

    if existing is None:
        victim.burn = BurnStatus(
            damage_per_tick=damage_per_tick,
            ticks_remaining=ticks,
            bonus_vs_mage=bonus_vs_mage,
            source=_source_ref(cast),
        )
        return

    if damage_per_tick > existing.damage_per_tick:
        existing.damage_per_tick = damage_per_tick
        existing.source = _source_ref(cast)
    existing.ticks_remaining = max(existing.ticks_remaining, ticks)
    existing.bonus_vs_mage = max(existing.bonus_vs_mage, bonus_vs_mage)


def _resolve_dash(effect: DashToTarget, cast: Cast) -> None:
    caster, target = cast.caster, cast.target
    if caster is None or target is None or caster.emplacement:
        return

    gap = distance(caster.position, target.position)
    step = min(effect.max_distance, gap - effect.stop_short)
    if step <= 0:
        return

    caster.position = move_toward(caster.position, target.position, step)
    if cast.follows_caster:
        cast.origin = caster.position


def _resolve_area_damage(effect: AreaDamage, cast: Cast) -> None:
    source = _source_ref(cast)
    for victim in _enemies_within(cast, cast.origin, effect.radius):
        damage_unit(cast, victim, effect.damage.against_unit(victim.kind), source)

    if effect.hits_base:
        _damage_base(cast, effect.radius, effect.damage)


def _resolve_burn(effect: Burn, cast: Cast) -> None:
    ticks = to_ticks(effect.duration_seconds, cast.ctx.config)
    damage_per_tick = effect.damage_per_second * cast.ctx.seconds_per_tick

    caught = _enemies_within(cast, cast.origin, effect.radius)
    for victim in caught:
        _apply_burn(cast, victim, damage_per_tick, ticks, effect.bonus_vs_mage)

    if effect.spread_radius <= 0:
        return

    # One hop, and one only: the neighbours below are never themselves walked
    # as sources, so a burn cannot walk a packed line end to end.
    already_lit = {victim.id for victim in caught}
    for victim in caught:
        for neighbour in _enemies_within(cast, victim.position, effect.spread_radius):
            if neighbour.id in already_lit:
                continue
            _apply_burn(cast, neighbour, damage_per_tick, ticks, effect.bonus_vs_mage)


def _resolve_burning_ground(effect: BurningGround, cast: Cast) -> None:
    world = cast.world
    world.hazards.append(
        GroundHazard(
            id=f"hz{world.next_hazard_id}",
            kind=BURNING_GROUND,
            side=cast.side,
            center=cast.origin,
            radius=effect.radius,
            damage_per_tick=effect.damage_per_second * cast.ctx.seconds_per_tick,
            ticks_remaining=to_ticks(effect.duration_seconds, cast.ctx.config),
            bonus_vs_mage=effect.bonus_vs_mage,
            source=_source_ref(cast),
        )
    )
    world.next_hazard_id += 1


def _resolve_knockback(effect: Knockback, cast: Cast) -> None:
    map_config = cast.ctx.map_config
    for victim in _enemies_within(cast, cast.origin, effect.radius):
        if victim.emplacement:
            continue
        victim.position = _push_away(
            cast.origin, victim.position, effect.distance, map_config.size_width, map_config.size_height
        )


def _resolve_energy_refill(effect: EnergyRefill, cast: Cast) -> None:
    caster = cast.caster
    for ally in _allies_within(cast, cast.origin, effect.radius):
        if ally.ability_id is None:
            continue
        if not effect.include_self and caster is not None and ally.id == caster.id:
            continue
        ally.energy += effect.amount


#: The dispatch table. Looked up by class and never iterated.
_RESOLVERS: dict[type, Callable[[Any, Cast], None]] = {
    DashToTarget: _resolve_dash,
    AreaDamage: _resolve_area_damage,
    Burn: _resolve_burn,
    BurningGround: _resolve_burning_ground,
    Knockback: _resolve_knockback,
    EnergyRefill: _resolve_energy_refill,
}


def apply_effects(effects: Sequence[Effect], cast: Cast) -> EffectOutcome:
    """Runs a bundle of effects, in the order the card declares them.

    Declaration order is load-bearing and deliberately so: a dash that lands
    before a blast puts the blast somewhere else, and a card author should be
    able to say which happens first without asking for code.
    """
    for effect in effects:
        resolver = _RESOLVERS.get(type(effect))
        if resolver is None:
            raise ValueError(f"{type(effect).__name__} is not a known effect primitive")
        resolver(effect, cast)

    return cast.outcome
