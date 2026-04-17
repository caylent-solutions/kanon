# Copyright (C) 2024 The Android Open Source Project
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

"""Unit tests for subcmds/manifest.py coverage."""

from unittest import mock

import pytest

from kanon_cli.repo.subcmds.manifest import Manifest, OutputFormat


def _make_cmd():
    """Create a Manifest command instance for testing."""
    cmd = Manifest.__new__(Manifest)
    cmd.manifest = mock.MagicMock()
    cmd.ManifestList = mock.MagicMock()
    cmd.Usage = mock.MagicMock()
    return cmd


@pytest.mark.unit
def test_output_format_enum():
    """Test OutputFormat enum."""
    assert OutputFormat.XML is not None
    assert OutputFormat.JSON is not None


@pytest.mark.unit
def test_options():
    """Test _Options method."""
    cmd = _make_cmd()
    parser = mock.MagicMock()
    cmd._Options(parser)

    # Should add multiple options
    assert parser.add_option.call_count >= 8


@pytest.mark.unit
def test_validate_options_no_args():
    """Test ValidateOptions with no args."""
    cmd = _make_cmd()
    opt = mock.MagicMock()

    cmd.ValidateOptions(opt, [])

    cmd.Usage.assert_not_called()


@pytest.mark.unit
def test_validate_options_with_args():
    """Test ValidateOptions with args calls Usage."""
    cmd = _make_cmd()
    opt = mock.MagicMock()

    cmd.ValidateOptions(opt, ["arg"])

    cmd.Usage.assert_called_once()


@pytest.mark.unit
def test_execute():
    """Test Execute calls _Output."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    args = []

    with mock.patch.object(cmd, "_Output") as mock_output:
        cmd.Execute(opt, args)

        mock_output.assert_called_once_with(opt)


@pytest.mark.unit
def test_output_xml_to_stdout():
    """Test _Output with XML format to stdout."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.manifest_name = None
    opt.output_file = "-"
    opt.format = "xml"
    opt.peg_rev = False
    opt.peg_rev_upstream = True
    opt.peg_rev_dest_branch = True
    opt.ignore_local_manifests = False

    manifest = mock.MagicMock()
    manifest.path_prefix = None
    cmd.ManifestList.return_value = [manifest]

    with mock.patch("sys.stdout"):
        cmd._Output(opt)

        manifest.Save.assert_called_once()


@pytest.mark.unit
def test_output_json_to_stdout():
    """Test _Output with JSON format to stdout."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.manifest_name = None
    opt.output_file = "-"
    opt.format = "json"
    opt.peg_rev = False
    opt.peg_rev_upstream = True
    opt.peg_rev_dest_branch = True
    opt.ignore_local_manifests = False
    opt.pretty = False

    manifest = mock.MagicMock()
    manifest.path_prefix = None
    manifest.ToDict.return_value = {"version": "1.0"}
    cmd.ManifestList.return_value = [manifest]

    with mock.patch("sys.stdout"):
        cmd._Output(opt)

        manifest.ToDict.assert_called_once()


@pytest.mark.unit
def test_output_json_pretty():
    """Test _Output with JSON format and pretty option."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.manifest_name = None
    opt.output_file = "-"
    opt.format = "json"
    opt.peg_rev = False
    opt.peg_rev_upstream = True
    opt.peg_rev_dest_branch = True
    opt.ignore_local_manifests = False
    opt.pretty = True

    manifest = mock.MagicMock()
    manifest.path_prefix = None
    manifest.ToDict.return_value = {"version": "1.0"}
    cmd.ManifestList.return_value = [manifest]

    with mock.patch("sys.stdout"):
        with mock.patch("builtins.open", mock.mock_open()):
            cmd._Output(opt)

            # Should call ToDict with pretty formatting
            manifest.ToDict.assert_called_once()


@pytest.mark.unit
def test_output_to_file():
    """Test _Output writes to file."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.manifest_name = None
    opt.output_file = "/tmp/manifest.xml"
    opt.format = "xml"
    opt.peg_rev = False
    opt.peg_rev_upstream = True
    opt.peg_rev_dest_branch = True
    opt.ignore_local_manifests = False

    manifest = mock.MagicMock()
    manifest.path_prefix = None
    cmd.ManifestList.return_value = [manifest]

    with mock.patch("builtins.open", mock.mock_open()) as mock_file:
        cmd._Output(opt)

        mock_file.assert_called_once_with("/tmp/manifest.xml", "w")
        manifest.Save.assert_called_once()


@pytest.mark.unit
def test_output_with_path_prefix():
    """Test _Output with submanifest path prefix."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.manifest_name = None
    opt.output_file = "/tmp/manifest.xml"
    opt.format = "xml"
    opt.peg_rev = False
    opt.peg_rev_upstream = True
    opt.peg_rev_dest_branch = True
    opt.ignore_local_manifests = False

    manifest = mock.MagicMock()
    manifest.path_prefix = "sub/path"
    cmd.ManifestList.return_value = [manifest]

    with mock.patch("builtins.open", mock.mock_open()) as mock_file:
        cmd._Output(opt)

        # Should modify output filename with path prefix
        expected_file = "/tmp/manifest.xml:sub%2fpath"
        mock_file.assert_called_once_with(expected_file, "w")


