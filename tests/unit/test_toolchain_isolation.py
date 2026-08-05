"""Guards on the single dependency-resolution path.

CI once resolved dependencies two ways: the tiered test jobs installed with
``pip install -r requirements-dev.txt``, which resolves from PyPI at run time,
while ``make test`` ran under ``uv run`` and honoured ``uv.lock``. The two
manifests disagreed, so the same suite ran under different tool versions
depending on the job, and an unpinned ``shtab`` release broke the completion
golden fixtures in the pip-based jobs only.

That split is closed: ``requirements-dev.txt`` is gone and every Make target
invokes its tools through ``uv run``. Nothing enforced it, though -- the
conditions that let it happen are ordinary edits to the Makefile or
``pyproject.toml``. These tests encode the three invariants that keep the path
single, each derived from a defect this repository actually hit:

1. A tool invoked through ``uv run`` is declared in ``[dependency-groups]``.
   ``make security-scan`` was ``uv run bandit`` while bandit was declared
   nowhere, so ``uv run`` fell through to ``PATH`` and silently executed a
   system-wide bandit -- an undeclared dependency deciding a security gate.
2. No Make recipe invokes a tool directly. A bare ``ruff check .`` resolves
   from ``PATH`` rather than the lock, which is the drift this all removes.
3. A dependency whose *output* is byte-compared against a committed fixture
   carries an upper bound. ``shtab>=1.7.0`` let shtab 1.9.0 change its
   generated completion script and break CI with no repository change.
"""

import pathlib
import re
import tomllib

import pytest


REPO_ROOT = pathlib.Path(__file__).parents[2]
MAKEFILE_PATH = REPO_ROOT / "Makefile"
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"

_ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=\S*$")
_REQUIREMENT_NAME_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")

_INTERPRETER = "python"
_OWN_ENTRY_POINT = "kanon"
_RUNNER = "uv"

_EXEMPT_FROM_DECLARATION = frozenset({_INTERPRETER, _OWN_ENTRY_POINT})

_TOOLS_THAT_MUST_GO_THROUGH_UV = frozenset(
    {
        "bandit",
        "coverage",
        "pip",
        "pre-commit",
        "pymarkdownlnt",
        "pytest",
        "python",
        "python3",
        "ruff",
        "semantic-release",
        "twine",
        "yamllint",
    }
)

_OUTPUT_SHAPING_DEPENDENCIES = ("shtab",)


def _recipe_lines() -> list[str]:
    """Return every recipe line in the Makefile, tabs and comments stripped.

    Returns:
        Recipe bodies in file order, excluding blank and comment-only lines.
    """
    lines: list[str] = []
    for raw in MAKEFILE_PATH.read_text(encoding="utf-8").splitlines():
        if not raw.startswith("\t"):
            continue
        body = raw.lstrip("\t").strip()
        if body and not body.startswith("#"):
            lines.append(body)
    return lines


def _declared_dev_dependencies() -> set[str]:
    """Return the distribution names declared in ``[dependency-groups] dev``.

    Returns:
        Lower-cased requirement names with version specifiers removed.
    """
    with PYPROJECT_PATH.open("rb") as fh:
        data = tomllib.load(fh)
    names: set[str] = set()
    for requirement in data.get("dependency-groups", {}).get("dev", []):
        match = _REQUIREMENT_NAME_RE.match(requirement.strip())
        if match:
            names.add(match.group(1).lower())
    return names


def _uv_run_tools(recipe: str) -> list[str]:
    """Return the executables *recipe* invokes through ``uv run``.

    Deliberately tokenizes rather than pattern-matching. A regex able to skip
    ``uv run``'s own flags needs a repeated optional group, which backtracks
    exponentially on adversarial input -- CodeQL's ``py/redos``. Walking tokens
    is linear in the length of the line and easier to follow.

    Any token starting with ``-`` after ``run`` is treated as a flag to uv
    itself and skipped, so a flag written as ``--flag=value`` is handled. A flag
    taking a detached value (``--flag value``) would misreport that value as the
    tool; no target uses that form, and the assertion messages name the line, so
    a future one would be obvious rather than silent.

    Args:
        recipe: A single recipe line, already stripped of its leading tab.

    Returns:
        One entry per ``uv run`` invocation in the line, in order.
    """
    tools: list[str] = []
    tokens = recipe.split()
    index = 0
    while index < len(tokens) - 1:
        if tokens[index] == _RUNNER and tokens[index + 1] == "run":
            candidate = index + 2
            while candidate < len(tokens) and tokens[candidate].startswith("-"):
                candidate += 1
            if candidate < len(tokens):
                tools.append(tokens[candidate])
            index = candidate
            continue
        index += 1
    return tools


