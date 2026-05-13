"""Centralized constants for the kanon-cli package.

All module-level constants live here to avoid hard-coded values
scattered across source files.
"""

import os
import re

# -- Marketplace validation --
MARKETPLACE_DIR_PREFIX = "${CLAUDE_MARKETPLACES_DIR}/"
MARKETPLACE_FILE_GLOB = "*-marketplace.xml"
ALLOWED_BRANCHES = frozenset({"main"})
REFS_TAGS_RE = re.compile(r"^refs/tags/.+/\d+\.\d+\.\d+$")
CONSTRAINT_RE = re.compile(r"^(~=|>=|<=|>|<)\d+\.\d+\.\d+$")

# -- Version resolution --
PEP440_OPERATORS = ("~=", ">=", "<=", "!=", "==", ">", "<")
# Maximum number of non-PEP-440 tag names to include in a loud error message.
# Keeps error output bounded when a prefix matches many malformed tags.
TAG_ERROR_DISPLAY_CAP = 10

# -- kanonenv parsing --
SOURCE_PREFIX = "KANON_SOURCE_"
SOURCE_URL_SUFFIX = "_URL"
SOURCE_NON_URL_SUFFIXES = ("_REVISION", "_PATH")
SOURCE_SUFFIXES = (SOURCE_URL_SUFFIX,) + SOURCE_NON_URL_SUFFIXES
SUFFIX_TO_KEY = {"_URL": "url", "_REVISION": "revision", "_PATH": "path"}
SHELL_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")

# -- Catalog --
CATALOG_ENV_VAR = "KANON_CATALOG_SOURCE"

# -- List command error and notice strings --
# Canonical missing-catalog error template (spec Section 4 header, verbatim).
# Call with .format(command=<command-name>) to produce the final error string.
MISSING_CATALOG_ERROR_TEMPLATE = (
    "ERROR: {command} requires a catalog source.\n"
    "Provide one of:\n"
    "  --catalog-source <git-url>@<ref>      # e.g. --catalog-source https://example.com/org/manifest-repo.git@main\n"
    "  KANON_CATALOG_SOURCE=<git-url>@<ref>  # set as env var, then re-run\n"
    "\n"
    "The CLI flag takes precedence when both are set.\n"
    "A catalog source identifies a manifest repo (a git repository whose\n"
    "repo-specs/ directory exposes installable kanon dependencies).\n"
    "See docs/catalogs-explained.md for what a manifest repo is and how to find one.\n"
    "See docs/configuration.md for the full configuration reference."
)

# Stderr note emitted when the manifest repo contains zero marketplace XML files.
# Spec Section 4.1: "manifest repo contains 0 entries".
LIST_EMPTY_CATALOG_NOTE = "manifest repo contains 0 entries"

# -- Configuration file --
KANONENV_FILENAME = ".kanon"

# -- Embedded repo tool --
REPO_RESTART_RETRIES_DEFAULT = 3

# -- Repo CLI --
KANON_REPO_DIR_ENV = "KANON_REPO_DIR"
KANONENV_REPO_DIR_DEFAULT = ".repo"

# -- Selfupdate embedded mode --
SELFUPDATE_EMBEDDED_MESSAGE = "selfupdate is not available -- upgrade kanon-cli instead: pipx upgrade kanon-cli"

# -- git ls-remote retry --
GIT_RETRY_COUNT_ENV_VAR = "KANON_GIT_RETRY_COUNT"
GIT_RETRY_DELAY_ENV_VAR = "KANON_GIT_RETRY_DELAY"
GIT_RETRY_COUNT_DEFAULT = 3
GIT_RETRY_DELAY_DEFAULT = 1
# Patterns in ls-remote stderr that indicate authentication errors.
# These errors must not be retried to avoid credential lockouts.
GIT_AUTH_ERROR_PATTERNS = ("Authentication", "Permission denied")

# -- Install concurrency lock --
# File name for the per-project exclusive lock that serializes concurrent installs.
INSTALL_LOCK_FILENAME = ".kanon-install.lock"

