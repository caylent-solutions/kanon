"""Centralized constants for the kanon-cli package.

All module-level constants live here to avoid hard-coded values
scattered across source files.
"""

import os
import pathlib
import re


def _env_int(var: str, default: int) -> int:
    """Read *var* from the environment and return it as an integer.

    Returns *default* when the variable is unset (absent from the environment).
    Raises ``SystemExit`` with a clear, actionable message naming the offending
    variable when the value is present but cannot be parsed as an integer
    (including an empty string).
    """
    raw = os.environ.get(var)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise SystemExit(f"ERROR: {var} must be an integer; got {raw!r}")


EXIT_CODE_DEPRECATED = 3


MARKETPLACE_DIR_PREFIX = "${CLAUDE_MARKETPLACES_DIR}/"


REVISION_EXISTENCE_REQUIRED_ENV_VAR = "KANON_VALIDATE_REQUIRE_EXISTENCE"


REFS_TAGS_RE = re.compile(r"^refs/tags/(?:.+/)?\d+\.\d+\.\d+$")
CONSTRAINT_RE = re.compile(r"^(~=|>=|<=|>|<)\d+\.\d+\.\d+$")


PEP440_OPERATORS = ("~=", ">=", "<=", "!=", "==", ">", "<")


TAG_ERROR_DISPLAY_CAP = 10


SOURCE_PREFIX = "KANON_SOURCE_"
SOURCE_URL_SUFFIX = "_URL"
SOURCE_REF_SUFFIX = "_REF"
SOURCE_PATH_SUFFIX = "_PATH"
SOURCE_NAME_SUFFIX = "_NAME"
SOURCE_NON_URL_SUFFIXES = (
    SOURCE_REF_SUFFIX,
    SOURCE_PATH_SUFFIX,
    SOURCE_NAME_SUFFIX,
)
SOURCE_SUFFIXES = (SOURCE_URL_SUFFIX,) + SOURCE_NON_URL_SUFFIXES
SUFFIX_TO_KEY = {
    SOURCE_URL_SUFFIX: "url",
    SOURCE_REF_SUFFIX: "ref",
    SOURCE_PATH_SUFFIX: "path",
    SOURCE_NAME_SUFFIX: "name",
}


SOURCE_MARKETPLACE_SUFFIX = "_MARKETPLACE"
SOURCE_MARKETPLACE_KEY = "marketplace"


SOURCE_ENV_KEY = "env"
SOURCE_GITBASE_VAR = "GITBASE"
SOURCE_RESERVED_SUFFIXES = SOURCE_SUFFIXES + (SOURCE_MARKETPLACE_SUFFIX,)


MARKETPLACE_FLAG_TRUE = "true"


CATALOG_TYPE_CLAUDE_MARKETPLACE = "claude-marketplace"
SHELL_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")

MANIFEST_VAR_PATTERN = re.compile(r"\$(?:\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)\}|(?P<bare>[A-Za-z_][A-Za-z0-9_]*))")
"""Variable references ``repo envsubst`` will actually expand in a manifest.

``repo envsubst`` substitutes through :func:`os.path.expandvars`, which expands
``$VAR`` and ``${VAR}`` alike. Detection has to match that grammar exactly: a
spelling the substituter expands but the detector misses is invisible to both
``kanon add`` and the install-time guard, so install exits 0 with the variable
unset and delivers nothing. This is deliberately *not*
:data:`SHELL_VAR_PATTERN`, which governs substitution inside ``.kanon`` values
and has its own, braces-only contract.
"""

UNFILLED_VAR_SENTINEL = "<SET_ME>"
"""Placeholder ``kanon add`` writes for a manifest variable the operator must set.

Deliberately shaped to match the unresolved-placeholder scanner, so an unfilled
value fails the install with a diagnostic naming the key. An empty value would
not: it substitutes as the empty string, so ``dest="${VAR}/rules"`` becomes
``/rules`` at the filesystem root and the guard sees a fully resolved manifest.
"""

MANIFEST_BRACED_VAR_BODY_PATTERN = re.compile(r"\$\{([^}]*)\}")
"""Any ``${...}`` body in a manifest, valid identifier or not.

Used to reject a malformed reference rather than let it through: a body such as
``VAR:-default`` or ``A${B`` is not something ``expandvars`` can ever resolve, so
writing it into ``.kanon`` as a key produces a source that can never install. An
*empty* body is not malformed -- ``expandvars`` leaves a literal ``${}`` alone,
and it can appear legitimately in text -- so callers skip it.
"""


MANIFEST_PROJECT_FUNCTIONAL_CHILD_TAGS = ("linkfile", "copyfile")


