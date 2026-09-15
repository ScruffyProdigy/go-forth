"""Go Forth!'s own game layer: what a match is, and what crosses the wire.

The split from `app/lobby/` is deliberate. That package speaks a contract fixed
by the platform and shared with rpslr; this one is this game and nothing else.
A change here cannot break the integration checks, and a change there cannot
change the game.

    wire.py       every byte between server and client — and the one thing that
                  must never become `sim/serialize.py`
    fixtures.py   the explicit round fixtures the opening demo runs on
    plan.py       reading, refusing and fielding a submitted plan
    round.py      one round: the sim stepped under seat commands
    session.py    the match: seats, phases, and the terminal result
    clock.py      the only module that knows what a second is
    hub.py        in-process fan-out to the sockets watching a match
"""
