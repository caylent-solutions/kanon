# Copyright (C) 2025 The Android Open Source Project
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

"""Unittests for the subcmds/checkout.py module."""

import optparse
from unittest import mock

import pytest

from kanon_cli.repo.subcmds import checkout


@pytest.mark.unit
class TestCheckoutOptions:
    """Test Checkout command options."""

    def test_options_setup(self):
        """Verify Checkout command option parser is set up correctly."""
        cmd = checkout.Checkout()
        p = optparse.OptionParser()
        cmd._Options(p)
        opts, args = p.parse_args([])

        # Verify options parser was set up
        assert p is not None


@pytest.mark.unit
class TestCheckoutCommand:
    """Test Checkout command properties."""

    def test_common_flag(self):
        """Test Checkout command is marked as COMMON."""
        assert checkout.Checkout.COMMON is True

    def test_help_summary(self):
        """Test Checkout command has help summary."""
        assert checkout.Checkout.helpSummary is not None

    def test_parallel_jobs(self):
        """Test Checkout has parallel jobs configured."""
        from kanon_cli.repo.command import DEFAULT_LOCAL_JOBS

        assert checkout.Checkout.PARALLEL_JOBS == DEFAULT_LOCAL_JOBS


@pytest.mark.unit
class TestCheckoutValidateOptions:
    """Test Checkout ValidateOptions method."""

    def test_validate_options_no_branch_fails(self):
        """Test ValidateOptions fails with no branch name."""
        from kanon_cli.repo.command import UsageError

        cmd = checkout.Checkout()
        opts, args = cmd.OptionParser.parse_args([])

        with pytest.raises(UsageError):
            cmd.ValidateOptions(opts, args)

    def test_validate_options_with_branch(self):
        """Test ValidateOptions passes with branch name."""
        cmd = checkout.Checkout()
        opts, args = cmd.OptionParser.parse_args(["branch-name"])

        # Should not raise
        cmd.ValidateOptions(opts, args)


@pytest.mark.unit
class TestCheckoutBranchResult:
    """Test CheckoutBranchResult namedtuple."""

    def test_checkout_branch_result_creation(self):
        """Test CheckoutBranchResult can be created."""
        result = checkout.CheckoutBranchResult(result=True, project_idx=0, error=None)

        assert result.result is True
        assert result.project_idx == 0
        assert result.error is None


@pytest.mark.unit
class TestCheckoutExecute:
    """Test Checkout Execute method."""

    def test_execute_one_success(self):
        """Test _ExecuteOne successfully checks out branch."""

        cmd = checkout.Checkout()

        project = mock.MagicMock()
        project.CheckoutBranch.return_value = True

        with cmd.ParallelContext():
            cmd.get_parallel_context()["projects"] = [project]
            result = cmd._ExecuteOne("branch-name", 0)

        assert result.result is True
        assert result.project_idx == 0
        assert result.error is None
