"""Shell completion preamble for shtab integration.

This module exports PREAMBLE, a dict mapping shell names to preamble
script fragments that shtab prepends to the generated completion script.

The bash and zsh entries define kanon-specific shell helper functions for
dynamic argument completion. Each helper shells out to the corresponding
``kanon __complete_<name>`` subcommand to retrieve candidate lists.

Environment variables honoured by every helper:

- ``KANON_COMPLETION_ENABLED`` (default: ``1``) -- when set to ``0``, the
  helper returns the empty candidate list immediately without invoking the
  kanon subprocess.
- ``KANON_COMPLETION_TIMEOUT`` (default: ``2``) -- number of seconds passed
  to ``timeout``(1) wrapping the kanon subprocess call. When ``timeout``(1)
  is not on ``$PATH``, the subprocess relies on kanon's own internal timeout
  (also bounded by this variable).

The mid-token splitter helper (``_kanon_complete_add_arg``) ships with a
placeholder body that calls ``_kanon_complete_catalog_entries``
unconditionally. E7-F2-S1-T7 replaces the body with the full ``@``-splitting
logic.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Bash preamble
# ---------------------------------------------------------------------------
#
# Design:
# - ``_kanon_run_complete <subcommand> [extra_args...]`` is the single
#   dispatch function that handles the KANON_COMPLETION_ENABLED guard,
#   the timeout(1) wrapper, and COMPREPLY population.  Every named helper
#   simply calls it with the correct subcommand name and $cur.
# - ``_kanon_complete_project_versions`` also passes a positional $repo_url
#   argument before $cur as required by the spec.
#
_BASH_PREAMBLE = r"""
# kanon shell-completion preamble (bash)
# Sourced by the generated completion script produced by `kanon completion bash`.

# _kanon_run_complete <subcommand> [args...]
#
# Common dispatcher called by every named helper.
# Respects KANON_COMPLETION_ENABLED and KANON_COMPLETION_TIMEOUT.
_kanon_run_complete() {
    local _subcommand="$1"
    shift
    # Honour KANON_COMPLETION_ENABLED (default 1 = enabled).
    if [[ "${KANON_COMPLETION_ENABLED:-1}" == "0" ]]; then
        COMPREPLY=()
        return 0
    fi
    local _timeout="${KANON_COMPLETION_TIMEOUT:-2}"
    local _output
    if command -v timeout > /dev/null 2>&1; then
        _output=$(timeout "$_timeout" kanon "$_subcommand" "$@" 2>/dev/null) || true
    else
        _output=$(kanon "$_subcommand" "$@" 2>/dev/null) || true
    fi
    mapfile -t COMPREPLY < <(compgen -W "$_output" -- "${cur:-}")
}

_kanon_complete_catalog_entries() {
    local cur="${1:-}"
    _kanon_run_complete __complete_catalog_entries "$cur"
}

_kanon_complete_source_names_in_kanon() {
    local cur="${1:-}"
    _kanon_run_complete __complete_source_names_in_kanon "$cur"
}

_kanon_complete_names_in_lockfile() {
    local cur="${1:-}"
    _kanon_run_complete __complete_names_in_lockfile "$cur"
}

_kanon_complete_catalog_versions() {
    local cur="${1:-}"
    _kanon_run_complete __complete_catalog_versions "$cur"
}

_kanon_complete_project_versions() {
    local repo_url="${1:-}"
    local cur="${2:-}"
    _kanon_run_complete __complete_project_versions "$repo_url" "$cur"
}

_kanon_complete_cached_catalogs() {
    local cur="${1:-}"
    _kanon_run_complete __complete_cached_catalogs "$cur"
}

# _kanon_complete_add_arg -- mid-token splitter helper (placeholder body).
# E7-F2-S1-T7 replaces this body with the full @-splitting logic.
_kanon_complete_add_arg() {
    local cur="${1:-}"
    _kanon_complete_catalog_entries "$cur"
}
"""

# ---------------------------------------------------------------------------
# Zsh preamble
# ---------------------------------------------------------------------------
#
# Design mirrors the bash preamble:
# - ``_kanon_run_complete <subcommand> [args...]`` handles the guard and the
#   timeout wrapper, then calls ``compadd`` with the candidate list.
# - Each named helper delegates to ``_kanon_run_complete``.
#
_ZSH_PREAMBLE = r"""
# kanon shell-completion preamble (zsh)
# Sourced by the generated completion script produced by `kanon completion zsh`.

# _kanon_run_complete <subcommand> [args...]
#
# Common dispatcher called by every named helper.
# Respects KANON_COMPLETION_ENABLED and KANON_COMPLETION_TIMEOUT.
_kanon_run_complete() {
    local _subcommand="$1"
    shift
    # Honour KANON_COMPLETION_ENABLED (default 1 = enabled).
    if [[ "${KANON_COMPLETION_ENABLED:-1}" == "0" ]]; then
        return 0
    fi
    local _timeout="${KANON_COMPLETION_TIMEOUT:-2}"
    local -a _lines
    if command -v timeout > /dev/null 2>&1; then
        _lines=("${(@f)$(timeout "$_timeout" kanon "$_subcommand" "$@" 2>/dev/null)}")
    else
        _lines=("${(@f)$(kanon "$_subcommand" "$@" 2>/dev/null)}")
    fi
    # Filter empty lines that result from trailing newlines in subprocess output.
    local -a _candidates
    local _item
    for _item in "${_lines[@]}"; do
        [[ -n "$_item" ]] && _candidates+=("$_item")
    done
    [[ ${#_candidates[@]} -gt 0 ]] && compadd -- "${_candidates[@]}"
}

_kanon_complete_catalog_entries() {
    local cur="${1:-}"
    _kanon_run_complete __complete_catalog_entries "$cur"
}

_kanon_complete_source_names_in_kanon() {
    local cur="${1:-}"
    _kanon_run_complete __complete_source_names_in_kanon "$cur"
}

_kanon_complete_names_in_lockfile() {
    local cur="${1:-}"
    _kanon_run_complete __complete_names_in_lockfile "$cur"
}

_kanon_complete_catalog_versions() {
    local cur="${1:-}"
    _kanon_run_complete __complete_catalog_versions "$cur"
}

_kanon_complete_project_versions() {
    local repo_url="${1:-}"
    local cur="${2:-}"
    _kanon_run_complete __complete_project_versions "$repo_url" "$cur"
}

_kanon_complete_cached_catalogs() {
    local cur="${1:-}"
    _kanon_run_complete __complete_cached_catalogs "$cur"
}

# _kanon_complete_add_arg -- mid-token splitter helper (placeholder body).
# E7-F2-S1-T7 replaces this body with the full @-splitting logic.
_kanon_complete_add_arg() {
    local cur="${1:-}"
    _kanon_complete_catalog_entries "$cur"
}
"""

PREAMBLE: dict[str, str] = {
    "bash": _BASH_PREAMBLE,
    "zsh": _ZSH_PREAMBLE,
}