def _command_heads(recipe: str) -> list[str]:
    """Return the executable invoked by each command in a recipe line.

    A recipe may chain commands with ``|``, ``&&`` or ``;``. Each command may be
    prefixed by make's ``@``/``-`` modifiers and any number of ``VAR=value``
    environment assignments, none of which is the executable.

    Args:
        recipe: A single recipe line, already stripped of its leading tab.

    Returns:
        The first real token of each command in the line.
    """
    heads: list[str] = []
    for command in re.split(r"\|\||&&|[|;]", recipe):
        tokens = command.strip().lstrip("@-").split()
        while tokens and _ENV_ASSIGNMENT_RE.match(tokens[0]):
            tokens = tokens[1:]
        if tokens:
            heads.append(tokens[0])
    return heads


@pytest.mark.unit
def test_every_uv_run_tool_is_declared_as_a_dev_dependency() -> None:
    """Verify each tool run via ``uv run`` is declared in ``[dependency-groups]``.

    Given: the Makefile and pyproject.toml at the repo root
    When: every ``uv run <tool>`` invocation is compared against the dev group
    Then: each tool is declared there

    ``uv run`` falls back to ``PATH`` for an undeclared executable rather than
    failing, so an omission is silent: ``make security-scan`` ran a system-wide
    bandit for as long as bandit was missing from this list. The interpreter and
    kanon's own console script are exempt -- the first is the environment, the
    second is provided by the editable install of this project.
    """
    declared = _declared_dev_dependencies()
    invoked = {tool for line in _recipe_lines() for tool in _uv_run_tools(line)}
    required = {tool for tool in invoked if tool not in _EXEMPT_FROM_DECLARATION}

    undeclared = sorted(tool for tool in required if tool.lower() not in declared)

    assert not undeclared, (
        f"Makefile runs {undeclared} through `uv run`, but they are not declared in "
        f"[dependency-groups].dev. `uv run` silently falls back to PATH for an "
        f"undeclared executable, so the target would use whatever version the host "
        f"happens to have instead of the locked one. Declared: {sorted(declared)}"
    )


@pytest.mark.unit
def test_no_make_recipe_invokes_a_tool_directly() -> None:
    """Verify every Make recipe reaches its tools through ``uv run``.

    Given: the Makefile at the repo root
    When: the executable of each command in each recipe is inspected
    Then: none of them is a tool that should come from the lock

    A bare ``ruff check .`` or ``pytest -m unit`` resolves from ``PATH``, which
    reintroduces exactly the two-path split that let an unpinned dependency
    break CI while the uv-based jobs stayed green.
    """
    offenders: list[str] = []
    for line in _recipe_lines():
        for head in _command_heads(line):
            if head != _RUNNER and head in _TOOLS_THAT_MUST_GO_THROUGH_UV:
                offenders.append(f"{head!r} in: {line}")

    assert not offenders, (
        "These Make recipes invoke a tool directly instead of through `uv run`, so "
        "they resolve from PATH rather than uv.lock:\n  " + "\n  ".join(offenders)
    )


@pytest.mark.unit
@pytest.mark.parametrize("dependency", _OUTPUT_SHAPING_DEPENDENCIES)
def test_output_shaping_dependency_has_an_upper_bound(dependency: str) -> None:
    """Verify a dependency whose output is snapshot-tested cannot float upward.

    Given: pyproject.toml at the repo root
    When: the requirement for *dependency* is read
    Then: it carries an exact pin or an upper bound

    ``tests/fixtures/completion/expected-*.sh`` are byte-for-byte comparisons
    against shtab's generated output. Under ``shtab>=1.7.0`` the 1.9.0 release
    changed that output and broke CI with no change to this repository. An
    upper bound makes such a break a deliberate, reviewable edit that arrives
    with regenerated fixtures via ``make update-completion-snapshots``.
    """
    with PYPROJECT_PATH.open("rb") as fh:
        data = tomllib.load(fh)

    matching = [
        requirement
        for requirement in data["project"]["dependencies"]
        if (_REQUIREMENT_NAME_RE.match(requirement.strip()) or [None])
        and _REQUIREMENT_NAME_RE.match(requirement.strip()).group(1).lower() == dependency
    ]
    assert matching, f"{dependency!r} must be declared in [project].dependencies"

    requirement = matching[0]
    bounded = "==" in requirement or "<" in requirement or "~=" in requirement
    assert bounded, (
        f"{requirement!r} lets {dependency} float upward, but its generated output is "
        f"compared byte-for-byte against committed fixtures. Pin it exactly or give it "
        f"an upper bound; regenerate fixtures with `make update-completion-snapshots` "
        f"when raising it."
    )
