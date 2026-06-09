"""Centralized constants for the kanon-cli package.

All module-level constants live here to avoid hard-coded values
scattered across source files.
"""

import os
import re

# -- Exit codes --
# Reserved exit code for deprecated-invocation paths (e.g. kanon bootstrap).
# 0 = success, 1 = runtime/usage error, 2 = argparse usage error, 3 = deprecated invocation.
EXIT_CODE_DEPRECATED = 3

# -- Marketplace validation --
MARKETPLACE_DIR_PREFIX = "${CLAUDE_MARKETPLACES_DIR}/"
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

# -- Workspace directory --
# When set, install and clean resolve .packages/ and .kanon-data/ relative to
# this directory instead of beside .kanon.  The value is resolved to an
# absolute path; the directory is created if absent.  An unwritable value
# causes a non-zero exit with an actionable message -- no silent cwd fallback.
WORKSPACE_DIR_ENV_VAR = "KANON_WORKSPACE_DIR"

# -- Catalog --
CATALOG_ENV_VAR = "KANON_CATALOG_SOURCE"

# -- .kanon [catalog] block --
# INI-style section header written by `kanon add` to a freshly-created .kanon
# file to record the catalog source URL so `kanon install` can read it back
# without requiring the operator to pass --catalog-source again.
KANON_CATALOG_BLOCK_HEADER = "[catalog]"
# Key name for the catalog source entry within the [catalog] block.
KANON_CATALOG_BLOCK_KEY = "KANON_CATALOG_SOURCE"

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

# Default cache directory path (XDG-style; resolved at runtime via expanduser).
# Section 11.4 / Section 11.6 default.
KANON_CACHE_DIR_DEFAULT = "~/.cache/kanon"

# TTL in seconds for shell-completion cache entries.
# Completers skip a remote fetch when the cached fetched_at is within this age.
# Section 11.4 lifecycle header.
KANON_COMPLETION_CACHE_TTL = 300

# Timeout in seconds applied to each kanon __complete_* subprocess call.
# Preamble helpers pass this to timeout(1) (or rely on kanon's internal limit).
# Section 11.6 configuration recap.
KANON_COMPLETION_TIMEOUT = 2

# When 1, the completion background-refresh subprocess is spawned after a
# stale-but-present cache read to refresh asynchronously. Section 11.4.
KANON_COMPLETION_REFRESH_BG = 1

# Environment variable name that controls the background-refresh behavior.
# Set to "0" to disable background refresh (the stale cache is still returned
# but no forked child updates it). Any non-integer or zero value disables the
# feature. Section 11.6.
KANON_COMPLETION_REFRESH_BG_ENV = "KANON_COMPLETION_REFRESH_BG"

# When 1, dynamic completion lookups are enabled. Set to 0 to disable all
# kanon __complete_* calls globally. Section 11.6.
KANON_COMPLETION_ENABLED = 1

# Coalescing window in seconds for accessed_at updates.
# A read that occurs within this many seconds of the last update does not
# rewrite accessed_at, to bound I/O under rapid Tab-pressing. Section 11.4.
KANON_ACCESSED_AT_COALESCE_SEC = 60

# Name of the environment variable that overrides the completion-errors log
# path. When unset, the log is written to ${KANON_CACHE_DIR}/completion-errors.log.
KANON_COMPLETION_LOG_ENV = "KANON_COMPLETION_LOG"

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

# -- Shell-completion output sanitization (spec Section 11.3) --
# Maximum byte length for a safe catalog entry name emitted by __complete_* subcommands.
# Names longer than this value are excluded from completion output.
COMPLETION_MAX_ENTRY_LEN = 128

# Characters that are not permitted in a catalog entry name emitted to stdout.
# Shell-special chars, whitespace, and control characters are forbidden
# per spec Section 11.3 "Output sanitization".
COMPLETION_UNSAFE_CHARS: frozenset[str] = frozenset(" \t\n\r;|&$`")

# Shell metacharacters forbidden in completion candidates (spec Section 11.3,
# Section 3.6 trust model).  Any entry containing one of these characters is
# dropped by sanitize_entries() and logged to completion-errors.log.
# Closed set: pipe, ampersand, semicolon, less-than, greater-than, open-paren,
# close-paren, open-brace, close-brace, dollar, backtick, backslash,
# double-quote, single-quote.
SHELL_METACHARS: frozenset[str] = frozenset("|&;<>(){}$`\\\"'")

# -- Source-name derivation (soft-spot rule 2) --
# Pattern matching the full recommended character set for catalog entry names.
# Characters outside this set in an entry name trigger a shell-quoting warning.
RECOMMENDED_CHAR_RE = re.compile(r"^[a-zA-Z0-9_-]*$")

# Compiled regex for the allowed catalog entry-name character set.
# Alias of RECOMMENDED_CHAR_RE -- both enforce the same character set
# [a-zA-Z0-9_-]. Used by _check_source_name_derivation in catalog.py to flag
# entry names that contain characters outside this set. These characters are
# legal but unusual; the warning helps authors spot accidental whitespace, dots,
# or non-ASCII before they propagate into shell variable names.
# Defined here (not inline in catalog.py) so the rule is testable data.
KANON_CATALOG_ENTRY_NAME_ALLOWED_CHARS_RE = RECOMMENDED_CHAR_RE

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

