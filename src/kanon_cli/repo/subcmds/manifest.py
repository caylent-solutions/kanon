# Copyright (C) 2009 The Android Open Source Project
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

import enum
import functools
import json
import optparse
import sys
from typing import Callable

from ..command import PagedCommand
from ..git_command import GitCommandError
from ..repo_logging import RepoLogger


logger = RepoLogger(__file__)

# Prefix applied to tag names when building the revision string for the
# ``--revision-as-tag`` output.
_REFS_TAGS_PREFIX = "refs/tags/"


def _lookup_exact_tag(project: object) -> str:
    """Return ``refs/tags/<name>`` for the exact tag at the project's HEAD.

    Calls ``git describe --exact-match HEAD`` on the project's working
    directory.  Raises :exc:`GitCommandError` when no tag points exactly
    at HEAD so callers can decide how to handle untagged commits.

    Args:
        project: A ``kanon_cli.repo.project.Project`` instance.

    Returns:
        A string of the form ``refs/tags/<tag-name>``.

    Raises:
        GitCommandError: When ``git describe --exact-match`` exits non-zero
            (i.e. no exact tag for HEAD).
    """
    tag_name = project.work_git.describe("--exact-match", "HEAD")
    return _REFS_TAGS_PREFIX + tag_name


def _apply_revision_as_tag(
    doc: object,
    project_relpath: str,
    lookup_fn: Callable[[], str],
) -> None:
    """Set or replace the ``revision`` attribute for the ``<project>`` matching *project_relpath*.

    Finds the ``<project>`` element in *doc* whose ``path`` attribute (or
    ``name`` attribute when ``path`` is absent) equals *project_relpath*.
    Calls ``lookup_fn()`` to obtain the tag reference string and sets or
    updates the ``revision`` attribute.  This ensures that even projects that
    inherit the default revision (no explicit ``revision`` attribute) get a
    tag reference written when an exact tag exists.

    If ``lookup_fn()`` raises :exc:`GitCommandError` (no exact tag at HEAD),
    a structured warning is emitted to stderr identifying the project by its
    relative path before continuing.  The ``revision`` attribute is left
    unchanged (or remains absent) so the manifest stays valid for untagged
    projects.

    Args:
        doc: A ``xml.dom.minidom.Document`` produced by ``manifest.ToXml()``.
        project_relpath: The relative path of the project within the checkout;
            used to locate the correct ``<project>`` DOM element.
        lookup_fn: A zero-argument callable returning ``refs/tags/<name>``.
            Expected to raise :exc:`GitCommandError` when no exact tag is found.
    """
    for element in doc.getElementsByTagName("project"):
        elem_path = element.getAttribute("path") or element.getAttribute("name")
        if elem_path != project_relpath:
            continue
        try:
            tag_ref = lookup_fn()
        except GitCommandError:
            print(
                f"warning: {project_relpath}: no exact tag at HEAD; revision unchanged",
                file=sys.stderr,
            )
            continue
        element.setAttribute("revision", tag_ref)


class OutputFormat(enum.Enum):
    """Type for the requested output format."""

    # Canonicalized manifest in XML format.
    XML = enum.auto()

    # Canonicalized manifest in JSON format.
    JSON = enum.auto()


