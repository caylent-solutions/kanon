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

# Number of recent lines to display from the completion-errors log during
# `kanon doctor` subcheck 7. Overridable via the
# KANON_COMPLETION_ERRORS_REPORT_LIMIT environment variable.
_raw_completion_errors_limit = os.environ.get("KANON_COMPLETION_ERRORS_REPORT_LIMIT")
if _raw_completion_errors_limit is not None:
    try:
        KANON_COMPLETION_ERRORS_REPORT_LIMIT: int = int(_raw_completion_errors_limit)
    except ValueError:
        raise SystemExit(
            f"ERROR: KANON_COMPLETION_ERRORS_REPORT_LIMIT must be a positive integer; "
            f"got {_raw_completion_errors_limit!r}"
        )
    if KANON_COMPLETION_ERRORS_REPORT_LIMIT <= 0:
        raise SystemExit(
            f"ERROR: KANON_COMPLETION_ERRORS_REPORT_LIMIT must be a positive integer; "
            f"got {KANON_COMPLETION_ERRORS_REPORT_LIMIT}"
        )
else:
    KANON_COMPLETION_ERRORS_REPORT_LIMIT = 5

# Name of the environment variable that specifies the kanon cache directory.
# The cache directory holds the completion-errors log and other cache files
# written by E7 completion callbacks. When unset, there is no cache directory.
KANON_CACHE_DIR_ENV = "KANON_CACHE_DIR"

# Filename of the completion-errors log within the cache directory.
# Doctor subcheck 7 reads the last KANON_COMPLETION_ERRORS_REPORT_LIMIT lines
# from this file when it exists.
KANON_COMPLETION_ERRORS_LOG_FILENAME = "completion-errors.log"

# Candidate paths for statically-installed shell completion scripts.
# Each entry is a (shell, path) pair. Doctor subcheck 9 iterates these pairs
# and checks files that exist on disk against a freshly generated script.
# Home-directory paths are expanded via os.path.expanduser() at import time;
# system-wide paths are used verbatim. Extend this tuple to support additional shells.
KANON_STATIC_COMPLETION_SEARCH_PATHS: tuple[tuple[str, str], ...] = (
    ("bash", os.path.expanduser("~/.local/share/bash-completion/completions/kanon")),
    ("bash", "/etc/bash_completion.d/kanon"),
    ("zsh", os.path.expanduser("~/.zsh/completions/_kanon")),
    ("zsh", "/usr/local/share/zsh/site-functions/_kanon"),
    ("zsh", "/usr/share/zsh/vendor-completions/_kanon"),
)

# Warning text template for a stale static completion script (subcheck 9).
# Call with .format(shell_name=<shell>, path=<path>) to produce the final message.
# The placeholder is named shell_name rather than shell to avoid the bandit B604
# false positive that flags any .format() with a keyword arg named "shell" as
# a potential shell-injection issue -- which it is not here.
KANON_STALE_COMPLETION_SCRIPT_WARNING = (
    "Stale {shell_name} completion script: {path} does not match the output of "
    "'kanon completion {shell_name}'. Re-run 'kanon completion {shell_name} > {path}' "
    "to update it."
)

# -- Doctor cache management (subchecks 8 + 10) --
# Permission bits for the completion-cache directory, enforcing owner-only
# access as required by spec Section 3.6 (trust model / credential isolation).
KANON_CACHE_DIR_MODE = 0o700

# Age threshold in days for the cache prune operation (subcheck 10).
# Files whose atime is older than this many days are removed by
# 'kanon doctor --prune-cache'. Overridable via KANON_CACHE_PRUNE_AGE_DAYS.
_raw_cache_prune_age_days = os.environ.get("KANON_CACHE_PRUNE_AGE_DAYS")
if _raw_cache_prune_age_days is not None:
    try:
        KANON_CACHE_PRUNE_AGE_DAYS: int = int(_raw_cache_prune_age_days)
    except ValueError:
        raise SystemExit(
            f"ERROR: KANON_CACHE_PRUNE_AGE_DAYS must be a positive integer; got {_raw_cache_prune_age_days!r}"
        )
    if KANON_CACHE_PRUNE_AGE_DAYS <= 0:
        raise SystemExit(
            f"ERROR: KANON_CACHE_PRUNE_AGE_DAYS must be a positive integer; got {KANON_CACHE_PRUNE_AGE_DAYS}"
        )
else:
    KANON_CACHE_PRUNE_AGE_DAYS = 30

# Maximum directory depth for the stale install-lock scan (subcheck 10).
# The scan walks .kanon-data/.kanon-install.lock files under the current
# working directory but stops at this depth to bound filesystem traversal.
# Overridable via KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH.
_raw_stale_lock_scan_max_depth = os.environ.get("KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH")
if _raw_stale_lock_scan_max_depth is not None:
    try:
        KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH: int = int(_raw_stale_lock_scan_max_depth)
    except ValueError:
        raise SystemExit(
            f"ERROR: KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH must be a positive integer; "
            f"got {_raw_stale_lock_scan_max_depth!r}"
        )
    if KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH <= 0:
        raise SystemExit(
            f"ERROR: KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH must be a positive integer; "
            f"got {KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH}"
        )
else:
    KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH = 4

