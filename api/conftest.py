"""Makes `app` importable from `api/` when pytest runs.

pytest prepends the directory of the topmost `conftest.py` to `sys.path`, which
is what lets `tests/` sit outside the package and still `import app.sim`. Once
the scaffold's `pyproject.toml` lands this can become
`[tool.pytest.ini_options] pythonpath = ["."]` instead.
"""
