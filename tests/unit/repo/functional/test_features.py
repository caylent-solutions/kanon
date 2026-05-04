# Copyright 2024 RPM Contributors
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

"""Functional tests for RPM-specific features.

These tests exercise the features added over the Google upstream repo tool,
running real commands and verifying I/O behavior.
"""

import os

import pytest


@pytest.mark.functional
class TestEnvsubstFeature:
    """Functional tests for the envsubst command."""

    def test_envsubst_replaces_variables_in_manifest(self, tmp_path, monkeypatch):
        """envsubst should replace ${VAR} placeholders in manifest XML."""
        manifests_dir = tmp_path / ".repo" / "manifests"
        manifests_dir.mkdir(parents=True)

        manifest_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="${GITBASE}" '
            'revision="${GITREV}"/>\n'
            '  <project name="test-project" path="test"/>\n'
            "</manifest>\n"
        )
        manifest_file = manifests_dir / "default.xml"
        manifest_file.write_text(manifest_content)

        monkeypatch.setenv("GITBASE", "https://github.com/testorg")
        monkeypatch.setenv("GITREV", "main")

        from kanon_cli.repo.subcmds.envsubst import Envsubst

        cmd = Envsubst.__new__(Envsubst)
        cmd.path = str(manifests_dir / "**" / "*.xml")
        cmd.Execute(opt=None, args=[])

        result = manifest_file.read_text()
        assert "https://github.com/testorg" in result
        assert "main" in result
        assert "${GITBASE}" not in result
        assert "${GITREV}" not in result

    def test_envsubst_creates_backup_files(self, tmp_path):
        """envsubst should create .bak backup files for originals."""
        manifests_dir = tmp_path / ".repo" / "manifests"
        manifests_dir.mkdir(parents=True)

        manifest_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="${MYVAR}"/>\n'
            "</manifest>\n"
        )
        manifest_file = manifests_dir / "default.xml"
        manifest_file.write_text(manifest_content)

        env = os.environ.copy()
        env["MYVAR"] = "replaced_value"

        from kanon_cli.repo.subcmds.envsubst import Envsubst

        cmd = Envsubst.__new__(Envsubst)
        cmd.path = str(manifests_dir / "**" / "*.xml")

        old_env = {}
        for k, v in env.items():
            if k not in os.environ:
                os.environ[k] = v
                old_env[k] = None
            elif os.environ[k] != v:
                old_env[k] = os.environ[k]
                os.environ[k] = v
        try:
            cmd.Execute(opt=None, args=[])
        finally:
            for k, v in old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

        backup_file = manifests_dir / "default.xml.bak"
        assert backup_file.exists()
        assert "${MYVAR}" in backup_file.read_text()


@pytest.mark.functional
class TestVersionConstraints:
    """Functional tests for PEP 440 version constraint resolution."""

    def test_version_constraint_detection(self):
        """is_version_constraint should detect PEP 440 syntax."""
        from kanon_cli.repo.version_constraints import is_version_constraint

        assert is_version_constraint("refs/tags/dev/python/agent/~=1.2.0")
        assert is_version_constraint("refs/tags/dev/python/agent/>=1.0.0,<2.0.0")
        assert is_version_constraint("refs/tags/dev/python/agent/*")
        assert not is_version_constraint("refs/tags/dev/python/agent/1.2.3")
        assert not is_version_constraint("refs/heads/main")

    def test_version_constraint_resolves_to_highest_match(self):
        """resolve_version_constraint should return highest matching tag."""
        from kanon_cli.repo.version_constraints import resolve_version_constraint

        tags = [
            "refs/tags/dev/python/agent/1.2.0",
            "refs/tags/dev/python/agent/1.2.3",
            "refs/tags/dev/python/agent/1.2.7",
            "refs/tags/dev/python/agent/1.3.0",
            "refs/tags/dev/python/agent/2.0.0",
        ]
        result = resolve_version_constraint("refs/tags/dev/python/agent/~=1.2.0", tags)
        assert result == "refs/tags/dev/python/agent/1.2.7"

    def test_version_constraint_wildcard_matches_all(self):
        """Wildcard '*' should match all versions and return highest."""
        from kanon_cli.repo.version_constraints import resolve_version_constraint

        tags = [
            "refs/tags/dev/python/lib/0.1.0",
            "refs/tags/dev/python/lib/1.0.0",
            "refs/tags/dev/python/lib/2.5.0",
        ]
        result = resolve_version_constraint("refs/tags/dev/python/lib/*", tags)
        assert result == "refs/tags/dev/python/lib/2.5.0"

    def test_version_constraint_error_on_no_match(self):
        """Should raise ManifestInvalidRevisionError when no tags match."""
        from kanon_cli.repo.version_constraints import resolve_version_constraint

        from kanon_cli.repo import error

        tags = [
            "refs/tags/dev/python/agent/0.1.0",
            "refs/tags/dev/python/agent/0.2.0",
        ]
        with pytest.raises(error.ManifestInvalidRevisionError):
            resolve_version_constraint("refs/tags/dev/python/agent/>=5.0.0", tags)

    def test_version_constraint_range(self):
        """Range constraints (>=X,<Y) should filter correctly."""
        from kanon_cli.repo.version_constraints import resolve_version_constraint

        tags = [
            "refs/tags/dev/python/lib/0.9.0",
            "refs/tags/dev/python/lib/1.0.0",
            "refs/tags/dev/python/lib/1.5.0",
            "refs/tags/dev/python/lib/2.0.0",
            "refs/tags/dev/python/lib/2.1.0",
        ]
        result = resolve_version_constraint("refs/tags/dev/python/lib/>=1.0.0,<2.0.0", tags)
        assert result == "refs/tags/dev/python/lib/1.5.0"