KANON_HOME_ENV_VAR = "KANON_HOME"


KANON_HOME_DIR_NAME = ".kanon-home"


KANON_HOME_STORE_SUBDIR = "store"


KANON_HOME_STORE_ENTRIES_SUBDIR = "entries"


KANON_HOME_STORE_LOCKS_SUBDIR = ".locks"


KANON_HOME_STORE_TMP_SUBDIR = ".tmp"


KANON_HOME_STORE_GITIGNORE_ENTRY = "*"


KANON_HOME_CACHE_SUBDIR = "cache"


def resolve_kanon_home(override: "pathlib.Path | None" = None) -> pathlib.Path:
    """Resolve the shared kanon home root directory.

    Resolution precedence (highest wins), per spec Section 7.1:
    0. The ``--home`` / ``--store-dir`` CLI flag, passed here as *override*,
       when it is not ``None``.
    1. The ``KANON_HOME`` environment variable, when set to a non-empty value.
    2. The default ``Path.home() / KANON_HOME_DIR_NAME`` (i.e. ``~/.kanon-home``).

    The default is derived from the real user home directory at call time; no
    absolute path is hard-coded. The returned path is NOT created here -- the
    caller that needs a writable directory (the store base dir, the cache dir)
    is responsible for creation and for failing fast on an unwritable target.

    The ``--home`` / ``--store-dir`` CLI flag override (precedence step 0) is
    threaded by the command layer: ``cli_args._apply_global_flags`` resolves the
    parsed flag and injects it into ``KANON_HOME`` in the process environment
    before any reader runs, so callers that do not have direct access to the
    parsed namespace still observe the flag value through the env var. Passing
    *override* directly to this helper is the equivalent in-process path and is
    used by the resolution unit tests.

    Args:
        override: An explicit kanon home path that wins over both the env var
            and the default when provided (the ``--home`` / ``--store-dir``
            flag value). ``None`` (the default) defers to the env var and the
            built-in default.

    Returns:
        A ``pathlib.Path`` to the resolved kanon home root.
    """
    if override is not None:
        return pathlib.Path(override)
    raw = os.environ.get(KANON_HOME_ENV_VAR)
    if raw:
        return pathlib.Path(raw)
    return pathlib.Path.home() / KANON_HOME_DIR_NAME


CATALOG_SOURCES_ENV_VAR = "KANON_CATALOG_SOURCES"


CATALOG_DEFAULT_BRANCH_ENV_VAR = "KANON_CATALOG_DEFAULT_BRANCH"


CATALOG_DEFAULT_BRANCH_DEFAULT = "main"


CATALOG_DEFAULT_BRANCH_AUTO = "auto"


SYMREF_HEADS_PREFIX = "refs/heads/"


SYMREF_LINE_PREFIX = "ref: "


CATALOG_DEFAULT_BRANCH_SYMREF_ABSENT_ERROR_TEMPLATE = (
    "ERROR: cannot resolve the default branch for {url}: the remote did not\n"
    "advertise a HEAD symref (ls-remote --symref returned no 'ref: refs/heads/...'\n"
    "line). Set KANON_CATALOG_DEFAULT_BRANCH or --catalog-default-branch to an\n"
    "explicit branch, or pin @<ref> on the source."
)


CATALOG_DEFAULT_BRANCH_WARN_TEMPLATE = (
    "WARNING: no ref pinned for {url}; using default branch '{branch}'. "
    "Pin @<ref> on the source to silence this warning."
)


MARKETPLACE_DIR_GLOBAL_KEY = "CLAUDE_MARKETPLACES_DIR"


GLOBALLY_SUPPLIED_MANIFEST_VARS = frozenset({MARKETPLACE_DIR_GLOBAL_KEY})


ANSI_YELLOW = "\033[33m"
ANSI_RESET = "\033[0m"


MISSING_CATALOG_ERROR_TEMPLATE = (
    "ERROR: {command} requires a catalog source.\n"
    "Provide one of:\n"
    "  --catalog-source <git-url>@<ref>       # e.g. --catalog-source https://example.com/org/manifest-repo.git@main\n"
    "  KANON_CATALOG_SOURCES=<git-url>@<ref>  # set as env var (one entry per line), then re-run\n"
    "\n"
    "The CLI flag takes precedence when both are set.\n"
    "A catalog source identifies a manifest repo (a git repository whose\n"
    "repo-specs/ directory exposes installable kanon dependencies).\n"
    "See docs/catalogs-explained.md for what a manifest repo is and how to find one.\n"
    "See docs/configuration.md for the full configuration reference."
)


LIST_EMPTY_CATALOG_NOTE = "manifest repo contains 0 entries"


