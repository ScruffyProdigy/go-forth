"""Runs two placeholder armies at each other and prints the event stream.

Deliberately outside `app/sim/`: this is the one piece that talks to the outside
world — argv in, stdout out — and the sim's purity test asserts nothing like it
is reachable from `run_battle`.

    python -m app.scripts.battle_demo
    python -m app.scripts.battle_demo --seed 7

stdout is the canonical serialisation and nothing else, so two runs can be
compared byte for byte. The human-readable summary goes to stderr.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from app.sim import (
    THREE_ZONE_MAP,
    digest_battle,
    placeholder_battle,
    run_battle,
    serialize_battle,
)

DEFAULT_SEED = 20260911


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args(argv)

    result = run_battle(THREE_ZONE_MAP, [], placeholder_battle(), args.seed)

    sys.stdout.write(f"{serialize_battle(result)}\n")

    defeats = sum(1 for event in result.events if event.type == "unitDefeated")
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
                f"{len(result.events)} events, {defeats} defeats",
                f"survivors: north {survivors['north']}, south {survivors['south']}",
                "",
            ]
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
