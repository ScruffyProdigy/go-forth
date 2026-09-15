"""Shared tactical behavior: one decision system for mages and summons alike.

The parent ticket's rule (JQ-296) is that adding a creature which uses existing
mechanics should cost **data, not code**. So nothing in here branches on a
creature id. A unit's behavior is the sum of three pieces of data —

* the **creature-type profile**: defaults for everything of that type,
* **individual trait overrides**: this one hound is skittish,
* **mage personality references**: the mage leading the troop is reckless —

composed into one set of factor weights, which then scale a fixed set of bounded
scores. Two units with identical stats and different trait data prefer different
actions; two units with identical data behave identically. That is the whole
contract.

The loop is observe -> generate legal candidates -> score -> select -> execute,
and the last step is deliberately *not* done here: the decision phase commits an
intent to the unit and the existing movement and combat phases carry it out. One
mover, one damager, no double application.

=================  ============================================================
Module             What it owns
=================  ============================================================
`factors`          the four things any action is judged on
`capabilities`     what a unit can do, read off its live stats
`profiles`         behavior as data, and how the pieces compose
`intent`           what a unit committed to; lives on `Unit`
`objective`        the read-only seam onto JQ-287's orders
`observe`          one unit's view of the field, gathered once
`candidates`       every legal action, in stable order
`scoring`          the four bounded verdicts
`decide`           select, and explain
`attach`           compose every unit's behavior at battle start
`fixtures`         sample data for everyone downstream
=================  ============================================================

**Nothing is re-exported from this package.** `world.py` imports `ai.attach`, so
anything imported here would run while `world` was still half-built — and
`ai.objective` imports `world`. Import the submodule you want; the public surface
is published from `app/sim/__init__.py`, alongside the rest of the sim's.
"""
