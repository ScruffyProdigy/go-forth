"""The shared pure resolver: deployed mages in, an eligible menu and real numbers out.

This is JQ-297's centre. One function answers every question the plan phase and
the battle both ask about player spells, and **both sides call the same one** —
the planning preview, the server's lock-in, and the client's local preview all
run this calculation or a copy of it checked against the same fixtures. A
preview that priced a spell differently from the lock-in would be a player
spending energy they do not have.

## What it takes, and what it deliberately cannot take

`resolve_menu` reads deployed *mages*, the side's roster spell access, the
definition catalog, and the rules. Four things it is not given, each for a
reason:

* **Summons.** JQ-297: "never count summons". Not filtered out here — not
  passed in. A resolver that received the whole army and remembered to skip
  summons would be one refactor away from not skipping them.
* **Schools.** Tags are not faction membership (`spellbook.py`), and the
  cheapest way to guarantee that is to have no school data to reach for.
* **The world.** A battle's casualties must not change a locked loadout, so the
  resolver has nothing to read them from.
* **Client-supplied numbers.** Costs and effects come from the catalog. The
  only thing a client contributes is *which* spells it wants in its slots.

## Counting

Each deployed mage is counted **once per tag it carries**. Two instances of the
same mage type count twice — they are two mages on the field — and a mage
carrying both `evocation` and `reckless` adds one to each count and nothing to
any notion of a pair. Tag combinations are never counted, which is what keeps a
two-tag spell from multiplying: `spellbook.EffectScaling` reads one tag for one
number, and no code anywhere combines two supports into a third.

Duplicate *grants* collapse: two Ember Adepts on the field put one Fireball on
the menu, and both are named in `granted_by`. Whether fielding two of the same
mage was legal at all is the plan validator's question, not this one's.

## The snapshot

`snapshot_loadout` freezes access, tag support, and every resolved cost and
effect at lock-in. From then on the round reads the snapshot and nothing else,
so a contributor dying mid-battle cannot remove a button or change a price —
which is the provisional playtest policy JQ-297 asks to be made an explicit
configurable rule rather than an emergent accident. It is `LoadoutRules`, and
it is an experiment: see the class docstring.

The snapshot also carries the battle's spell catalog. `sim_spells()` hands the
sim `Spell` objects whose effects are the *resolved* ones, under ids namespaced
by side, because the two sides resolve the same definition to different numbers
and `BattleSetup.spells` is one catalog. The id a client names in a cast is the
definition id; the id the sim fires is the namespaced one, and the translation
happens server-side where a client cannot reach it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.sim.effects import Effect
from app.sim.spellbook import (
    AccessKind,
    AlwaysAvailable,
    IndependentAccess,
    MageTag,
    SignatureOf,
    SpellDefinition,
    SpellDefinitionCatalog,
    access_kind,
    camel_path,
    effect_to_json,
    read_field,
    write_field,
)
from app.sim.spells import Spell


class LoadoutError(Exception):
    """A loadout this server will not field. Carries the reason, for the seat."""


# ---------------------------------------------------------------------- input --


@dataclass(frozen=True, slots=True)
class DeployedMage:
    """One mage this plan actually puts on the field.

    `instance_id` identifies the deployment; `type_id` is the stable definition
    the mage was authored as. JQ-297 asks for both to be preserved and they do
    different jobs: signatures are granted by *type* (two copies grant one
    spell), and contributors are reported by *instance* (the screen names the
    two mages raising a number).
    """

    instance_id: str
    type_id: str
    name: str
    tags: tuple[MageTag, ...] = ()


@dataclass(frozen=True, slots=True)
class LoadoutRules:
    """The first test's spell policy, as configuration rather than as behaviour.

    **This is an experiment, not a settled rule of the game** — JQ-297 is
    explicit on that, and the fields are here so a playtest can change them
    without a code change and so a reader can see what the policy actually is:

    * `slots` — how many spells a seat takes into a round.
    * `reselect_each_round` — whether the slots are chosen again every round.
      Eligible previous choices are preserved (`preserved_selection`), so
      "reselected" means the player *may* change them, not that they are
      cleared.
    * `snapshot_at_lock_in` — whether access, tag support and resolved
      costs/effects freeze when the plan locks. True is the policy under test:
      a mage dying mid-battle does not remove a button or change a price.

    False is **declared and refused** rather than silently accepted, by
    `snapshot_loadout`. Resolving live is not a flag this layer can honour on its
    own: the battle's spell catalog is built once from the snapshot, so a
    loadout that re-priced itself mid-round would show one number and fire
    another — worse than either policy. Turning it off is a real piece of work
    in the round, and the refusal says so at the point somebody tries, rather
    than leaving a field that looks configurable and is not.
    """

    slots: int = 2
    reselect_each_round: bool = True
    snapshot_at_lock_in: bool = True


DEFAULT_LOADOUT_RULES = LoadoutRules()


# --------------------------------------------------------------------- output --


@dataclass(frozen=True, slots=True)
class Contributor:
    """One deployed mage raising one of a spell's numbers, by one tag."""

    instance_id: str
    mage_name: str
    type_id: str
    tag: MageTag


