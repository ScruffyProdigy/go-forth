"""The JoinQuest Lobby contract.

Everything the platform talks to, and nothing about Go Forth! itself. The split
is the point of this package: `app/match/` decides what a battle is, and this
decides who is allowed into one and what the Lobby is told about it afterwards.

The wire contract here is **fixed** — it must match rpslr exactly, because the
two are the same contract in two languages (`api/CONVENTIONS.md`). Module names
therefore track rpslr's file names rather than being renamed to Python taste:

    rpslr (TypeScript)      go-forth (Python)
    ------------------      -----------------
    gameModes.ts            manifest.py
    lobbyIssuer.ts          issuer.py
    tokens.ts               tokens.py
    provision.ts            provision.py
    launchUrls.ts           launch_urls.py
    lobbyClient.ts          client.py
    seatBinding.ts          seat_binding.py

A developer holding the integration guide's §8 table in one hand should be able
to find the row in either repo without a map. `docs/python-vs-typescript.md`
records where the two languages genuinely diverge.
"""