@pytest.mark.functional
class TestAbsolutePathLinkfile:
    """Functional tests for absolute path linkfile support."""

    def test_check_local_path_allows_absolute_with_abs_ok(self):
        """_CheckLocalPath should allow absolute paths when abs_ok=True."""
        from kanon_cli.repo import manifest_xml

        # Should NOT raise
        manifest_xml.XmlManifest._CheckLocalPath("/etc/myapp/config.yml", abs_ok=True)

    def test_check_local_path_rejects_traversal_even_with_abs_ok(self):
        """Path traversal should be rejected even with abs_ok=True."""
        from kanon_cli.repo import manifest_xml

        msg = manifest_xml.XmlManifest._CheckLocalPath("/etc/../secret", abs_ok=True)
        assert msg is not None, "_CheckLocalPath should reject path traversal even with abs_ok"


@pytest.mark.functional
class TestMandatorySSH:
    """Functional tests for mandatory SSH handling."""

    def test_ssh_version_callable(self):
        """ssh.version() should return a tuple or exit cleanly."""
        from kanon_cli.repo import ssh

        ssh.version.cache_clear()
        try:
            result = ssh.version()
            assert isinstance(result, tuple)
        except SystemExit:
            # Expected if ssh is not installed in test environment
            pass
        finally:
            ssh.version.cache_clear()


@pytest.mark.functional
class TestLinkFileExclude:
    """Functional tests for the linkfile exclude attribute."""

    def test_linkfile_exclude_creates_individual_symlinks(self, tmp_path):
        """End-to-end: exclude creates real dir with per-child symlinks."""
        from kanon_cli.repo import project

        worktree = tmp_path / "worktree"
        topdir = tmp_path / "checkout"
        worktree.mkdir()
        topdir.mkdir()

        # Create source directory with children.
        src_dir = worktree / "plugin"
        src_dir.mkdir()
        (src_dir / "main.py").write_text("# main")
        (src_dir / "utils.py").write_text("# utils")
        (src_dir / "tests").mkdir()
        (src_dir / "tests" / "test_main.py").write_text("# test")

        dest = str(topdir / "linked-plugin")
        lf = project._LinkFile(str(worktree), "plugin", str(topdir), dest, exclude="tests")
        lf._Link()

        dest_path = topdir / "linked-plugin"
        assert dest_path.is_dir()
        assert not dest_path.is_symlink()
        assert (dest_path / "main.py").is_symlink()
        assert (dest_path / "utils.py").is_symlink()
        assert not (dest_path / "tests").exists()

    def test_linkfile_exclude_with_absolute_dest(self, tmp_path):
        """End-to-end: exclude works with absolute dest path (spec 17.1)."""
        from kanon_cli.repo import project

        worktree = tmp_path / "worktree"
        topdir = tmp_path / "checkout"
        worktree.mkdir()
        topdir.mkdir()

        src_dir = worktree / "plugin"
        src_dir.mkdir()
        (src_dir / "main.py").write_text("# main")
        (src_dir / "docs").mkdir()

        abs_dest = str(tmp_path / "external" / "linked-plugin")
        lf = project._LinkFile(str(worktree), "plugin", str(topdir), abs_dest, exclude="docs")
        lf._Link()

        dest_path = tmp_path / "external" / "linked-plugin"
        assert dest_path.is_dir()
        assert not dest_path.is_symlink()
        assert (dest_path / "main.py").is_symlink()
        assert not (dest_path / "docs").exists()