@dataclass(frozen=True, slots=True)
class ScaledField:
    """What happened to one number of one effect, shown rather than summarised.

    The whole calculation is reported — base, support, bonus, result, and
    whether the cap bound — because the plan screen has to explain a price, and
    because a test for "the cap holds at high support" needs somewhere to look
    that is not the final number alone.
    """

    effect_index: int
    field: str
    tag: MageTag
    support: int
    base: float
    bonus: float
    value: float
    capped: bool


@dataclass(frozen=True, slots=True)
class ResolvedSpell:
    """A definition plus a plan: the actual cost, and the actual effects."""

    definition_id: str
    name: str
    cost: float
    text: str
    access: AccessKind
    #: The base effects with every scaled field written in. What the sim runs.
    effects: tuple[Effect, ...]
    scaled: tuple[ScaledField, ...] = ()
    contributors: tuple[Contributor, ...] = ()
    #: Instance ids of the deployed mages whose signature put this on the menu.
    #: More than one when duplicates are fielded; the menu still shows one entry.
    granted_by: tuple[str, ...] = ()

    @property
    def reads(self) -> tuple[MageTag, ...]:
        found: list[MageTag] = []
        for entry in self.scaled:
            if entry.tag not in found:
                found.append(entry.tag)
        return tuple(found)


@dataclass(frozen=True, slots=True)
class MenuEntry:
    """One spell on the menu, eligible or not.

    Ineligible spells stay on the menu carrying their reason. Hiding them would
    hide the mage-to-spell link that is the whole reason troops are chosen
    before spells (§10 #31).
    """

    spell: ResolvedSpell
    eligible: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class LoadoutMenu:
    entries: tuple[MenuEntry, ...] = ()
    #: `(tag, count)` for every tag carried by a deployed mage, sorted by tag.
    #: Sorted rather than in encounter order: it crosses a process boundary and
    #: a dict keyed by strings is exactly the hash-ordering hazard
    #: `CONVENTIONS.md` is about.
    tag_support: tuple[tuple[MageTag, int], ...] = ()

    def entry(self, definition_id: str) -> MenuEntry | None:
        for candidate in self.entries:
            if candidate.spell.definition_id == definition_id:
                return candidate
        return None

    def eligible_ids(self) -> tuple[str, ...]:
        return tuple(entry.spell.definition_id for entry in self.entries if entry.eligible)

    def support_for(self, tag: MageTag) -> int:
        for name, count in self.tag_support:
            if name == tag:
                return count
        return 0


@dataclass(frozen=True, slots=True)
class SlotOutcome:
    """One spell slot after resolution: what is in it, and whether it may stay."""

    index: int
    definition_id: str | None
    spell: ResolvedSpell | None = None
    eligible: bool = True
    reason: str | None = None

    @property
    def stranded(self) -> bool:
        """Filled with something no longer legal. Blocks lock-in until replaced."""
        return self.definition_id is not None and not self.eligible


# -------------------------------------------------------------------- counting --