# Age threshold in hours beyond which a .kanon-install.lock file is considered
# stale (subcheck 10 advisory). Doctor does NOT delete stale locks; it only
# reports them. Overridable via KANON_DOCTOR_STALE_LOCK_AGE_HOURS.
_raw_stale_lock_age_hours = os.environ.get("KANON_DOCTOR_STALE_LOCK_AGE_HOURS")
if _raw_stale_lock_age_hours is not None:
    try:
        KANON_DOCTOR_STALE_LOCK_AGE_HOURS: int = int(_raw_stale_lock_age_hours)
    except ValueError:
        raise SystemExit(
            f"ERROR: KANON_DOCTOR_STALE_LOCK_AGE_HOURS must be a positive integer; got {_raw_stale_lock_age_hours!r}"
        )
    if KANON_DOCTOR_STALE_LOCK_AGE_HOURS <= 0:
        raise SystemExit(
            f"ERROR: KANON_DOCTOR_STALE_LOCK_AGE_HOURS must be a positive integer; "
            f"got {KANON_DOCTOR_STALE_LOCK_AGE_HOURS}"
        )
else:
    KANON_DOCTOR_STALE_LOCK_AGE_HOURS = 1

# Maximum number of characters from the first line of stderr to include in a
# remote-reachability warning finding (subcheck 11). Keeps error output bounded
# when a git server returns a long diagnostics message.
# Overridable via the KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS environment variable.
_raw_remote_stderr_preview = os.environ.get("KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS")
if _raw_remote_stderr_preview is not None:
    try:
        KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS: int = int(_raw_remote_stderr_preview)
    except ValueError:
        raise SystemExit(
            f"ERROR: KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS must be a positive integer; "
            f"got {_raw_remote_stderr_preview!r}"
        )
    if KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS <= 0:
        raise SystemExit(
            f"ERROR: KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS must be a positive integer; "
            f"got {KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS}"
        )
else:
    KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS = 160

# Environment variable name for the git ls-remote / resolve timeout (seconds).
# Used by kanon doctor subchecks 4 (branch drift) and 5 (dangling SHA).
_KANON_RESOLVE_TIMEOUT_ENV = "KANON_RESOLVE_TIMEOUT"

# Default timeout (in seconds) for git ls-remote calls made by kanon doctor.
_KANON_RESOLVE_TIMEOUT_DEFAULT = 30

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

# JSON format name for 'kanon why --format json'.
KANON_WHY_FORMAT_JSON = "json"

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

# -- kanon why JSON output --
# Indentation level (in spaces) used by json.dumps when --format json is selected.
# Controls pretty-print depth without requiring source edits.
# Overridable via the KANON_WHY_JSON_INDENT environment variable.
_raw_why_json_indent = os.environ.get("KANON_WHY_JSON_INDENT")
if _raw_why_json_indent is not None:
    try:
        KANON_WHY_JSON_INDENT: int = int(_raw_why_json_indent)
    except ValueError:
        raise SystemExit(f"ERROR: KANON_WHY_JSON_INDENT must be a non-negative integer; got {_raw_why_json_indent!r}")
    if KANON_WHY_JSON_INDENT < 0:
        raise SystemExit(f"ERROR: KANON_WHY_JSON_INDENT must be a non-negative integer; got {KANON_WHY_JSON_INDENT}")
else:
    KANON_WHY_JSON_INDENT = 2

# -- kanon catalog audit --
# The five valid subset names for the --check flag of kanon catalog audit.
# These are the only values accepted individually or in comma-separated combination.
# The special value "all" expands to this full set at parse time.
KANON_CATALOG_AUDIT_VALID_CHECKS: frozenset[str] = frozenset(
    {
        "metadata",
        "source-name-derivation",
        "entry-name-uniqueness",
        "remote-url",
        "tag-format",
    }
)

# Cache TTL (in seconds) for cloned catalog-audit target repos.
# A cached clone is reused if its mtime is within this many seconds of now.
# Overridable via the KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS environment variable.
_raw_catalog_audit_cache_ttl = os.environ.get("KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS")
if _raw_catalog_audit_cache_ttl is not None:
    try:
        KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS: int = int(_raw_catalog_audit_cache_ttl)
    except ValueError:
        raise SystemExit(
            f"ERROR: KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS must be a positive integer; "
            f"got {_raw_catalog_audit_cache_ttl!r}"
        )
    if KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS <= 0:
        raise SystemExit(
            f"ERROR: KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS must be a positive integer; "
            f"got {KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS}"
        )
else:
    KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS = 3600

# Subdirectory name under KANON_CACHE_DIR for catalog-audit cloned repos.
# Full path: ${KANON_CACHE_DIR}/catalog-audit/<sha256-of-canonicalized-url-at-ref>/
KANON_CATALOG_AUDIT_CACHE_SUBDIR = "catalog-audit"

# Environment variable name that controls the output format for 'kanon catalog audit'.
# The CLI flag --format takes precedence when both are set.
# Supported values: "text" (default), "json".
KANON_CATALOG_AUDIT_FORMAT_ENV = "KANON_CATALOG_AUDIT_FORMAT"

# Default output format for 'kanon catalog audit' when neither --format nor
# KANON_CATALOG_AUDIT_FORMAT are set.
KANON_CATALOG_AUDIT_FORMAT_DEFAULT = "text"

# JSON format name for 'kanon catalog audit --format json'.
KANON_CATALOG_AUDIT_FORMAT_JSON = "json"

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
