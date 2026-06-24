"""Unit tests for doctor-subcheck Finding constants and the Finding dataclass.

Covers:
- AC-FUNC-001: The six finding-prefix constants exist in kanon_cli.constants.
- AC-FUNC-002: Finding dataclass has severity, name, reason fields and a
  validator that rejects invalid severity values.

Spec reference: spec/defect-resolution-and-fixture-automation-2026-06/spec.md
Section 4 E33 (Change + Failing test), CLAUDE.md NO HARD-CODED VALUES.
"""

from __future__ import annotations

import pytest


@pytest.mark.unit
class TestFindingPrefixConstants:
    """The six finding-prefix constants are exported from kanon_cli.constants."""

    def test_finding_severity_ok_value(self) -> None:
        """FINDING_SEVERITY_OK equals the canonical string 'ok'."""
        from kanon_cli.constants import FINDING_SEVERITY_OK

        assert FINDING_SEVERITY_OK == "ok"

    def test_finding_severity_fail_value(self) -> None:
        """FINDING_SEVERITY_FAIL equals the canonical string 'fail'."""
        from kanon_cli.constants import FINDING_SEVERITY_FAIL

        assert FINDING_SEVERITY_FAIL == "fail"

    def test_finding_severity_info_value(self) -> None:
        """FINDING_SEVERITY_INFO equals the canonical string 'info'."""
        from kanon_cli.constants import FINDING_SEVERITY_INFO

        assert FINDING_SEVERITY_INFO == "info"

    def test_finding_prefix_ok_value(self) -> None:
        """FINDING_PREFIX_OK equals the canonical token '[ok]'."""
        from kanon_cli.constants import FINDING_PREFIX_OK

        assert FINDING_PREFIX_OK == "[ok]"

    def test_finding_prefix_fail_value(self) -> None:
        """FINDING_PREFIX_FAIL equals the canonical token '[fail]'."""
        from kanon_cli.constants import FINDING_PREFIX_FAIL

        assert FINDING_PREFIX_FAIL == "[fail]"

    def test_finding_prefix_info_value(self) -> None:
        """FINDING_PREFIX_INFO equals the canonical token '[info]'."""
        from kanon_cli.constants import FINDING_PREFIX_INFO

        assert FINDING_PREFIX_INFO == "[info]"


@pytest.mark.unit
class TestFindingDataclass:
    """Finding dataclass has severity/name/reason fields and severity validator."""

    def test_finding_ok_has_severity_field(self) -> None:
        """Finding with severity='ok' stores the severity on the instance."""
        from kanon_cli.commands.doctor import Finding

        f = Finding(severity="ok", name="kanon_hash consistency")
        assert f.severity == "ok"

    def test_finding_fail_has_severity_field(self) -> None:
        """Finding with severity='fail' stores the severity on the instance."""
        from kanon_cli.commands.doctor import Finding

        f = Finding(severity="fail", name="kanon_hash consistency", reason="hash mismatch")
        assert f.severity == "fail"

    def test_finding_info_has_severity_field(self) -> None:
        """Finding with severity='info' stores the severity on the instance."""
        from kanon_cli.commands.doctor import Finding

        f = Finding(severity="info", name="effective catalog source")
        assert f.severity == "info"

    def test_finding_has_name_field(self) -> None:
        """Finding stores the subcheck name verbatim."""
        from kanon_cli.commands.doctor import Finding

        f = Finding(severity="ok", name="no orphaned lock entries")
        assert f.name == "no orphaned lock entries"

    def test_finding_reason_defaults_to_none(self) -> None:
        """Finding.reason defaults to None when not supplied."""
        from kanon_cli.commands.doctor import Finding

        f = Finding(severity="ok", name="no branch drift")
        assert f.reason is None

    def test_finding_reason_stored_when_supplied(self) -> None:
        """Finding.reason stores the supplied string."""
        from kanon_cli.commands.doctor import Finding

        f = Finding(severity="fail", name="kanon_hash consistency", reason="mismatch detail")
        assert f.reason == "mismatch detail"

    def test_finding_is_frozen(self) -> None:
        """Finding is immutable -- setattr raises FrozenInstanceError (AttributeError subclass)."""
        from kanon_cli.commands.doctor import Finding

        f = Finding(severity="ok", name="kanon_hash consistency")
        with pytest.raises(AttributeError):
            setattr(f, "severity", "fail")

    @pytest.mark.parametrize("severity", ["ok", "fail", "info"])
    def test_finding_valid_severities_accepted(self, severity: str) -> None:
        """All three valid severity values are accepted without error."""
        from kanon_cli.commands.doctor import Finding

        f = Finding(severity=severity, name="check")
        assert f.severity == severity

    @pytest.mark.parametrize("bad_severity", ["error", "warn", "warning", "", "OK", "FAIL"])
    def test_finding_invalid_severity_raises_value_error(self, bad_severity: str) -> None:
        """Finding raises ValueError when severity is not one of the three valid values."""
        from kanon_cli.commands.doctor import Finding

        with pytest.raises(ValueError, match="severity"):
            Finding(severity=bad_severity, name="check")


@pytest.mark.unit
class TestDoctorImportsFindingConstants:
    """doctor.py imports the six finding-prefix constants from constants.py."""

    def test_doctor_module_exposes_finding_prefix_ok(self) -> None:
        """doctor module-level namespace contains FINDING_PREFIX_OK from constants."""
        import kanon_cli.commands.doctor as doctor_module

        assert hasattr(doctor_module, "FINDING_PREFIX_OK")

    def test_doctor_module_exposes_finding_prefix_fail(self) -> None:
        """doctor module-level namespace contains FINDING_PREFIX_FAIL from constants."""
        import kanon_cli.commands.doctor as doctor_module

        assert hasattr(doctor_module, "FINDING_PREFIX_FAIL")

    def test_doctor_module_exposes_finding_prefix_info(self) -> None:
        """doctor module-level namespace contains FINDING_PREFIX_INFO from constants."""
        import kanon_cli.commands.doctor as doctor_module

        assert hasattr(doctor_module, "FINDING_PREFIX_INFO")
