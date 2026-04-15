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
import os
from xml.dom import minidom
from xml.dom.minidom import parseString

from command import Command
from command import MirrorSafeCommand


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

        for file in files:
            print(file)
            if os.path.getsize(file) > 0:
                self.EnvSubst(file)

    def EnvSubst(self, infile):
        doc = minidom.parse(infile)
        self.search_replace_placeholders(doc)
        os.rename(infile, infile + ".bak")
        self.save(infile, doc)

    def save(self, outfile, doc):
        """Save the modified XML document with comments and the XML header."""

        def pretty_print(data):
            return "\n".join(
                [line for line in parseString(data).toprettyxml(indent=" " * 2).split("\n") if line.strip()]
            )

        with open(outfile, "wb") as f:
            f.write(str.encode(pretty_print(doc.toprettyxml(encoding="utf-8"))))

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
