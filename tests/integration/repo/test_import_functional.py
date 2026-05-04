"""E2E functional tests: all subcommand imports resolve to working instances.

These tests verify that every entry in ``all_commands`` has an ``Execute``
method (AC-TEST-001) and that the Envsubst command can process a real XML
file placed under a ``.repo/manifests/`` directory tree inside ``tmp_path``
with no git repository required (AC-TEST-002).

The parametrize data for AC-TEST-001 is loaded dynamically from the
``all_commands`` registry so the test automatically covers any new or removed
subcommands without requiring manual updates.
"""

import optparse
import pathlib

import pytest

from kanon_cli.repo.subcmds import all_commands
from kanon_cli.repo.subcmds.envsubst import Envsubst

# ---------------------------------------------------------------------------
# Parametrize data -- derived at module import time from the live registry.
# Each parameter is a (command_name, command_class) pair so that pytest
# displays a descriptive test ID for every case.
# ---------------------------------------------------------------------------
_SUBCOMMAND_PARAMS = sorted(all_commands.items(), key=lambda pair: pair[0])


@pytest.mark.parametrize("command_name,command_cls", _SUBCOMMAND_PARAMS)
@pytest.mark.integration
def test_subcommand_has_execute_method(command_name: str, command_cls: type) -> None:
    """Verify every entry in all_commands exposes an Execute method.

    The Execute method is the single mandatory interface contract for all repo
    subcommands. Verifying it is present on the class (not just the instance)
    confirms that each module was loaded and the correct class was registered.

    AC-TEST-001
    """
    assert hasattr(command_cls, "Execute"), (
        f"Subcommand {command_name!r} (class {command_cls.__qualname__!r}) "
        f"does not have an Execute method. "
        f"Ensure the class in the corresponding subcmds module defines Execute(self, opt, args)."
    )
    assert callable(command_cls.Execute), (
        f"Subcommand {command_name!r}: Execute attribute is not callable -- "
        f"expected a method, got {type(command_cls.Execute)!r}."
    )


@pytest.mark.integration
def test_envsubst_processes_real_xml(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify Envsubst substitutes environment variables in a real XML file.

    Sets up a ``.repo/manifests/`` directory tree inside ``tmp_path``,
    writes a manifest XML file containing a ``${TEST_ENVSUBST_REMOTE}``
    placeholder, then runs Envsubst.Execute from that directory and confirms:

    - The processed output file exists and contains the resolved value.
    - The original file was renamed to ``<name>.bak``.
    - No git repository is needed.

    AC-TEST-002
    """
    manifests_dir = tmp_path / ".repo" / "manifests"
    manifests_dir.mkdir(parents=True)

    xml_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="${TEST_ENVSUBST_REMOTE}" />\n'
        '  <default remote="origin" revision="main" />\n'
        "</manifest>\n"
    )
    manifest_file = manifests_dir / "default.xml"
    manifest_file.write_text(xml_content, encoding="utf-8")

    expected_remote = "https://example.com/test-org"
    monkeypatch.setenv("TEST_ENVSUBST_REMOTE", expected_remote)
    monkeypatch.chdir(tmp_path)

    opt = optparse.Values()
    cmd = Envsubst()
    cmd.Execute(opt, [])

    backup_file = pathlib.Path(str(manifest_file) + ".bak")
    assert backup_file.exists(), (
        f"Expected backup file {backup_file} to exist after Envsubst.Execute, "
        f"but it was not found. Ensure EnvSubst renames the original to <name>.bak."
    )

    processed_content = manifest_file.read_text(encoding="utf-8")
    assert expected_remote in processed_content, (
        f"Expected {expected_remote!r} to appear in the processed manifest "
        f"{manifest_file}, but it was not found. "
        f"Processed content: {processed_content!r}"
    )
    assert "${TEST_ENVSUBST_REMOTE}" not in processed_content, (
        f"Expected the placeholder ${{TEST_ENVSUBST_REMOTE}} to be replaced in "
        f"{manifest_file}, but it is still present. "
        f"Processed content: {processed_content!r}"
    )
