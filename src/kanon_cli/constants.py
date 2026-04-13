"""Centralized constants for the kanon-cli package.

All module-level constants live here to avoid hard-coded values
scattered across source files.
"""

import re

# -- Package identity --
PYPI_REPO_TOOL_PACKAGE = "rpm-git-repo"

# -- Marketplace validation --
MARKETPLACE_DIR_PREFIX = "${CLAUDE_MARKETPLACES_DIR}/"
MARKETPLACE_FILE_GLOB = "*-marketplace.xml"
ALLOWED_BRANCHES = frozenset({"main", "review/caylent-claude"})
REFS_TAGS_RE = re.compile(r"^refs/tags/.+/\d+\.\d+\.\d+$")
CONSTRAINT_RE = re.compile(r"^(~=|>=|<=|>|<)\d+\.\d+\.\d+$")

# -- Version resolution --
PEP440_OPERATORS = ("~=", ">=", "<=", "!=", "==", ">", "<")

# -- kanonenv parsing --
SOURCE_PREFIX = "KANON_SOURCE_"
SOURCE_SUFFIXES = ("_URL", "_REVISION", "_PATH")
SUFFIX_TO_KEY = {"_URL": "url", "_REVISION": "revision", "_PATH": "path"}
SHELL_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")

# -- Catalog --
CATALOG_ENV_VAR = "KANON_CATALOG_SOURCE"