def tag_support(mages: Sequence[DeployedMage]) -> tuple[tuple[MageTag, int], ...]:
    """How many deployed mages carry each tag.

    Once per mage per tag. A mage that lists a tag twice still counts once for
    it — deduplicated per mage rather than trusted — and nothing here can see a
    summon, so JQ-297's "never count summons" holds by construction.

    Sorted by tag. The counts are assembled in a dict and then sorted on the
    way out, never iterated as they fall.
    """
    counts: dict[MageTag, int] = {}
    for mage in mages:
        seen: list[MageTag] = []
        for tag in mage.tags:
            if tag in seen:
                continue
            seen.append(tag)
            counts[tag] = counts.get(tag, 0) + 1
    return tuple(sorted(counts.items()))


def _contributors(definition: SpellDefinition, mages: Sequence[DeployedMage]) -> tuple[Contributor, ...]:
    """Every (mage, tag) pair feeding this spell, in mage order then tag order.

    Mage order is the plan's own troop order and tag order is the spell's, so
    two interpreters resolving the same plan report the same list. Carriers are
    reported even when a threshold means they add nothing yet: "one more
    Evocation mage and this starts working" is the thing the screen has to be
    able to say.
    """
    found: list[Contributor] = []
    for mage in mages:
        for tag in definition.reads:
            if tag in mage.tags:
                found.append(
                    Contributor(
                        instance_id=mage.instance_id,
                        mage_name=mage.name,
                        type_id=mage.type_id,
                        tag=tag,
                    )
                )
    return tuple(found)


# ------------------------------------------------------------------- resolving --


def resolve_spell(
    definition: SpellDefinition,
    mages: Sequence[DeployedMage],
    support: Mapping[MageTag, int] | None = None,
) -> ResolvedSpell:
    """Apply this plan's tag support to one definition.

    Each scaling entry is applied to its own field of its own effect,
    independently, additively, and capped. Nothing multiplies and nothing reads
    school resonance: JQ-292 replaced player-spell resonance scaling with this,
    and `resonance.py` continues to scale units only.
    """
    counts = dict(tag_support(mages)) if support is None else dict(support)

    effects = list(definition.effects)
    scaled: list[ScaledField] = []
    for entry in definition.scaling:
        count = counts.get(entry.tag, 0)
        base = read_field(definition.effects[entry.effect_index], entry.field)
        bonus = entry.bonus_at(count)
        # `>=` rather than `>`: a curve that lands exactly on its cap is bound
        # by it, and the boundary hazard `CONVENTIONS.md` documents for geometry
        # is the same one here — a strict test would report the first capped
        # value as uncapped.
        capped = entry.per_mage * max(0, count - entry.threshold) >= entry.cap > 0
        effects[entry.effect_index] = write_field(effects[entry.effect_index], entry.field, base + bonus)
        scaled.append(
            ScaledField(
                effect_index=entry.effect_index,
                field=entry.field,
                tag=entry.tag,
                support=count,
                base=base,
                bonus=bonus,
                value=base + bonus,
                capped=capped,
            )
        )

    return ResolvedSpell(
        definition_id=definition.id,
        name=definition.name,
        cost=definition.cost,
        text=definition.text,
        access=access_kind(definition.access),
        effects=tuple(effects),
        scaled=tuple(scaled),
        contributors=_contributors(definition, mages),
        granted_by=_granting_instances(definition, mages),
    )


def _granting_instances(definition: SpellDefinition, mages: Sequence[DeployedMage]) -> tuple[str, ...]:
    if not isinstance(definition.access, SignatureOf):
        return ()
    return tuple(mage.instance_id for mage in mages if mage.type_id == definition.access.mage_type_id)


def _eligibility(
    definition: SpellDefinition,
    mages: Sequence[DeployedMage],
    roster_access: Sequence[str],
    support: Mapping[MageTag, int],
) -> tuple[bool, str | None]:
    """Whether this spell may be equipped, and the reason when it may not.

    The reason is written for the player rather than for a log — it is what the
    greyed card says, and JQ-293's screen shows it rather than hiding the spell.
    """
    access = definition.access

    if isinstance(access, AlwaysAvailable):
        return True, None

    if isinstance(access, SignatureOf):
        if any(mage.type_id == access.mage_type_id for mage in mages):
            return True, None
        return False, "needs its mage on the field"

    # `IndependentAccess` — the last arm of the union, so mypy proves there is
    # no fourth case to fall through to and an `else` here would be dead code.
    if definition.id not in roster_access:
        # Never "you do not carry it and also lack the tag": which of the two it
        # was would enumerate a roster the player does not own.
        return False, "is not on this roster"
    if access.requires_tag is None:
        return True, None
    count = support.get(access.requires_tag, 0)
    if count >= access.minimum:
        return True, None
    if access.minimum == 1:
        return False, f"needs a fielded {access.requires_tag} mage"
    return False, f"needs {access.minimum} fielded {access.requires_tag} mages"