SEARCH_NO_MATCHES_NOTE = "no matches"


SEARCH_UNREACHABLE_SOURCE_WARN_TEMPLATE = "WARNING: skipping unreachable catalog source {source}: {reason}"


KANONENV_FILENAME = ".kanon"


REPO_RESTART_RETRIES_DEFAULT = 3


KANON_REPO_DIR_ENV = "KANON_REPO_DIR"
KANONENV_REPO_DIR_DEFAULT = ".repo"


SELFUPDATE_EMBEDDED_MESSAGE = "selfupdate is not available -- upgrade kanon-cli instead: pipx upgrade kanon-cli"


KANON_PYPI_PROJECT_NAME = "kanon-cli"
KANON_PYPI_JSON_URL = "https://pypi.org/pypi/kanon-cli/json"


KANON_UPDATE_UPGRADE_COMMAND = "pipx upgrade kanon-cli"


KANON_SKIP_UPDATE_CHECK_ENV = "KANON_SKIP_UPDATE_CHECK"


KANON_SKIP_UPDATE_CHECK_TRUE = "1"


KANON_UPDATE_CHECK_TTL_ENV = "KANON_UPDATE_CHECK_TTL"
KANON_UPDATE_CHECK_TTL: int = _env_int(KANON_UPDATE_CHECK_TTL_ENV, 10800)
if KANON_UPDATE_CHECK_TTL <= 0:
    raise SystemExit(f"ERROR: {KANON_UPDATE_CHECK_TTL_ENV} must be a positive integer; got {KANON_UPDATE_CHECK_TTL}")


KANON_UPDATE_CONNECT_TIMEOUT_ENV = "KANON_UPDATE_CONNECT_TIMEOUT"
KANON_UPDATE_CONNECT_TIMEOUT: int = _env_int(KANON_UPDATE_CONNECT_TIMEOUT_ENV, 2)
if KANON_UPDATE_CONNECT_TIMEOUT <= 0:
    raise SystemExit(
        f"ERROR: {KANON_UPDATE_CONNECT_TIMEOUT_ENV} must be a positive integer; got {KANON_UPDATE_CONNECT_TIMEOUT}"
    )


KANON_UPDATE_READ_TIMEOUT_ENV = "KANON_UPDATE_READ_TIMEOUT"
KANON_UPDATE_READ_TIMEOUT: int = _env_int(KANON_UPDATE_READ_TIMEOUT_ENV, 3)
if KANON_UPDATE_READ_TIMEOUT <= 0:
    raise SystemExit(
        f"ERROR: {KANON_UPDATE_READ_TIMEOUT_ENV} must be a positive integer; got {KANON_UPDATE_READ_TIMEOUT}"
    )


KANON_UPDATE_BODY_SIZE_CAP_ENV = "KANON_UPDATE_BODY_SIZE_CAP"
KANON_UPDATE_BODY_SIZE_CAP: int = _env_int(KANON_UPDATE_BODY_SIZE_CAP_ENV, 200 * 1024)
if KANON_UPDATE_BODY_SIZE_CAP <= 0:
    raise SystemExit(
        f"ERROR: {KANON_UPDATE_BODY_SIZE_CAP_ENV} must be a positive integer; got {KANON_UPDATE_BODY_SIZE_CAP}"
    )


KANON_UPDATE_CHECK_CACHE_SUBDIR = "update-check"


KANON_UPDATE_CHECK_VERSION_FILENAME = "latest.txt"


ANSI_RED = "\033[31m"
ANSI_GREEN = "\033[32m"


KANON_UPDATE_ALERT_TEMPLATE = (
    "A new release of kanon-cli is available: {current} -> {latest}.\nRun '{command}' to upgrade."
)


KANON_UPDATE_NO_INTERNET_NOTICE = "kanon: no internet access -- could not check for updates."


GIT_RETRY_COUNT_ENV_VAR = "KANON_GIT_RETRY_COUNT"
GIT_RETRY_DELAY_ENV_VAR = "KANON_GIT_RETRY_DELAY"
GIT_RETRY_COUNT_DEFAULT = 3
GIT_RETRY_DELAY_DEFAULT = 1


GIT_AUTH_ERROR_PATTERNS = ("Authentication", "Permission denied")


KANON_GIT_LS_REMOTE_TIMEOUT: int = _env_int("KANON_GIT_LS_REMOTE_TIMEOUT", 30)


INSTALL_LOCK_FILENAME = ".kanon-install.lock"