@pytest.mark.unit
def test_output_with_peg_rev():
    """Test _Output with --revision-as-HEAD option."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.manifest_name = None
    opt.output_file = "-"
    opt.format = "xml"
    opt.peg_rev = True
    opt.peg_rev_upstream = True
    opt.peg_rev_dest_branch = True
    opt.ignore_local_manifests = False

    manifest = mock.MagicMock()
    manifest.path_prefix = None
    cmd.ManifestList.return_value = [manifest]

    with mock.patch("sys.stdout"):
        cmd._Output(opt)

        # Should pass peg_rev=True
        manifest.Save.assert_called_once_with(
            mock.ANY,
            peg_rev=True,
            peg_rev_upstream=True,
            peg_rev_dest_branch=True,
        )


@pytest.mark.unit
def test_output_suppress_upstream():
    """Test _Output with --suppress-upstream-revision."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.manifest_name = None
    opt.output_file = "-"
    opt.format = "xml"
    opt.peg_rev = True
    opt.peg_rev_upstream = False
    opt.peg_rev_dest_branch = True
    opt.ignore_local_manifests = False

    manifest = mock.MagicMock()
    manifest.path_prefix = None
    cmd.ManifestList.return_value = [manifest]

    with mock.patch("sys.stdout"):
        cmd._Output(opt)

        manifest.Save.assert_called_once_with(
            mock.ANY,
            peg_rev=True,
            peg_rev_upstream=False,
            peg_rev_dest_branch=True,
        )


@pytest.mark.unit
def test_output_suppress_dest_branch():
    """Test _Output with --suppress-dest-branch."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.manifest_name = None
    opt.output_file = "-"
    opt.format = "xml"
    opt.peg_rev = True
    opt.peg_rev_upstream = True
    opt.peg_rev_dest_branch = False
    opt.ignore_local_manifests = False

    manifest = mock.MagicMock()
    manifest.path_prefix = None
    cmd.ManifestList.return_value = [manifest]

    with mock.patch("sys.stdout"):
        cmd._Output(opt)

        manifest.Save.assert_called_once_with(
            mock.ANY,
            peg_rev=True,
            peg_rev_upstream=True,
            peg_rev_dest_branch=False,
        )


@pytest.mark.unit
def test_output_ignore_local_manifests():
    """Test _Output with --no-local-manifests."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.manifest_name = None
    opt.output_file = "-"
    opt.format = "xml"
    opt.peg_rev = False
    opt.peg_rev_upstream = True
    opt.peg_rev_dest_branch = True
    opt.ignore_local_manifests = True

    manifest = mock.MagicMock()
    manifest.path_prefix = None
    cmd.ManifestList.return_value = [manifest]

    with mock.patch("sys.stdout"):
        cmd._Output(opt)

        manifest.SetUseLocalManifests.assert_called_once_with(False)


@pytest.mark.unit
def test_output_override_manifest():
    """Test _Output with --manifest-name option."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.manifest_name = "custom.xml"
    opt.output_file = "-"
    opt.format = "xml"
    opt.peg_rev = False
    opt.peg_rev_upstream = True
    opt.peg_rev_dest_branch = True
    opt.ignore_local_manifests = False

    manifest = mock.MagicMock()
    manifest.path_prefix = None
    cmd.ManifestList.return_value = [manifest]

    with mock.patch("sys.stdout"):
        cmd._Output(opt)

        cmd.manifest.Override.assert_called_once_with("custom.xml", False)


@pytest.mark.unit
def test_output_multiple_manifests():
    """Test _Output with multiple manifests."""
    cmd = _make_cmd()
    opt = mock.MagicMock()
    opt.manifest_name = None
    opt.output_file = "/tmp/manifest.xml"
    opt.format = "xml"
    opt.peg_rev = False
    opt.peg_rev_upstream = True
    opt.peg_rev_dest_branch = True
    opt.ignore_local_manifests = False

    manifest1 = mock.MagicMock()
    manifest1.path_prefix = None
    manifest2 = mock.MagicMock()
    manifest2.path_prefix = "sub"
    cmd.ManifestList.return_value = [manifest1, manifest2]

    with mock.patch("builtins.open", mock.mock_open()):
        cmd._Output(opt)

        # Should save both manifests
        assert manifest1.Save.call_count == 1
        assert manifest2.Save.call_count == 1


@pytest.mark.unit
def test_help_description_property():
    """helpDescription property returns the base description plus a pointer to docs/repo/manifest-format.md."""
    cmd = _make_cmd()
    desc = cmd.helpDescription

    assert "docs/repo/manifest-format.md" in desc, (
        f"helpDescription must reference the docs/repo/manifest-format.md reference, got:\n{desc!r}"
    )