def resolve_menu(
    *,
    mages: Sequence[DeployedMage],
    roster_access: Sequence[str] = (),
    definitions: SpellDefinitionCatalog,
) -> LoadoutMenu:
    """The whole menu for one plan: what is offered, why, and with what numbers.

    One entry per spell definition, in catalog order — so two deployed copies of
    a mage put their shared signature on the menu once, named once, and priced
    once. `granted_by` still carries both instances.

    Ineligible spells are resolved too. The numbers on a greyed card are the
    numbers it would have at this plan's current tag support, which is what lets
    the screen show what fielding the missing mage would buy.

    No `rules` argument: the whole menu is offered whatever the slot policy is,
    and how many of it a player may take is `resolve_slots`' question.
    """
    support = dict(tag_support(mages))

    entries: list[MenuEntry] = []
    for definition in definitions.values():
        eligible, reason = _eligibility(definition, mages, roster_access, support)
        entries.append(
            MenuEntry(
                spell=resolve_spell(definition, mages, support),
                eligible=eligible,
                reason=reason,
            )
        )

    return LoadoutMenu(entries=tuple(entries), tag_support=tuple(sorted(support.items())))


# ---------------------------------------------------------------------- slots --


def resolve_slots(
    menu: LoadoutMenu,
    selection: Sequence[str | None],
    rules: LoadoutRules = DEFAULT_LOADOUT_RULES,
) -> tuple[SlotOutcome, ...]:
    """Each slot of a selection against a menu, in screen order.

    An empty slot is legal; a slot holding something the current troops no
    longer support is `stranded` and blocks lock-in. It is reported rather than
    silently cleared — the player chose that spell and should be told it went
    away, not discover an empty slot (§10 #32).
    """
    if len(selection) > rules.slots:
        raise LoadoutError(f"a plan carries at most {rules.slots} spells")

    outcomes: list[SlotOutcome] = []
    for index, definition_id in enumerate(selection):
        if definition_id is None:
            outcomes.append(SlotOutcome(index=index, definition_id=None))
            continue
        entry = menu.entry(definition_id)
        if entry is None:
            outcomes.append(
                SlotOutcome(
                    index=index,
                    definition_id=definition_id,
                    eligible=False,
                    reason="is not a spell on this roster",
                )
            )
            continue
        outcomes.append(
            SlotOutcome(
                index=index,
                definition_id=definition_id,
                spell=entry.spell,
                eligible=entry.eligible,
                reason=entry.reason,
            )
        )
    return tuple(outcomes)


def preserved_selection(
    menu: LoadoutMenu,
    previous: Sequence[str | None],
    rules: LoadoutRules = DEFAULT_LOADOUT_RULES,
) -> tuple[str | None, ...]:
    """Last round's slots, with the ones that are still legal kept.

    The other half of `reselect_each_round`: the slots are chosen again, but a
    player who fielded the same troops does not retype the same two spells. A
    choice that is no longer eligible becomes an empty slot needing a legal
    replacement rather than a stranded one, because a *new* round has no
    selection to strand — this is what the player is handed to edit.
    """
    if not rules.reselect_each_round:
        return tuple(previous[: rules.slots])
    eligible = menu.eligible_ids()
    kept = [spell_id if spell_id in eligible else None for spell_id in previous[: rules.slots]]
    kept.extend([None] * (rules.slots - len(kept)))
    return tuple(kept)


# ------------------------------------------------------------------- snapshot --