KANON_WORKSPACE_LOCK_TIMEOUT_SECONDS: int = _env_int("KANON_WORKSPACE_LOCK_TIMEOUT_SECONDS", 30)
if KANON_WORKSPACE_LOCK_TIMEOUT_SECONDS <= 0:
    raise SystemExit(
        f"ERROR: KANON_WORKSPACE_LOCK_TIMEOUT_SECONDS must be a positive integer; "
        f"got {KANON_WORKSPACE_LOCK_TIMEOUT_SECONDS}"
    )


KANON_COMPLETION_CACHE_DIR = "completion-cache"


KANON_COMPLETION_ERRORS_REPORT_LIMIT: int = _env_int("KANON_COMPLETION_ERRORS_REPORT_LIMIT", 5)
if KANON_COMPLETION_ERRORS_REPORT_LIMIT <= 0:
    raise SystemExit(
        f"ERROR: KANON_COMPLETION_ERRORS_REPORT_LIMIT must be a positive integer; "
        f"got {KANON_COMPLETION_ERRORS_REPORT_LIMIT}"
    )


KANON_COMPLETION_CACHE_TTL = 300


KANON_COMPLETION_TIMEOUT = 2


KANON_COMPLETION_REFRESH_BG = 1


KANON_COMPLETION_REFRESH_BG_ENV = "KANON_COMPLETION_REFRESH_BG"


KANON_COMPLETION_ENABLED = 1


KANON_ACCESSED_AT_COALESCE_SEC = 60


KANON_COMPLETION_LOG_ENV = "KANON_COMPLETION_LOG"


KANON_COMPLETION_ERRORS_LOG_FILENAME = "completion-errors.log"


KANON_STATIC_COMPLETION_SEARCH_PATHS: tuple[tuple[str, str], ...] = (
    ("bash", os.path.expanduser("~/.local/share/bash-completion/completions/kanon")),
    ("bash", "/etc/bash_completion.d/kanon"),
    ("zsh", os.path.expanduser("~/.zsh/completions/_kanon")),
    ("zsh", "/usr/local/share/zsh/site-functions/_kanon"),
    ("zsh", "/usr/share/zsh/vendor-completions/_kanon"),
)


KANON_STALE_COMPLETION_SCRIPT_WARNING = (
    "Stale {shell_name} completion script: {path} does not match the output of "
    "'kanon completion {shell_name}'. Re-run 'kanon completion {shell_name} > {path}' "
    "to update it."
)


KANON_HOME_CACHE_DIR_MODE = 0o700


KANON_CACHE_PRUNE_AGE_DAYS: int = _env_int("KANON_CACHE_PRUNE_AGE_DAYS", 30)
if KANON_CACHE_PRUNE_AGE_DAYS <= 0:
    raise SystemExit(f"ERROR: KANON_CACHE_PRUNE_AGE_DAYS must be a positive integer; got {KANON_CACHE_PRUNE_AGE_DAYS}")


KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH: int = _env_int("KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH", 4)
if KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH <= 0:
    raise SystemExit(
        f"ERROR: KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH must be a positive integer; "
        f"got {KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH}"
    )


KANON_DOCTOR_STALE_LOCK_AGE_HOURS: int = _env_int("KANON_DOCTOR_STALE_LOCK_AGE_HOURS", 1)
if KANON_DOCTOR_STALE_LOCK_AGE_HOURS <= 0:
    raise SystemExit(
        f"ERROR: KANON_DOCTOR_STALE_LOCK_AGE_HOURS must be a positive integer; got {KANON_DOCTOR_STALE_LOCK_AGE_HOURS}"
    )


KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS: int = _env_int("KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS", 160)
if KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS <= 0:
    raise SystemExit(
        f"ERROR: KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS must be a positive integer; "
        f"got {KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS}"
    )


_KANON_RESOLVE_TIMEOUT_ENV = "KANON_RESOLVE_TIMEOUT"


_KANON_RESOLVE_TIMEOUT_DEFAULT = 30


NO_COLOR_ENV = "NO_COLOR"


_NO_COLOR_ACTIVE: bool = False


COMPLETION_MAX_ENTRY_LEN = 128


COMPLETION_UNSAFE_CHARS: frozenset[str] = frozenset(" \t\n\r;|&$`")


SHELL_METACHARS: frozenset[str] = frozenset("|&;<>(){}$`\\\"'")


RECOMMENDED_CHAR_RE = re.compile(r"^[a-zA-Z0-9_-]*$")


KANON_CATALOG_ENTRY_NAME_ALLOWED_CHARS_RE = RECOMMENDED_CHAR_RE


KANON_TREE_NO_FILTER_THRESHOLD: int = _env_int("KANON_TREE_NO_FILTER_THRESHOLD", 20)