# -- kanon outdated revision normalization (DEFECT-007 fix) --
# Individual git ref prefix constants for all recognized prefix forms.
# These are the canonical string values; all code in outdated.py and elsewhere
# must reference these constants rather than inline string literals.
REVISION_REF_PREFIX_TAGS = "refs/tags/"
REVISION_REF_PREFIX_HEADS = "refs/heads/"
REVISION_REF_PREFIX_REMOTES = "refs/remotes/origin/"

# Ordered tuple of git ref prefixes that 'kanon outdated' recognizes and strips
# before classifying a REVISION as a PEP 440 version or a branch name.
# Order matters: refs/remotes/origin/ is checked before refs/heads/ and
# refs/tags/ so that longer prefixes are consumed first.
REVISION_REF_PREFIXES: tuple[str, ...] = (
    REVISION_REF_PREFIX_REMOTES,
    REVISION_REF_PREFIX_HEADS,
    REVISION_REF_PREFIX_TAGS,
)

# Classification token returned by _normalize_revision_for_constraint when the
# bare ref (after prefix stripping) is a valid PEP 440 version.
REVISION_CLASSIFICATION_VERSION = "version"

# Classification token returned by _normalize_revision_for_constraint when the
# bare ref is from a branch-shaped prefix (refs/heads/ or refs/remotes/origin/).
REVISION_CLASSIFICATION_BRANCH = "branch"

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

# -- kanon catalog audit metadata check field lists --
# REQUIRED fields: missing or whitespace-only triggers an ERROR finding.
# Defined here so they are testable data, not inline literals in catalog.py.
KANON_CATALOG_METADATA_REQUIRED_FIELDS: tuple[str, ...] = (
    "name",
    "display-name",
    "description",
    "version",
)

# RECOMMENDED fields: missing any triggers a WARN finding per file.
# Defined here so they are testable data, not inline literals in catalog.py.
KANON_CATALOG_METADATA_RECOMMENDED_FIELDS: tuple[str, ...] = (
    "type",
    "owner-name",
    "owner-email",
    "keywords",
)

# -- kanon catalog audit tag-format check (soft-spot rule 5) --
# Maximum number of non-PEP-440 tag WARN findings emitted per check run.
# When the actual count of non-PEP-440 tags exceeds this limit, only the
# first KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT findings are emitted per-tag;
# a single additional summary WARN names the remaining count.
# Overridable via the KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT environment variable.
_raw_tag_report_limit = os.environ.get("KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT")
if _raw_tag_report_limit is not None:
    try:
        KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT: int = int(_raw_tag_report_limit)
    except ValueError:
        raise SystemExit(
            f"ERROR: KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT must be a positive integer; got {_raw_tag_report_limit!r}"
        )
    if KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT <= 0:
        raise SystemExit(
            f"ERROR: KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT must be a positive integer; "
            f"got {KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT}"
        )
else:
    KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT = 50

# Summary-text template for the tag-format check when the number of non-PEP-440
# tags exceeds KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT.
# Call with .format(remaining=<count>) to produce the final summary message.
KANON_CATALOG_AUDIT_TAG_FORMAT_SUMMARY_TEMPLATE = (
    "{remaining} additional non-PEP-440 tag(s) not listed above. "
    "Run 'kanon catalog audit --check tag-format' for the full list."
)

# Strict-mode summary template for kanon catalog audit --strict.
# Emitted to stderr when --strict is active and at least one WARN finding exists.
# Call with .format(count=<warning-count>) to produce the final summary line.
# Spec source: spec Section 4.8 (--strict flag).
KANON_CATALOG_AUDIT_STRICT_SUMMARY_TEMPLATE = "strict mode: {count} warning(s) treated as errors"

# Warning message template for the legacy catalog/<name>/ directory detection.
# Emitted unconditionally by audit_command when a catalog/ subdirectory is found
# containing at least one immediate child directory in the audit target.
# Call with .format(version=<kanon-version>) to produce the final message.
# Spec source: spec Section 4.8.
KANON_CATALOG_AUDIT_LEGACY_DIR_WARNING_TEMPLATE = (
    "Legacy catalog/ directory detected; this directory is unused by "
    "kanon >= {version} and should be deleted; "
    "see docs/migration-bootstrap-to-add.md"
)

# -- Doctor subcheck Finding severity tokens (DEFECT-012 fix) --
# Canonical severity identifiers used by the Finding dataclass validator.
# All three values are checked by Finding.__post_init__; any other value raises ValueError.
FINDING_SEVERITY_OK = "ok"
FINDING_SEVERITY_FAIL = "fail"
FINDING_SEVERITY_INFO = "info"

# Prefix tokens printed by the doctor dispatcher for each Finding severity level.
# Format: "[ok] <name>", "[fail] <name>: <reason>", "[info] <name>" (or with reason).
FINDING_PREFIX_OK = "[ok]"
FINDING_PREFIX_FAIL = "[fail]"
FINDING_PREFIX_INFO = "[info]"

# -- kanon why scope tags (DEFECT-009 fix) --
# Scope tag applied to lockfile index entries that originate from top-level
# [[sources]] entries (i.e. not transitively included via [[sources.includes]]).
WHY_SCOPE_TOP_LEVEL = "top_level"

# Scope tag applied to lockfile index entries that originate from transitive
# [[sources.includes]] entries (i.e. pulled in by a top-level source's manifest).
WHY_SCOPE_TRANSITIVE = "transitive"

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