@dataclass(frozen=True, slots=True)
class LoadoutSnapshot:
    """One seat's spells, frozen at lock-in. The battle reads nothing else.

    Nothing in here can be recomputed from the world, which is the point: the
    round holds a snapshot, so a battle in which every contributing mage dies
    resolves its spells exactly as the plan screen priced them.
    """

    namespace: str
    spells: tuple[ResolvedSpell, ...] = ()
    tag_support: tuple[tuple[MageTag, int], ...] = ()
    rules: LoadoutRules = DEFAULT_LOADOUT_RULES
    round_number: int = 1

    def sim_spell_id(self, definition_id: str) -> str:
        """The id the sim's catalog holds this seat's copy of the spell under.

        Namespaced by side. Both seats can equip Fireball and resolve it to
        different damage, and `BattleSetup.spells` is a single catalog — so
        without this the second army silently overwrites the first's numbers.
        The namespaced id never crosses the wire; a client names the definition.
        """
        return f"{self.namespace}:{definition_id}"

    def sim_spells(self) -> list[Spell]:
        """This seat's contribution to the battle's spell catalog."""
        return [
            Spell(id=self.sim_spell_id(spell.definition_id), effects=spell.effects) for spell in self.spells
        ]

    def spell(self, definition_id: str) -> ResolvedSpell | None:
        for candidate in self.spells:
            if candidate.definition_id == definition_id:
                return candidate
        return None


def snapshot_loadout(
    *,
    namespace: str,
    mages: Sequence[DeployedMage],
    selection: Sequence[str | None],
    roster_access: Sequence[str] = (),
    definitions: SpellDefinitionCatalog,
    rules: LoadoutRules = DEFAULT_LOADOUT_RULES,
    round_number: int = 1,
) -> LoadoutSnapshot:
    """Freeze this plan's spells for the round. Raises on an illegal selection.

    The raise is deliberate belt-and-braces. `plan.validate_plan` refuses a
    stranded slot first, with a message naming the spell; reaching here with one
    means something bypassed validation, and taking a snapshot of an illegal
    loadout would put a button on the screen that the round would then refuse to
    honour.
    """
    if not rules.snapshot_at_lock_in:
        raise LoadoutError(
            "snapshot_at_lock_in is off, and resolving a loadout live is not implemented: "
            "the battle's spell catalog is built once from the snapshot, so a re-priced "
            "loadout would show one number and fire another"
        )

    menu = resolve_menu(mages=mages, roster_access=roster_access, definitions=definitions)
    outcomes = resolve_slots(menu, selection, rules)

    for outcome in outcomes:
        if outcome.stranded:
            raise LoadoutError(f"spell {outcome.index + 1} — {outcome.definition_id} {outcome.reason}")

    spells: list[ResolvedSpell] = []
    for outcome in outcomes:
        if outcome.spell is None:
            continue
        # A slot filled twice is one spell in the catalog. Two buttons for one
        # id would make `sim_spells` build a catalog with a duplicate key, which
        # `build_spell_catalog` refuses — correctly, and unhelpfully late.
        if any(spell.definition_id == outcome.spell.definition_id for spell in spells):
            continue
        spells.append(outcome.spell)

    return LoadoutSnapshot(
        namespace=namespace,
        spells=tuple(spells),
        tag_support=menu.tag_support,
        rules=rules,
        round_number=round_number,
    )


# --------------------------------------------------------------------- display --


def _number(value: float) -> str:
    """A number as the summary prints it. `:g` so 54.0 is `54` in both languages."""
    return f"{value:g}"


def _label(path: str) -> str:
    """A field path as a sentence reads it. `damage.amount` -> `damage amount`.

    The whole path rather than its last segment: a bare `amount` next to a
    `radius` says nothing about which of a spell's numbers moved, and two
    effects in one spell can each have one.
    """
    return path.replace(".", " ").replace("_", " ")