KANON_LIST_LIMIT: int = _env_int("KANON_LIST_LIMIT", 50)


KANON_SEARCH_MAX_WORKERS: int = _env_int("KANON_SEARCH_MAX_WORKERS", 8)
if KANON_SEARCH_MAX_WORKERS <= 0:
    raise ValueError(f"ERROR: KANON_SEARCH_MAX_WORKERS must be a positive integer; got {KANON_SEARCH_MAX_WORKERS}")


KANON_KANON_FILE_ENV = "KANON_KANON_FILE"


KANON_LOCK_FILE = "KANON_LOCK_FILE"


KANON_ALLOW_INSECURE_REMOTES = "KANON_ALLOW_INSECURE_REMOTES"


KANON_KANON_FILE_DEFAULT = "./.kanon"


LOCKFILE_FILENAME = ".kanon.lock"


KANON_HEADER_GITBASE = "GITBASE=<YOUR_GIT_ORG_BASE_URL>"
KANON_HEADER_CLAUDE_MARKETPLACES_DIR = "CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces"


REVISION_REF_PREFIX_TAGS = "refs/tags/"
REVISION_REF_PREFIX_HEADS = "refs/heads/"
REVISION_REF_PREFIX_REMOTES = "refs/remotes/origin/"


REVISION_REF_PREFIXES: tuple[str, ...] = (
    REVISION_REF_PREFIX_REMOTES,
    REVISION_REF_PREFIX_HEADS,
    REVISION_REF_PREFIX_TAGS,
)


REVISION_CLASSIFICATION_VERSION = "version"


REVISION_CLASSIFICATION_BRANCH = "branch"


KANON_OUTDATED_FORMAT = "KANON_OUTDATED_FORMAT"


KANON_OUTDATED_FORMAT_DEFAULT = "table"


KANON_OUTDATED_FORMAT_JSON = "json"


KANON_WHY_FORMAT_JSON = "json"


KANON_OUTDATED_JSON_INDENT: int = _env_int("KANON_OUTDATED_JSON_INDENT", 2)


BRANCH_SHA_TRUNCATION_LENGTH = 12


SHA1_HEX_LENGTH = 40
SHA256_HEX_LENGTH = 64


KANON_WHY_FORMAT = "KANON_WHY_FORMAT"


KANON_WHY_FORMAT_DEFAULT = "text"


KANON_WHY_JSON_INDENT: int = _env_int("KANON_WHY_JSON_INDENT", 2)
if KANON_WHY_JSON_INDENT < 0:
    raise SystemExit(f"ERROR: KANON_WHY_JSON_INDENT must be a non-negative integer; got {KANON_WHY_JSON_INDENT}")


KANON_LIST_OUTPUT_FORMAT = "KANON_LIST_OUTPUT_FORMAT"


KANON_LIST_OUTPUT_FORMAT_TABLE = "table"


KANON_LIST_OUTPUT_FORMAT_JSON = "json"


KANON_LIST_OUTPUT_FORMAT_DEFAULT = KANON_LIST_OUTPUT_FORMAT_TABLE


KANON_LIST_OUTPUT_FORMAT_CHOICES: tuple[str, ...] = (
    KANON_LIST_OUTPUT_FORMAT_TABLE,
    KANON_LIST_OUTPUT_FORMAT_JSON,
)


KANON_LIST_JSON_INDENT: int = _env_int("KANON_LIST_JSON_INDENT", 2)
if KANON_LIST_JSON_INDENT < 0:
    raise SystemExit(f"ERROR: KANON_LIST_JSON_INDENT must be a non-negative integer; got {KANON_LIST_JSON_INDENT}")


KANON_LIST_STATUS_INSTALLED = "installed"


KANON_LIST_STATUS_NOT_INSTALLED = "not-installed"


KANON_LIST_STATUS_ORPHAN = "orphan"


KANON_LIST_STATUS_CHOICES: tuple[str, ...] = (
    KANON_LIST_STATUS_INSTALLED,
    KANON_LIST_STATUS_NOT_INSTALLED,
    KANON_LIST_STATUS_ORPHAN,
)


KANON_LIST_SCOPE_DIRECT = "direct"


KANON_LIST_SCOPE_TRANSITIVE = "transitive"


KANON_LIST_COLUMN_SOURCE = "SOURCE"


KANON_LIST_COLUMN_REF = "REF"


KANON_LIST_COLUMN_STATUS = "STATUS"


KANON_LIST_REF_UNRESOLVED = "-"


KANON_LIST_TREE_INDENT = "  "


KANON_LIST_NO_SOURCES_NOTE = "no dependencies declared in .kanon (add one with 'kanon add')"


