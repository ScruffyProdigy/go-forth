"""The sim is a pure module. This is what makes that a fact, not a convention.

It walks the import graph reachable from `app/sim/__init__.py` and fails if
anything in it can reach outside the sim. The graph is parsed with `ast` rather
than scanned with regexes, because Python docstrings are strings rather than
comments — a source scan would flag this very package's prose about not using
`random` as a use of `random`.
"""

import ast
import pathlib

SIM_DIR = pathlib.Path(__file__).resolve().parent.parent / "app" / "sim"
ENTRY = SIM_DIR / "__init__.py"

#: Anything that reaches the outside world, or that is not reproducible.
FORBIDDEN_MODULES = {
    "os",
    "sys",
    "io",
    "pathlib",
    "shutil",
    "tempfile",
    "glob",
    "random",
    "secrets",
    "uuid",
    "time",
    "datetime",
    "calendar",
    "subprocess",
    "socket",
    "threading",
    "multiprocessing",
    "asyncio",
    "logging",
    "http",
    "urllib",
    "requests",
    "httpx",
}
#: Builtins that do I/O without importing anything.
FORBIDDEN_CALLS = {"print", "open", "input", "eval", "exec", "compile", "__import__"}


def _module_path(name: str) -> pathlib.Path:
    relative = name.split(".")
    candidate = SIM_DIR.parent.parent / pathlib.Path(*relative)
    return (
        candidate / "__init__.py"
        if candidate.is_dir()
        else candidate.with_suffix(".py")
    )


def _import_graph() -> dict[pathlib.Path, ast.Module]:
    """Every module `run_battle` can reach, the entry point included."""
    seen: dict[pathlib.Path, ast.Module] = {}
    queue: list[pathlib.Path] = [ENTRY]

    while queue:
        path = queue.pop()
        if path in seen:
            continue

        tree = ast.parse(path.read_text(), filename=str(path))
        seen[path] = tree

        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]

            for name in names:
                if name.startswith("app."):
                    queue.append(_module_path(name))

    return seen


GRAPH = _import_graph()


def _imported_modules(tree: ast.Module) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def _relative(path: pathlib.Path) -> str:
    return str(path.relative_to(SIM_DIR.parent))


def test_the_walk_actually_walks() -> None:
    assert len(GRAPH) > 5


def test_imports_nothing_that_reaches_the_outside_world() -> None:
    offenders = [
        f"{_relative(path)} imports {module}"
        for path, tree in GRAPH.items()
        for module in _imported_modules(tree)
        if module.split(".")[0] in FORBIDDEN_MODULES
    ]

    assert offenders == []


def test_imports_nothing_from_the_app_outside_the_sim() -> None:
    """The equivalent of the TypeScript version's ban on importing from client/."""
    offenders = [
        f"{_relative(path)} imports {module}"
        for path, tree in GRAPH.items()
        for module in _imported_modules(tree)
        if module.startswith("app.") and not module.startswith("app.sim")
    ]

    assert offenders == []


def test_never_calls_a_builtin_that_does_io() -> None:
    offenders = [
        f"{_relative(path)} calls {node.func.id}"
        for path, tree in GRAPH.items()
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in FORBIDDEN_CALLS
    ]

    assert offenders == []


def test_every_module_in_the_graph_lives_under_the_sim() -> None:
    for path in GRAPH:
        assert SIM_DIR in path.parents or path == ENTRY