# -- Doctor command --
# Subdirectory name under .kanon-data/ where completion-cache files are stored.
KANON_COMPLETION_CACHE_DIR = "completion-cache"

# -- Color / TTY output --
# Environment variable name that suppresses ANSI color output when non-empty,
# following the https://no-color.org convention.
NO_COLOR_ENV = "NO_COLOR"
# Runtime flag mutated by _apply_global_flags (kanon_cli.core.cli_args) when
# --no-color is passed or NO_COLOR env var is non-empty. All formatter helpers
# read this flag before emitting ANSI escape sequences.
_NO_COLOR_ACTIVE: bool = False

# -- Source-name derivation (soft-spot rule 2) --
# Pattern matching the full recommended character set for catalog entry names.
# Characters outside this set in an entry name trigger a shell-quoting warning.
RECOMMENDED_CHAR_RE = re.compile(r"^[a-zA-Z0-9_-]*$")

# -- kanon list --tree threshold guardrail --
# Maximum number of catalog entries allowed before the threshold guardrail
# requires the operator to supply a filter (positional substring, --regex,
# --max-depth 0) or override with --no-filter-required.
# Overridable via the KANON_TREE_NO_FILTER_THRESHOLD environment variable.
_raw_threshold = os.environ.get("KANON_TREE_NO_FILTER_THRESHOLD")
if _raw_threshold is not None:
    KANON_TREE_NO_FILTER_THRESHOLD: int = int(_raw_threshold)
else:
    KANON_TREE_NO_FILTER_THRESHOLD = 20

# -- kanon list --all-versions cap --
# Maximum number of catalog versions walked when --all-versions is given and
# neither --limit N nor --no-limit is explicitly passed.
# Overridable via the KANON_LIST_LIMIT environment variable.
_raw_list_limit = os.environ.get("KANON_LIST_LIMIT")
if _raw_list_limit is not None:
    KANON_LIST_LIMIT: int = int(_raw_list_limit)
else:
    KANON_LIST_LIMIT = 50

# -- kanon add --
# Environment variable name for the destination .kanon file path.
# CLI flag --kanon-file takes precedence when both are set.
KANON_KANON_FILE_ENV = "KANON_KANON_FILE"

# -- kanon lock --
# Environment variable name for the operator-override lockfile path.
# When set, kanon reads/writes the lockfile at this path instead of the
# default derived from --kanon-file. CLI flag --lock-file takes precedence.
KANON_LOCK_FILE = "KANON_LOCK_FILE"

# -- HTTPS enforcement (spec Section 4.7 / Section 3.6 trust model) --
# When set to "1", disables the insecure-remote-URL security check in
# kanon install. All remote URL schemes (HTTP, file://, git://, etc.) are
# accepted without error. Any value other than "1" is treated as unset.
# See docs/configuration.md for the security rationale.
KANON_ALLOW_INSECURE_REMOTES = "KANON_ALLOW_INSECURE_REMOTES"

# Default destination .kanon file path when neither --kanon-file nor
# KANON_KANON_FILE are set.
KANON_KANON_FILE_DEFAULT = "./.kanon"

# Standard-header line values written to a newly-created .kanon file.
# These match the template in src/kanon_cli/catalog/kanon/.kanon verbatim.
KANON_HEADER_GITBASE = "GITBASE=<YOUR_GIT_ORG_BASE_URL>"
KANON_HEADER_CLAUDE_MARKETPLACES_DIR = "CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces"
KANON_HEADER_MARKETPLACE_INSTALL = "KANON_MARKETPLACE_INSTALL=<true|false>"

# -- kanon outdated --
# Environment variable name that controls the output format for 'kanon outdated'.
# The CLI flag --format takes precedence when both are set.
# Supported values: "table" (default). Extended to "table","json" in T4.
KANON_OUTDATED_FORMAT = "KANON_OUTDATED_FORMAT"

# Default output format for 'kanon outdated' when neither --format nor
# KANON_OUTDATED_FORMAT are set.
KANON_OUTDATED_FORMAT_DEFAULT = "table"