KANON_LIST_NO_LOCKFILE_NOTE = "no .kanon.lock found -- declared sources are not installed yet (run 'kanon install')"


KANON_CATALOG_AUDIT_VALID_CHECKS: frozenset[str] = frozenset(
    {
        "metadata",
        "source-name-derivation",
        "entry-name-uniqueness",
        "remote-url",
        "tag-format",
    }
)


KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS: int = _env_int("KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS", 3600)
if KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS <= 0:
    raise SystemExit(
        f"ERROR: KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS must be a positive integer; "
        f"got {KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS}"
    )


KANON_CATALOG_AUDIT_CACHE_SUBDIR = "catalog-audit"


KANON_CATALOG_AUDIT_FORMAT_ENV = "KANON_CATALOG_AUDIT_FORMAT"


KANON_CATALOG_AUDIT_FORMAT_DEFAULT = "text"


KANON_CATALOG_AUDIT_FORMAT_JSON = "json"


KANON_CATALOG_METADATA_REQUIRED_FIELDS: tuple[str, ...] = (
    "name",
    "display-name",
    "description",
    "version",
)


KANON_CATALOG_METADATA_RECOMMENDED_FIELDS: tuple[str, ...] = (
    "type",
    "owner-name",
    "owner-email",
    "keywords",
)


KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT: int = _env_int("KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT", 50)
if KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT <= 0:
    raise SystemExit(
        f"ERROR: KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT must be a positive integer; "
        f"got {KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT}"
    )


KANON_CATALOG_AUDIT_TAG_FORMAT_SUMMARY_TEMPLATE = (
    "{remaining} additional non-PEP-440 tag(s) not listed above. "
    "Run 'kanon catalog audit --check tag-format' for the full list."
)


KANON_CATALOG_AUDIT_STRICT_SUMMARY_TEMPLATE = "strict mode: {count} warning(s) treated as errors"


KANON_CATALOG_AUDIT_LEGACY_DIR_WARNING_TEMPLATE = (
    "Legacy catalog/ directory detected; this directory is unused by "
    "kanon >= {version} and should be deleted; "
    "see docs/archive/upgrading-from-2x.md"
)


FINDING_SEVERITY_OK = "ok"
FINDING_SEVERITY_FAIL = "fail"
FINDING_SEVERITY_INFO = "info"


FINDING_PREFIX_OK = "[ok]"
FINDING_PREFIX_FAIL = "[fail]"
FINDING_PREFIX_INFO = "[info]"


WHY_SCOPE_TOP_LEVEL = "top_level"


WHY_SCOPE_TRANSITIVE = "transitive"


KANON_WHY_SUGGEST_MAX_DISTANCE: int = _env_int("KANON_WHY_SUGGEST_MAX_DISTANCE", 3)
if KANON_WHY_SUGGEST_MAX_DISTANCE < 0:
    raise SystemExit(
        f"ERROR: KANON_WHY_SUGGEST_MAX_DISTANCE must be a non-negative integer; got {KANON_WHY_SUGGEST_MAX_DISTANCE}"
    )


KANON_WHY_SUGGEST_TOP_N: int = _env_int("KANON_WHY_SUGGEST_TOP_N", 3)
if KANON_WHY_SUGGEST_TOP_N < 0:
    raise SystemExit(f"ERROR: KANON_WHY_SUGGEST_TOP_N must be a non-negative integer; got {KANON_WHY_SUGGEST_TOP_N}")


KANON_COMPLETER_COMMAND_PREFIX = "__complete"


KANON_TELEMETRY_TOOL_NAME = "kanon"


KANON_TELEMETRY_EVENT_TYPE = "cli_command"


KANON_TELEMETRY_SCHEMA_VERSION = 1


KANON_TELEMETRY_SERVICE_NAME = "kanon-cli"


KANON_TELEMETRY_ENDPOINT_ENV = "KANON_TELEMETRY_ENDPOINT"
KANON_TELEMETRY_ENDPOINT_DEFAULT = "https://collector.platform.solutions.caylent.com/v1/logs"


KANON_TELEMETRY_DISABLED_ENV = "KANON_TELEMETRY_DISABLED"


KANON_TELEMETRY_FORCE_ENV = "KANON_TELEMETRY_FORCE"


KANON_TELEMETRY_DEBUG_ENV = "KANON_TELEMETRY_DEBUG"


KANON_TELEMETRY_TRUTHY_VALUES: frozenset[str] = frozenset({"1", "true", "yes", "on"})


KANON_TELEMETRY_CONTENT_TYPE = "application/json"


KANON_TELEMETRY_LOG_ENV = "KANON_TELEMETRY_LOG"


