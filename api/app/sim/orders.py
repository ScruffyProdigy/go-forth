"""Orders — the whole of what a player gives a troop.

The design's central constraint (§6.1) is that the player gives an *order*, never
a placement: where units stand, which way they face, how tightly they bunch and
who stands in front are all derived from the order and the map. That is what
keeps the plan phase to three taps on a phone (JQ-190), and it is why `Order` is
frozen and carries nothing but a verb and, for a hold, the zone it names.

Five orders exist on the three-zone map — hold each zone, defend your own base,
push the enemy's — but "five" is a fact about the map rather than a constant
here: `legal_orders` counts the zones. A map with four zones offers six.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.sim.map import MapConfig, strip_centre, zone_by_id, zone_centre
from app.sim.types import Side, Vec2, opposing

OrderKind = Literal["holdZone", "defendBase", "pushEnemyBase"]


@dataclass(frozen=True)
class Order:
    """One verb, and the zone it names when the verb is `holdZone`.

    Frozen and position-free on purpose. Nothing may be added here that amounts
    to a placement or a stance — that is the constraint this type exists to hold.
    """

    kind: OrderKind
    zone_id: str | None = None


def hold(zone_id: str) -> Order:
    """Hold a zone: stand in it, and keep the enemy out of it."""
    return Order("holdZone", zone_id)


#: Form up in front of your own base and stay there.
DEFEND_BASE = Order("defendBase")
#: Walk at the enemy base. The only order under which the base can be attacked.
PUSH_ENEMY_BASE = Order("pushEnemyBase")


def legal_orders(config: MapConfig) -> tuple[Order, ...]:
    """Every order a plan may give on this map, in menu order."""
    return (*(hold(zone.id) for zone in config.zones), DEFEND_BASE, PUSH_ENEMY_BASE)


def validate_order(order: Order, config: MapConfig) -> None:
    """Raises unless the order is one this map can actually be given."""
    if order.kind == "holdZone":
        if order.zone_id is None:
            raise ValueError("a hold order must name the zone it holds")
        zone_by_id(config, order.zone_id)
        return

    if order.kind not in ("defendBase", "pushEnemyBase"):
        raise ValueError(f"{order.kind!r} is not an order")
    if order.zone_id is not None:
        raise ValueError(f"a {order.kind} order names no zone, but this one names {order.zone_id!r}")


def objective_position(order: Order, side: Side, config: MapConfig) -> Vec2:
    """The point the troop's formation is built around.

    Hold forms up on the middle of its zone, so that holding the zone and
    standing on the objective are the same act. Defend forms up on the middle of
    its own deployment strip — in front of the base rather than on it. Push walks
    at the enemy base itself.
    """
    validate_order(order, config)

    if order.kind == "holdZone":
        if order.zone_id is None:  # pragma: no cover - validate_order has already raised
            raise ValueError("a hold order must name the zone it holds")
        return zone_centre(zone_by_id(config, order.zone_id))
    if order.kind == "defendBase":
        return strip_centre(config, side)
    return config.bases[opposing(side)].position


def may_attack_base(order: Order) -> bool:
    """Only troops under Push enemy base may swing at a base (JQ-287).

    Exposed as a predicate so that the behaviour layer (JQ-296/328) can ask the
    question when it scores candidates, rather than re-deriving the rule. The
    combat phase applies it as a filter regardless: a unit under any other order
    never gets the base as a target, whoever asked.
    """
    return order.kind == "pushEnemyBase"


def faces_own_base(order: Order) -> bool:
    """Whether the troop's objective is behind it rather than in front.

    Only Defend base is: a defending troop starts on the base-facing side of its
    deployment strip, where every other order starts pressed against the far side.
    """
    return order.kind == "defendBase"
