# Copyright (C) 2011 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import glob
import logging
import os
import re
from xml.dom import minidom
from xml.parsers.expat import ExpatError

from ..command import Command
from ..command import MirrorSafeCommand

_LOG = logging.getLogger(__name__)

# Regex that matches any ${VAR_NAME} pattern remaining after expandvars().
# A match indicates that VAR_NAME was not defined in the environment.
_UNRESOLVED_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

# Regex that matches nested ${...${...}...} patterns where an inner ${...}
# appears inside an outer ${...}. expandvars() cannot resolve these patterns
# and leaves them unchanged. Each match captures the full nested pattern text.
_NESTED_VAR_PATTERN = re.compile(r"\$\{[^}$]*\$\{[^}]*\}[^}$]*\}")


def _collect_unresolved_vars(doc):
    """Return the set of variable names that remain unresolved in the document.

    Scans all attribute values and text node values in the DOM for patterns
    matching _UNRESOLVED_PATTERN and collects the variable names. A match
    indicates expandvars() left the placeholder intact because the variable
    was not defined in the environment.

    Args:
        doc: A minidom Document node after search_replace_placeholders() has run.

    Returns:
        A set of variable name strings (without the ${} delimiters).
    """
    unresolved = set()
    for elem in doc.getElementsByTagName("*"):
        for _key, value in elem.attributes.items():
            for match in _UNRESOLVED_PATTERN.finditer(value):
                unresolved.add(match.group(1))
        if elem.firstChild and elem.firstChild.nodeType == elem.TEXT_NODE:
            for match in _UNRESOLVED_PATTERN.finditer(elem.firstChild.nodeValue):
                unresolved.add(match.group(1))
    return unresolved


def _warn_nested_vars(content, infile):
    """Scan raw file content for nested ${...${...}...} patterns and warn.

    Nested variable references such as ${VAR_${INNER}} cannot be resolved by
    os.path.expandvars(). Each occurrence is logged as a WARNING including the
    full pattern text so the user can identify which references need attention.

    The tool does not attempt to resolve nested variables.

    Args:
        content: Raw text content of the file (before or after substitution).
        infile: Path to the file being processed, included in each warning.
    """
    for match in _NESTED_VAR_PATTERN.finditer(content):
        _LOG.warning(
            "Nested variable reference %s in %s -- expandvars() cannot resolve nested patterns",
            match.group(0),
            infile,
        )


class Envsubst(Command, MirrorSafeCommand):
    COMMON = True
    helpSummary = "Replace ENV vars in all xml manifest files"
    helpUsage = """
%prog
"""
    helpDescription = """
Replace ENV vars in all xml manifest files

Finds all XML files in the manifests and replaces environment
variables with values.
"""
    path = ".repo/manifests/**/*.xml"

    def Execute(self, opt, args):
        """Substitute all ${ENVVAR} references in manifest xml files.

        Args:
            opt: The options.
            args: Positional args (unused).
        """
        print(f"Executing envsubst {opt}, {args}")
        files = glob.glob(self.path, recursive=True)

        if not files:
            _LOG.warning("No files matched glob pattern: %s", self.path)
            return

        all_unresolved = set()
        for file in files:
            print(file)
            if os.path.getsize(file) > 0:
                unresolved = self.EnvSubst(file)
                if unresolved:
                    all_unresolved.update(unresolved)

        if all_unresolved:
            sorted_vars = sorted(all_unresolved)
            print(f"Unresolved environment variables: {', '.join(sorted_vars)}")

    def EnvSubst(self, infile):
        """Substitute environment variables in the given XML manifest file.

        Reads the raw file content and scans for nested ${...${...}...}
        patterns, logging a WARNING for each occurrence (Bug 16). Then parses
        the XML, performs variable substitution via expandvars(), and scans for
        any remaining ${VAR} patterns (undefined variables), logging a WARNING
        per unresolved variable name.

        Saves the modified document using string-based line filtering instead of
        a second XML parse (Bug 18 fix).

        Args:
            infile: Path to the XML manifest file to process.

        Returns:
            A set of variable name strings that were left unresolved, or an
            empty set if all variables were resolved (or parsing failed).
        """
        with open(infile, encoding="utf-8") as fh:
            raw_content = fh.read()

        # Bug 16: detect nested ${...${...}...} patterns before substitution.
        _warn_nested_vars(raw_content, infile)

        try:
            doc = minidom.parseString(raw_content.encode("utf-8"))
        except ExpatError as exc:
            _LOG.error("Skipping %s: malformed XML -- %s", infile, exc)
            return set()
        self.search_replace_placeholders(doc)
        unresolved = _collect_unresolved_vars(doc)
        for var_name in sorted(unresolved):
            _LOG.warning("Unresolved variable ${%s} in %s", var_name, infile)
        bak_path = infile + ".bak"
        if os.path.exists(bak_path):
            os.remove(bak_path)
        os.rename(infile, bak_path)
        self.save(infile, doc)
        return unresolved

    def save(self, outfile, doc):
        """Save the modified XML document using string-based line filtering.

        Serializes the DOM to pretty-printed XML via toprettyxml(), then filters
        blank lines using string manipulation. This replaces the previous
        double-parse approach that re-parsed the output with parseString() just
        to remove empty lines (Bug 18 fix).
        """
        pretty_xml = doc.toprettyxml(indent=" " * 2)
        filtered = "\n".join(line for line in pretty_xml.splitlines() if line.strip())
        with open(outfile, "wb") as f:
            f.write(filtered.encode("utf-8"))

    def search_replace_placeholders(self, doc):
        """Replace ${PLACEHOLDER} in texts and attributes with values."""
        for elem in doc.getElementsByTagName("*"):
            for key, value in elem.attributes.items():
                # Check if the attribute value contains an environment variable
                if self.is_placeholder_detected(value):
                    # Replace the environment variable with its value
                    elem.setAttribute(key, self.resolve_variable(value))
            if (
                elem.firstChild
                and elem.firstChild.nodeType == elem.TEXT_NODE
                and self.is_placeholder_detected(elem.firstChild.nodeValue)
            ):
                # Replace the environment variable with its value
                elem.firstChild.nodeValue = self.resolve_variable(elem.firstChild.nodeValue)

    def is_placeholder_detected(self, value):
        return "$" in value

    def resolve_variable(self, var_name):
        """Resolve variables from OS environment variables."""
        return os.path.expandvars(var_name)
