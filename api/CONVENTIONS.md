# Conventions for the Go Forth! API

Go Forth!'s api is the **Python** reference implementation for JoinQuest. rpslr
and wordhunt cover TypeScript; this one exists so a Python developer — or their
agent — has something to read in the language they are actually writing.

That shapes two rules that override ordinary taste:

1. **The wire contract is fixed.** It must match rpslr exactly. Only the
   implementation is Python. If something here reads better with a different
   payload shape, it is still wrong.
2. **The architecture should match too.** The only difference between the
   references should be the language. That is why migrations are plain SQL
   files with a small in-repo runner rather than Alembic: someone comparing
   rpslr to go-forth to learn the JoinQuest contract should not have to learn a
   migration framework on the way.

## Determinism

JQ-186 requires the battle sim to be byte-identical across runs. Python makes
that harder than TypeScript did, in a way that is invisible if you port by
reading.

**Python randomizes string hashing per process.** Iterating a `set` gives a
different order in every fresh interpreter. Measured on eight plain strings:

```
in-process, two iterations identical: True
distinct set-iteration orders across 8 fresh processes: 8
```

TypeScript has no such hazard — its `Set` iterates in insertion order — so code
that was correct there becomes non-deterministic here with no visible change.

**The rules:**

- Use `set` for membership tests only. Never iterate one where the order can
  reach output.
- Never iterate a `dict` keyed by anything whose order matters unless you
  control insertion order deliberately.
- Sort explicitly when order matters. `sorted(...)` on a stable key, not
  whatever the container hands back.
- Seed an explicit `random.Random(seed)`. Never touch module-level `random`,
  which shares global state with everything else in the process.

**Testing it:** a determinism test must spawn a real subprocess.

```python
out = {
    subprocess.run([sys.executable, "-c", SCRIPT], capture_output=True, text=True, check=True).stdout
    for _ in range(5)
}
assert len(out) == 1
```

`PYTHONHASHSEED` is fixed once at interpreter startup, and **pytest runs the
whole suite in one interpreter**. Running the sim twice inside a test therefore
samples a single hash seed and passes unconditionally — it is the shape of test
most people write for this, and the one shape that proves nothing. This was
confirmed by deliberately breaking the removal phase to iterate a set of ids:
every in-process test still passed; only the fresh-interpreter ones failed.

For the same reason, **`PYTHONHASHSEED` must never be pinned in CI.** Pinning it
is the natural-looking fix for a determinism "flake", and it disarms every such
test everywhere while turning them green. `api-tests.yml` asserts it is unset.

## Porting from the TypeScript

**Capture golden vectors from the old implementation before deleting it.**

A wrong transliteration is still perfectly deterministic. The JQ-286 port of
mulberry32 XORed the wrong operand and shifted 15 where the JavaScript shifts
14, and produced a stable, reproducible, entirely different sequence — passing
every determinism test it had. Only output captured from the TypeScript caught
it.

**Retire a golden vector when the behaviour it pins is superseded, rather than
teaching the sim to reproduce it.** `tests/sim/golden_battles.json` proved the
JQ-286 port matched the TypeScript, which is a claim about one moment: slice B
(JQ-287) replaces the movement rule those battles encode — everybody marches at
the enemy base — with orders and derived formations, so no correct
implementation of slice B can reproduce them. Keeping them green would have
meant keeping a superseded rule alive behind a flag. The PRNG vectors in
`test_rng.py` pin the generator rather than the game and are untouched.

**Compare across languages by parsed value, not by bytes.** Python and
JavaScript format some floats differently in JSON (`1e+21` vs `1e21`, `1e-06`
vs `0.000001`). Byte-identical determinism means *one implementation
reproducing its own output* — not two languages agreeing on float formatting.
Those are different claims, and conflating them sends you chasing an impossible
one.

## Layout

```
api/
├── pyproject.toml   # deps, ruff, mypy and pytest config, all in one file
├── app/
│   ├── main.py      # the FastAPI factory
│   ├── server.py    # binds the port: `python -m app.server`
│   ├── config.py    # environment, with defaults that run without a .env
│   └── sim/         # the battle sim (JQ-286)
├── migrations/      # forward-only *.sql, applied in filename order
└── tests/           # not co-located; the Python convention, unlike rpslr
```

`tests/` sits outside the package, so `pyproject.toml` puts `.` on the path via
`[tool.pytest.ini_options] pythonpath`.

## Toolchain

Python 3.12. `pip install -e ".[dev]"` from `api/` is the documented path and
needs nothing beyond a virtualenv; [uv](https://docs.astral.sh/uv/) reads the
same `pyproject.toml` and is faster if you have it, but nothing requires it —
a reference implementation should ask a reader to install as little as
possible.

```bash
ruff check .          # lint
ruff format .         # format
mypy app tests        # strict
pytest                # tests
```

All four run in CI on every change under `api/`.