class Manifest(PagedCommand):
    COMMON = False
    helpSummary = "Manifest inspection utility"
    helpUsage = """
%prog [-o {-|NAME.xml}] [-m MANIFEST.xml] [-r]
"""
    _helpDescription = """

With the -o option, exports the current manifest for inspection.
The manifest and (if present) local_manifests/ are combined
together to produce a single manifest file.  This file can be stored
in a Git repository for use during future 'repo init' invocations.

The -r option can be used to generate a manifest file with project
revisions set to the current commit hash.  These are known as
"revision locked manifests", as they don't follow a particular branch.
In this case, the 'upstream' attribute is set to the ref we were on
when the manifest was generated.  The 'dest-branch' attribute is set
to indicate the remote ref to push changes to via 'repo upload'.

Multiple output formats are supported via --format.  The default output
is XML, and formats are generally "condensed".  Use --pretty for more
human-readable variations.
"""

    @property
    def helpDescription(self):
        return (
            self._helpDescription + "\nFor the full manifest XML schema, see docs/repo/manifest-format.md"
            " (https://github.com/caylent-solutions/kanon/blob/main/docs/repo/manifest-format.md).\n"
        )

    def _Options(self, p):
        p.add_option(
            "-r",
            "--revision-as-HEAD",
            dest="peg_rev",
            action="store_true",
            help="save revisions as current HEAD",
        )
        p.add_option(
            "-m",
            "--manifest-name",
            help="temporary manifest to use for this sync",
            metavar="NAME.xml",
        )
        p.add_option(
            "--suppress-upstream-revision",
            dest="peg_rev_upstream",
            default=True,
            action="store_false",
            help="if in -r mode, do not write the upstream field "
            "(only of use if the branch names for a sha1 manifest are "
            "sensitive)",
        )
        p.add_option(
            "--suppress-dest-branch",
            dest="peg_rev_dest_branch",
            default=True,
            action="store_false",
            help="if in -r mode, do not write the dest-branch field "
            "(only of use if the branch names for a sha1 manifest are "
            "sensitive)",
        )
        # Replaced with --format=json.  Kept for backwards compatibility.
        # Can delete in Jun 2026 or later.
        p.add_option(
            "--json",
            action="store_const",
            dest="format",
            const=OutputFormat.JSON.name.lower(),
            help=optparse.SUPPRESS_HELP,
        )
        formats = tuple(x.lower() for x in OutputFormat.__members__.keys())
        p.add_option(
            "--format",
            default=OutputFormat.XML.name.lower(),
            choices=formats,
            help=f"output format: {', '.join(formats)} (default: %default)",
        )
        p.add_option(
            "--pretty",
            default=False,
            action="store_true",
            help="format output for humans to read",
        )
        p.add_option(
            "--no-local-manifests",
            default=False,
            action="store_true",
            dest="ignore_local_manifests",
            help="ignore local manifests",
        )
        p.add_option(
            "-o",
            "--output-file",
            default="-",
            help="file to save the manifest to. (Filename prefix for multi-tree.)",
            metavar="-|NAME.xml",
        )
        p.add_option(
            "--revision-as-tag",
            default=False,
            action="store_true",
            help="replace each project's revision with the nearest exact git tag "
            "(refs/tags/<name>); projects with no exact tag keep their original revision",
        )

    def _Output(self, opt):
        # If alternate manifest is specified, override the manifest file that
        # we're using.
        if opt.manifest_name:
            self.manifest.Override(opt.manifest_name, False)

        output_format = OutputFormat[opt.format.upper()]

        for manifest in self.ManifestList(opt):
            output_file = opt.output_file
            if output_file == "-":
                fd = sys.stdout
            else:
                if manifest.path_prefix:
                    output_file = f"{opt.output_file}:{manifest.path_prefix.replace('/', '%2f')}"
                fd = open(output_file, "w")

            manifest.SetUseLocalManifests(not opt.ignore_local_manifests)

            if output_format == OutputFormat.JSON:
                doc = manifest.ToDict(
                    peg_rev=opt.peg_rev,
                    peg_rev_upstream=opt.peg_rev_upstream,
                    peg_rev_dest_branch=opt.peg_rev_dest_branch,
                )

                json_settings = {
                    # JSON style guide says Unicode characters are fully
                    # allowed.
                    "ensure_ascii": False,
                    # We use 2 space indent to match JSON style guide.
                    "indent": 2 if opt.pretty else None,
                    "separators": (",", ": ") if opt.pretty else (",", ":"),
                    "sort_keys": True,
                }
                fd.write(json.dumps(doc, **json_settings) + "\n")
            elif opt.revision_as_tag:
                xml_doc = manifest.ToXml(
                    peg_rev=opt.peg_rev,
                    peg_rev_upstream=opt.peg_rev_upstream,
                    peg_rev_dest_branch=opt.peg_rev_dest_branch,
                )
                for project in manifest.projects:
                    _apply_revision_as_tag(
                        xml_doc,
                        project.relpath,
                        functools.partial(_lookup_exact_tag, project),
                    )
                xml_doc.writexml(fd, "", "  ", "\n", "UTF-8")
            else:
                manifest.Save(
                    fd,
                    peg_rev=opt.peg_rev,
                    peg_rev_upstream=opt.peg_rev_upstream,
                    peg_rev_dest_branch=opt.peg_rev_dest_branch,
                )
            if output_file != "-":
                fd.close()
                if manifest.path_prefix:
                    logger.warning(
                        "Saved %s submanifest to %s",
                        manifest.path_prefix,
                        output_file,
                    )
                else:
                    logger.warning("Saved manifest to %s", output_file)

    def ValidateOptions(self, opt, args):
        if args:
            self.Usage()

    def Execute(self, opt, args):
        self._Output(opt)
