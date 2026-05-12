import pytest

from kanon_cli.constants import TAG_ERROR_DISPLAY_CAP


@pytest.mark.unit
class TestTagErrorDisplayCap:
    def test_tag_error_display_cap_is_positive_int(self):
        assert isinstance(TAG_ERROR_DISPLAY_CAP, int)
        assert TAG_ERROR_DISPLAY_CAP > 0

    def test_tag_error_display_cap_value(self):
        assert TAG_ERROR_DISPLAY_CAP == 10
