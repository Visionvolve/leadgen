"""Tests for phone number normalization."""

from api.services.phone_normalize import format_phone_display, normalize_phone


class TestNormalizePhone:
    """Tests for normalize_phone()."""

    def test_none_returns_none(self):
        assert normalize_phone(None) is None

    def test_empty_string_returns_none(self):
        assert normalize_phone("") is None
        assert normalize_phone("   ") is None

    def test_strip_decimal_suffix(self):
        """Float-like values from CSV imports."""
        assert normalize_phone("602123456.0") == "+420602123456"

    def test_strip_whitespace_and_dashes(self):
        assert normalize_phone("+420 602 123 456") == "+420602123456"
        assert normalize_phone("+420-602-123-456") == "+420602123456"
        assert normalize_phone("(602) 123-456") == "+420602123456"

    def test_czech_9_digit_mobile(self):
        """9-digit Czech numbers starting with 2-7 get +420 prefix."""
        assert normalize_phone("602123456") == "+420602123456"
        assert normalize_phone("773456789") == "+420773456789"
        assert normalize_phone("221234567") == "+420221234567"

    def test_czech_9_digit_non_mobile(self):
        """9-digit numbers starting outside 2-7 are not assumed Czech."""
        # 8xx and 9xx are not standard Czech patterns
        result = normalize_phone("812345678")
        assert result == "812345678"  # 9 digits, not Czech pattern

    def test_already_has_plus(self):
        """Numbers already starting with + are preserved."""
        assert normalize_phone("+420602123456") == "+420602123456"
        assert normalize_phone("+49 30 12345678") == "+493012345678"
        assert normalize_phone("+1 555 123 4567") == "+15551234567"

    def test_double_zero_prefix(self):
        """00XX international format converts to +XX."""
        assert normalize_phone("00420602123456") == "+420602123456"
        assert normalize_phone("0033 680 928 601") == "+33680928601"
        assert normalize_phone("004915112345678") == "+4915112345678"

    def test_420_without_plus(self):
        """420XXXXXXXXX gets + prepended."""
        assert normalize_phone("420602123456") == "+420602123456"

    def test_long_number_gets_plus(self):
        """10+ digit numbers without prefix get + added."""
        assert normalize_phone("493012345678") == "+493012345678"

    def test_numeric_input(self):
        """Handles numeric (int/float) input gracefully."""
        assert normalize_phone(602123456) == "+420602123456"
        assert normalize_phone(602123456.0) == "+420602123456"

    def test_dots_in_number(self):
        """Dots used as separators are stripped."""
        assert normalize_phone("602.123.456") == "+420602123456"

    def test_parentheses(self):
        assert normalize_phone("+1 (555) 123-4567") == "+15551234567"


class TestFormatPhoneDisplay:
    """Tests for format_phone_display()."""

    def test_none_returns_none(self):
        assert format_phone_display(None) is None

    def test_empty_returns_empty(self):
        assert format_phone_display("") == ""

    def test_czech_format(self):
        assert format_phone_display("+420602123456") == "+420 602 123 456"

    def test_german_format(self):
        result = format_phone_display("+493012345678")
        # Groups digits in threes after country code prefix
        assert result == "+493 012 345 678"

    def test_us_format(self):
        result = format_phone_display("+15551234567")
        assert result == "+155 512 345 67"

    def test_short_number_passthrough(self):
        """Short numbers without + are returned as-is."""
        assert format_phone_display("12345") == "12345"
