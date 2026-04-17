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

"""Unit tests for fetch.py module."""

import subprocess
from unittest import mock

import pytest

from kanon_cli.repo.fetch import fetch_file
from kanon_cli.repo.fetch import FetchFileError


@pytest.mark.unit
class TestFetchFile:
    """Tests for fetch_file function."""

    def test_fetch_file_gs_success(self):
        """Test fetch_file with gs:// URL."""
        with mock.patch("subprocess.run") as mock_run:
            mock_result = mock.Mock()
            mock_result.stdout = b"file contents"
            mock_result.stderr = b""
            mock_run.return_value = mock_result

            result = fetch_file("gs://bucket/file.txt")

            assert result == b"file contents"
            mock_run.assert_called_once()
            assert mock_run.call_args[0][0] == [
                "gsutil",
                "cat",
                "gs://bucket/file.txt",
            ]

    def test_fetch_file_gs_with_verbose(self):
        """Test fetch_file with gs:// URL and verbose mode."""
        with mock.patch("subprocess.run") as mock_run:
            mock_result = mock.Mock()
            mock_result.stdout = b"file contents"
            mock_result.stderr = b"warning message"
            mock_run.return_value = mock_result

            result = fetch_file("gs://bucket/file.txt", verbose=True)

            assert result == b"file contents"

    def test_fetch_file_gs_error(self):
        """Test fetch_file with gs:// URL error."""
        with mock.patch("subprocess.run") as mock_run:
            error = subprocess.CalledProcessError(1, "gsutil", stderr=b"error")
            mock_run.side_effect = error

            with pytest.raises(FetchFileError):
                fetch_file("gs://bucket/file.txt")

    def test_fetch_file_http_success(self):
        """Test fetch_file with HTTP URL."""
        with mock.patch("kanon_cli.repo.fetch.urlopen") as mock_urlopen:
            mock_response = mock.MagicMock()
            mock_response.read.return_value = b"http contents"
            mock_response.__enter__.return_value = mock_response
            mock_urlopen.return_value = mock_response

            result = fetch_file("https://example.com/file.txt")

            assert result == b"http contents"
            mock_urlopen.assert_called_once_with("https://example.com/file.txt")

    def test_fetch_file_https_success(self):
        """Test fetch_file with HTTPS URL."""
        with mock.patch("kanon_cli.repo.fetch.urlopen") as mock_urlopen:
            mock_response = mock.MagicMock()
            mock_response.read.return_value = b"https contents"
            mock_response.__enter__.return_value = mock_response
            mock_urlopen.return_value = mock_response

            result = fetch_file("https://secure.example.com/file.txt")

            assert result == b"https contents"

    def test_fetch_file_file_url(self):
        """Test fetch_file with file:// URL."""
        with mock.patch("kanon_cli.repo.fetch.urlopen") as mock_urlopen:
            mock_response = mock.MagicMock()
            mock_response.read.return_value = b"local file contents"
            mock_response.__enter__.return_value = mock_response
            mock_urlopen.return_value = mock_response

            result = fetch_file("file:///tmp/file.txt")

            assert result == b"local file contents"


@pytest.mark.unit
class TestFetchFileError:
    """Tests for FetchFileError exception."""

    def test_fetch_file_error_creation(self):
        """Test FetchFileError can be created."""
        error = FetchFileError("Test error")
        assert str(error) == "Test error"

    def test_fetch_file_error_with_aggregate_errors(self):
        """Test FetchFileError with aggregate errors."""
        errors = [Exception("error1"), Exception("error2")]
        error = FetchFileError("Multiple errors", aggregate_errors=errors)
        assert str(error) == "Multiple errors"