# JSON format name for 'kanon outdated --format json'.
KANON_OUTDATED_FORMAT_JSON = "json"

# -- kanon outdated JSON output --
# Indentation level (in spaces) used by json.dumps when --format json is selected.
# Controls pretty-print depth without requiring source edits.
# Overridable via the KANON_OUTDATED_JSON_INDENT environment variable.
_raw_json_indent = os.environ.get("KANON_OUTDATED_JSON_INDENT")
if _raw_json_indent is not None:
    KANON_OUTDATED_JSON_INDENT: int = int(_raw_json_indent)
else:
    KANON_OUTDATED_JSON_INDENT = 2

# -- Branch-pinned SHA truncation (spec Section 4.4) --
# Number of leading hex characters used for the short-SHA display in the
# 'kanon outdated' table for branch-pinned and SHA-pinned sources.
# Matches git's default short-SHA convention.
BRANCH_SHA_TRUNCATION_LENGTH = 12

# Lengths (in hex chars) of the two SHA hash types accepted as REVISION values.
# SHA-1 produces a 40-character hex string; SHA-256 produces a 64-character hex
# string. Both are recognised as "SHA-pinned" by _classify_revision_shape.
SHA1_HEX_LENGTH = 40
SHA256_HEX_LENGTH = 64

# -- kanon why --
# Environment variable name that controls the output format for 'kanon why'.
# The CLI flag --format takes precedence when both are set.
# Supported values: "text" (default). Extended to "text","json" in T4.
KANON_WHY_FORMAT = "KANON_WHY_FORMAT"

# Default output format for 'kanon why' when neither --format nor
# KANON_WHY_FORMAT are set.
KANON_WHY_FORMAT_DEFAULT = "text"

# -- kanon why closest-match suggestion thresholds --
# Maximum Levenshtein edit distance for a candidate to be considered a close
# match during not-found suggestion. Only candidates with distance <= this
# value are eligible. Overridable via the KANON_WHY_SUGGEST_MAX_DISTANCE env var.
_raw_why_suggest_max_distance = os.environ.get("KANON_WHY_SUGGEST_MAX_DISTANCE")
if _raw_why_suggest_max_distance is not None:
    try:
        KANON_WHY_SUGGEST_MAX_DISTANCE: int = int(_raw_why_suggest_max_distance)
    except ValueError:
        raise SystemExit(
            f"ERROR: KANON_WHY_SUGGEST_MAX_DISTANCE must be a non-negative integer; "
            f"got {_raw_why_suggest_max_distance!r}"
        )
    if KANON_WHY_SUGGEST_MAX_DISTANCE < 0:
        raise SystemExit(
            f"ERROR: KANON_WHY_SUGGEST_MAX_DISTANCE must be a non-negative integer; "
            f"got {KANON_WHY_SUGGEST_MAX_DISTANCE}"
        )
else:
    KANON_WHY_SUGGEST_MAX_DISTANCE = 3

# Maximum number of close-match suggestions to include in the not-found error
# message. Suggestions are sorted ascending by (distance, value) and truncated
# to this count. Overridable via the KANON_WHY_SUGGEST_TOP_N env var.
_raw_why_suggest_top_n = os.environ.get("KANON_WHY_SUGGEST_TOP_N")
if _raw_why_suggest_top_n is not None:
    try:
        KANON_WHY_SUGGEST_TOP_N: int = int(_raw_why_suggest_top_n)
    except ValueError:
        raise SystemExit(
            f"ERROR: KANON_WHY_SUGGEST_TOP_N must be a non-negative integer; got {_raw_why_suggest_top_n!r}"
        )
    if KANON_WHY_SUGGEST_TOP_N < 0:
        raise SystemExit(
            f"ERROR: KANON_WHY_SUGGEST_TOP_N must be a non-negative integer; got {KANON_WHY_SUGGEST_TOP_N}"
        )
else:
    KANON_WHY_SUGGEST_TOP_N = 3
