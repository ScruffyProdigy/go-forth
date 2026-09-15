"""Runs two placeholder armies at each other and prints the event stream.

Deliberately outside `app/sim/`: this is the one piece that talks to the outside
world — argv in, stdout out — and the sim's purity test asserts nothing like it
is reachable from `run_battle`.

    python -m app.scripts.battle_demo
    python -m app.scripts.battle_demo --seed 7
    python -m app.scripts.battle_demo --abilities

`--abilities` swaps the slice-A placeholder roster for the one carrying energy
gauges, abilities and a mid-battle spell (JQ-288). It is a separate flag rather
than the default because the default roster is what `golden_battles.json` was
captured from, and that comparison is worth keeping.

stdout is the canonical serialisation and nothing else, so two runs can be
compared byte for byte. The human-readable summary goes to stderr.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from app.sim import (
    THREE_ZONE_MAP,
    SpellInjection,
    Vec2,
    ability_battle,
    digest_battle,
    placeholder_battle,
    run_battle,
    serialize_battle,
)

DEFAULT_SEED = 20260911

#: One scheduled spell, so the `--abilities` run shows an injection landing.
#: Mid-battle by eye, in the middle zone where the armies meet.
DEMO_SPELL = SpellInjection(tick=200, spell_id="meteor", location=Vec2(187.5, 290), side="north")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--abilities",
        action="store_true",
        help="run the roster with energy gauges, abilities and an injected spell",
    )
    args = parser.parse_args(argv)

    battle = ability_battle([DEMO_SPELL]) if args.abilities else placeholder_battle()
    result = run_battle(THREE_ZONE_MAP, [], battle, args.seed)

    sys.stdout.write(f"{serialize_battle(result)}\n")

    defeats = sum(1 for event in result.events if event.type == "unitDefeated")
    casts = sum(1 for event in result.events if event.type in ("abilityCast", "spell"))
    survivors = {
        side: sum(1 for unit in result.final_state.units if unit.side == side) for side in ("north", "south")
    }
    seconds = result.final_state.tick / result.config.tick_rate

    sys.stderr.write(
        "\n".join(
            [
                f"seed {args.seed} · digest {digest_battle(result)}",
                (
                    f"{result.outcome} after {result.final_state.tick} ticks "
                    f"({seconds}s at {result.config.tick_rate} ticks/s)"
                ),
                f"{len(result.events)} events, {defeats} defeats, {casts} casts",
                f"survivors: north {survivors['north']}, south {survivors['south']}",
                "",
            ]
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