def effect_summary(spell: ResolvedSpell) -> str:
    """One sentence naming the spell's resolved numbers and what raised them.

    A *server-side* sentence, and the one place this module makes a display
    decision. JQ-190 owns what the plan and cast screens actually draw; this
    exists because the wire has carried an `effect` string since JQ-311 and a
    client is entitled to something honest in it without parsing the scaling.

    Honest in the sense JQ-297's last criterion asks for: it reports what the
    numbers *are*, and says nothing about what they would kill.
    """
    if not spell.scaled:
        return spell.text

    parts: list[str] = []
    for entry in spell.scaled:
        name = _label(entry.field)
        if entry.bonus == 0:
            parts.append(f"{name} {_number(entry.value)}")
            continue
        tail = ", at its cap" if entry.capped else ""
        plural = "" if entry.support == 1 else "s"
        parts.append(
            f"{name} {_number(entry.value)} "
            f"(+{_number(entry.bonus)} from {entry.support} {entry.tag} mage{plural}{tail})"
        )
    return f"{spell.text} {'; '.join(parts)}."


# ------------------------------------------------------------------- fixtures --


def resolved_spell_to_json(spell: ResolvedSpell) -> dict[str, Any]:
    """A resolved spell as the cross-language conformance fixtures carry it.

    Only what both implementations must agree on. `text` and the summary
    sentence are left out on purpose: a wording change in one language should
    not fail the other's conformance run, and the claim being pinned is about
    numbers.
    """
    return {
        "spellId": spell.definition_id,
        "name": spell.name,
        "cost": spell.cost,
        "access": spell.access,
        "effects": [effect_to_json(effect) for effect in spell.effects],
        "scaled": [
            {
                "effectIndex": entry.effect_index,
                "field": camel_path(entry.field),
                "tag": entry.tag,
                "support": entry.support,
                "base": entry.base,
                "bonus": entry.bonus,
                "value": entry.value,
                "capped": entry.capped,
            }
            for entry in spell.scaled
        ],
        "contributors": [
            {"mageId": who.instance_id, "mageName": who.mage_name, "tag": who.tag}
            for who in spell.contributors
        ],
        "grantedBy": list(spell.granted_by),
    }


def menu_to_json(menu: LoadoutMenu) -> dict[str, Any]:
    return {
        "tagSupport": [{"tag": tag, "count": count} for tag, count in menu.tag_support],
        "entries": [
            {
                "eligible": entry.eligible,
                "reason": entry.reason,
                "spell": resolved_spell_to_json(entry.spell),
            }
            for entry in menu.entries
        ],
    }


def snapshot_to_json(snapshot: LoadoutSnapshot) -> dict[str, Any]:
    return {
        "namespace": snapshot.namespace,
        "tagSupport": [{"tag": tag, "count": count} for tag, count in snapshot.tag_support],
        "spells": [resolved_spell_to_json(spell) for spell in snapshot.spells],
        "simSpellIds": [snapshot.sim_spell_id(spell.definition_id) for spell in snapshot.spells],
    }


def definition_to_json(definition: SpellDefinition) -> dict[str, Any]:
    """A definition as the shared fixture carries it, so both sides read one source."""
    access = definition.access
    if isinstance(access, SignatureOf):
        access_json: dict[str, Any] = {"kind": "signature", "mageTypeId": access.mage_type_id}
    elif isinstance(access, IndependentAccess):
        access_json = {"kind": "independent", "requiresTag": access.requires_tag, "minimum": access.minimum}
    else:
        access_json = {"kind": "fallback"}

    return {
        "id": definition.id,
        "name": definition.name,
        "cost": definition.cost,
        "text": definition.text,
        "access": access_json,
        "effects": [effect_to_json(effect) for effect in definition.effects],
        "scaling": [
            {
                "effectIndex": entry.effect_index,
                "field": camel_path(entry.field),
                "tag": entry.tag,
                "perMage": entry.per_mage,
                "cap": entry.cap,
                "threshold": entry.threshold,
            }
            for entry in definition.scaling
        ],
    }


def mage_to_json(mage: DeployedMage) -> dict[str, Any]:
    return {
        "instanceId": mage.instance_id,
        "typeId": mage.type_id,
        "name": mage.name,
        "tags": list(mage.tags),
    }


def deployed_mages(entries: Iterable[tuple[str, str, str, Sequence[str]]]) -> list[DeployedMage]:
    """`(instance_id, type_id, name, tags)` tuples as `DeployedMage`s. Test sugar."""
    return [
        DeployedMage(instance_id=instance, type_id=type_id, name=name, tags=tuple(tags))
        for instance, type_id, name, tags in entries
    ]