KANON_TELEMETRY_ERROR_LOG_FILENAME = "telemetry-errors.log"


KANON_TELEMETRY_STATUS_OK = "ok"
KANON_TELEMETRY_STATUS_ERROR = "error"


KANON_TELEMETRY_SCOPE_DIRECT = "direct"
KANON_TELEMETRY_SCOPE_TRANSITIVE = "transitive"


KANON_TELEMETRY_INSTALL_TYPE_EDITABLE = "editable"
KANON_TELEMETRY_INSTALL_TYPE_SOURCE = "source"
KANON_TELEMETRY_INSTALL_TYPE_WHEEL = "wheel"


KANON_TELEMETRY_INSTALL_COMMANDS: frozenset[str] = frozenset({"install"})


KANON_TELEMETRY_FLAG_VALUE_ALLOWLIST: frozenset[str] = frozenset({"format", "status"})


KANON_TELEMETRY_INTERNAL_ARG_KEYS: frozenset[str] = frozenset({"func", "parser", "command"})


KANON_TELEMETRY_VERSION_COMMAND = "--version"
KANON_TELEMETRY_HELP_COMMAND = "--help"
KANON_TELEMETRY_HELP_TOKENS: frozenset[str] = frozenset({KANON_TELEMETRY_HELP_COMMAND, "-h"})
KANON_TELEMETRY_EARLY_EXIT_COMMAND = "<none>"


KANON_TELEMETRY_DEBUG_FLAG = "--telemetry-debug"
KANON_TELEMETRY_ENDPOINT_FLAG = "--telemetry-endpoint"


KANON_CI_ENV = "CI"


KANON_TELEMETRY_CONNECT_TIMEOUT: int = _env_int("KANON_TELEMETRY_CONNECT_TIMEOUT", 2)
if KANON_TELEMETRY_CONNECT_TIMEOUT <= 0:
    raise SystemExit(
        f"ERROR: KANON_TELEMETRY_CONNECT_TIMEOUT must be a positive integer; got {KANON_TELEMETRY_CONNECT_TIMEOUT}"
    )


KANON_TELEMETRY_READ_TIMEOUT: int = _env_int("KANON_TELEMETRY_READ_TIMEOUT", 3)
if KANON_TELEMETRY_READ_TIMEOUT <= 0:
    raise SystemExit(
        f"ERROR: KANON_TELEMETRY_READ_TIMEOUT must be a positive integer; got {KANON_TELEMETRY_READ_TIMEOUT}"
    )


KANON_TELEMETRY_GIT_TIMEOUT: int = _env_int("KANON_TELEMETRY_GIT_TIMEOUT", 3)
if KANON_TELEMETRY_GIT_TIMEOUT <= 0:
    raise SystemExit(
        f"ERROR: KANON_TELEMETRY_GIT_TIMEOUT must be a positive integer; got {KANON_TELEMETRY_GIT_TIMEOUT}"
    )


KANON_TELEMETRY_MAX_BODY_BYTES: int = _env_int("KANON_TELEMETRY_MAX_BODY_BYTES", 4 * 1024 * 1024)
if KANON_TELEMETRY_MAX_BODY_BYTES <= 0:
    raise SystemExit(
        f"ERROR: KANON_TELEMETRY_MAX_BODY_BYTES must be a positive integer; got {KANON_TELEMETRY_MAX_BODY_BYTES}"
    )


KANON_TELEMETRY_GRAPH_SIZE_CAP: int = _env_int("KANON_TELEMETRY_GRAPH_SIZE_CAP", 3 * 1024 * 1024)
if KANON_TELEMETRY_GRAPH_SIZE_CAP <= 0:
    raise SystemExit(
        f"ERROR: KANON_TELEMETRY_GRAPH_SIZE_CAP must be a positive integer; got {KANON_TELEMETRY_GRAPH_SIZE_CAP}"
    )


KANON_SYNC_JOBS_ENV = "KANON_SYNC_JOBS"


REPO_DEFAULT_NETWORK_JOBS = 1
"""The job count repo sync uses for network fetch when given no --jobs.

Mirrors repo/subcmds/sync.py. Deliberately not the same as the local-checkout
default: conflating the two is what made a single --jobs=N raise network
fan-out while appearing to bound it.
"""


