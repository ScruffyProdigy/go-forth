"""The tuning inputs a match runs on — every one of them provisional.

JQ-308 asks for these to be *recorded* rather than agreed: "if a numeric value
is missing, the implementer supplies a configurable provisional value, records
it, and proceeds". This module is that record. Nothing here has been balanced,
and JQ-185/307 (packages) and JQ-292/297 (spells) replace the numbers as they
land. They are gathered in one frozen dataclass rather than scattered as
constants so that a playtest can hand `run_round` a different profile without
editing code — tuning from observed battles is the stated intent.

What is *not* in here is the mechanical rules: which side wins a tie, what
happens when a plan never arrives, which of two simultaneous terminal outcomes
takes precedence. Those live in `outcome.py` and `plan.py` as code, because the
ticket asks for them to stay "explicit and separate from numeric tuning" — a
policy that can be dialled from a config file is a policy nobody has decided.

## The numbers, and where each came from

`sim.max_battle_seconds` (90) and `sim.tick_rate` (20) are already in
`SimConfig` — the design doc's 60-90 s battle phase (§3.2). `base_hp` follows
`TWO_LANE_MAP`'s own 1000. `packages_available` / `packages_chosen` (5 / 3) and
`spells_per_round` (2) come straight from the ticket; three is also the opening
mage cap (§4.3). The rest are new here:

- `score_threshold` (900). A lane pays 1 a tick, so this is one lane held for
  45 s of a 90 s battle, or both for 22.5 s. Picked to be reachable in a
  decisive round and out of reach in a close one.
- `spell_energy_start` (20). Half a cast in hand at the opening whistle, so the
  first cast is a decision about *when* rather than a wait.
- `spell_energy_per_second` (4). A 40-cost spell every 10 s at a standstill;
  about nine casts across a full battle.
- `spell_energy_cap` (100). Two and a half casts' worth, so banking is worth
  something and hoarding the whole battle is not.
- `default_spell_cost` (40). Per-spell overrides live on the package catalog.
- `plan_backstop_seconds` (180). Deliberately generous — the ticket rules out
  an ordinary planning countdown, so this is a liveness backstop against a
  player who never answers, not a clock to play against.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from app.sim import DEFAULT_SIM_CONFIG, Side, SimConfig

#: The label this profile reports itself under. JQ-308 asks for it to survive
#: into session and UI reporting, so that nobody mistakes a configured
#: single-round demo for production Starter.
SINGLE_ROUND_TEST = "single-round-test"


@dataclass(frozen=True)
class MatchProfile:
    """One configured way to run a match. See the module docstring for sources."""

    label: str = SINGLE_ROUND_TEST
    #: How many rounds the match is. One, here; Starter is best-of-five (JQ-187).
    rounds: int = 1
    sim: SimConfig = DEFAULT_SIM_CONFIG
    #: Zone score that takes the round outright, before the backstop.
    score_threshold: float = 900
    #: Opening base HP per side. Empty means the map's own maximum — the only
    #: sane default, since a base never recovers and this is round one.
    base_hp: Mapping[Side, float] = MappingProxyType({})
    packages_available: int = 5
    packages_chosen: int = 3
    spells_per_round: int = 2
    spell_energy_start: float = 20
    spell_energy_per_second: float = 4
    spell_energy_cap: float = 100
    default_spell_cost: float = 40
    plan_backstop_seconds: float = 180


def validate_profile(profile: MatchProfile) -> None:
    """Raises unless the profile describes a match that can actually be played."""
    if profile.rounds < 1:
        raise ValueError(f"a match is at least one round, got {profile.rounds}")
    if profile.score_threshold <= 0:
        raise ValueError(f"score threshold must be positive, got {profile.score_threshold}")
    if profile.packages_chosen < 1:
        raise ValueError(f"a plan fields at least one troop, got {profile.packages_chosen}")
    if profile.packages_chosen > profile.packages_available:
        raise ValueError(
            f"a plan chooses {profile.packages_chosen} of {profile.packages_available} packages, "
            "which is more than are on offer"
        )
    if profile.spells_per_round < 0:
        raise ValueError(f"spell loadout size cannot be negative, got {profile.spells_per_round}")
    for name, value in (
        ("starting spell energy", profile.spell_energy_start),
        ("spell energy generation", profile.spell_energy_per_second),
        ("default spell cost", profile.default_spell_cost),
    ):
        if value < 0:
            raise ValueError(f"{name} cannot be negative, got {value}")
    if profile.spell_energy_cap <= 0:
        raise ValueError(f"spell energy cap must be positive, got {profile.spell_energy_cap}")
    if profile.spell_energy_start > profile.spell_energy_cap:
        raise ValueError(
            f"spell energy starts at {profile.spell_energy_start}, above its own cap "
            f"of {profile.spell_energy_cap}"
        )
    if profile.plan_backstop_seconds <= 0:
        raise ValueError(f"the planning backstop must be positive, got {profile.plan_backstop_seconds}")


#: The configured single-round test profile JQ-308 asks for. Explicitly *not*
#: production Starter: one round rather than five, and a score threshold that
#: production does not have.
SINGLE_ROUND_TEST_PROFILE = MatchProfile()