def resolve_sync_jobs() -> int | None:
    """Return the operator-requested ``repo sync`` job count, or ``None`` when unset.

    ``repo sync`` resolves two independent job counts whose defaults differ:
    network fetch is 1 and local checkout is ``min(os.cpu_count(), 8)``. The value
    here is an upper bound applied to each against its own default, never a single
    ``--jobs`` that would set both -- doing that raised network fan-out while
    appearing to bound it. When many
    ``kanon`` processes run concurrently on one machine -- most acutely a
    ``pytest-xdist`` run, where every worker drives its own ``kanon install`` --
    each of those pools contends for the same POSIX semaphores, and the pool
    workers can block in ``sem_wait()`` while the parent blocks in ``waitpid()``,
    deadlocking both indefinitely. Setting this variable to ``1`` takes the
    single-process short-circuit in ``repo.command`` and builds no pool at all.

    Unlike the other tunables in this module this is resolved per call rather than
    at import, because callers (and the test suite) set it through the process
    environment after ``kanon_cli`` has already been imported.

    Returns:
        The positive integer job count when ``KANON_SYNC_JOBS`` is set, otherwise
        ``None`` so ``repo sync`` keeps its own default.

    Raises:
        SystemExit: When the variable is set to anything but a positive integer.
    """
    raw = os.environ.get(KANON_SYNC_JOBS_ENV)
    if raw is None:
        return None
    try:
        jobs = int(raw)
    except ValueError:
        raise SystemExit(f"ERROR: {KANON_SYNC_JOBS_ENV} must be a positive integer; got {raw!r}")
    if jobs <= 0:
        raise SystemExit(f"ERROR: {KANON_SYNC_JOBS_ENV} must be a positive integer; got {jobs}")
    return jobs


KANON_ALLOWED_ABS_ROOTS_ENV = "KANON_ALLOWED_ABS_ROOTS"
"""Operator-facing list of extra roots an absolute manifest ``dest`` may resolve under."""

KANON_PERMITTED_ABS_ROOTS_ENV = "KANON_PERMITTED_ABS_ROOTS"
"""Internal, fully resolved permitted-root list handed to the vendored repo tool."""

ABS_ROOTS_SEPARATOR = os.pathsep


def resolve_allowed_abs_roots() -> list[str]:
    """Return the operator-supplied extra roots for absolute manifest destinations.

    A ``<linkfile>`` or ``<copyfile>`` may declare an absolute ``dest``. Such a
    destination is confined to a set of permitted roots so that a manifest fetched
    from a remote repository cannot write outside the consuming project. Two roots
    are always permitted and are supplied by the caller rather than this function:
    the consumer project root and the resolved ``CLAUDE_MARKETPLACES_DIR``. This
    function returns only the *additional* roots an operator has opted into, in
    precedence order ``--allow-abs-root`` flag > ``KANON_ALLOWED_ABS_ROOTS`` env
    var > none. The flag is folded into the environment variable by
    :func:`kanon_cli.core.cli_args.apply_global_flags` before this runs, so only
    the variable is read here.

    Because the two built-in roots are unconditional, this setting can only widen
    the boundary, never narrow it below the project being installed into.

    Returns:
        The operator-supplied roots as absolute path strings, in the order given,
        with duplicates preserved (the caller de-duplicates against the built-ins).

    Raises:
        SystemExit: When the variable is set but contains an empty entry or a
            relative path, either of which would silently widen the boundary in a
            way the operator did not intend.
    """
    raw = os.environ.get(KANON_ALLOWED_ABS_ROOTS_ENV)
    if not raw:
        return []
    roots: list[str] = []
    for entry in raw.split(ABS_ROOTS_SEPARATOR):
        if not entry.strip():
            raise SystemExit(
                f"ERROR: {KANON_ALLOWED_ABS_ROOTS_ENV} contains an empty entry; "
                f"expected {ABS_ROOTS_SEPARATOR!r}-separated absolute paths, got {raw!r}"
            )
        if not os.path.isabs(entry):
            raise SystemExit(f"ERROR: {KANON_ALLOWED_ABS_ROOTS_ENV} entries must be absolute paths; got {entry!r}")
        roots.append(os.path.normpath(entry))
    return roots


def format_permitted_abs_roots(roots: list[str]) -> str:
    """Serialise permitted roots for :data:`KANON_PERMITTED_ABS_ROOTS_ENV`.

    Args:
        roots: Absolute path strings, already resolved and de-duplicated.

    Returns:
        The separator-joined value to place in the environment.
    """
    return ABS_ROOTS_SEPARATOR.join(roots)


def parse_permitted_abs_roots(raw: str) -> list[str]:
    """Parse the serialised permitted-root list.

    Args:
        raw: The raw environment value, possibly empty.

    Returns:
        The absolute path strings it encodes; empty when *raw* is empty.
    """
    if not raw:
        return []
    return [entry for entry in raw.split(ABS_ROOTS_SEPARATOR) if entry]
