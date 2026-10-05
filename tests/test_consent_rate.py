"""Unit tests for scripts.consent_rate._percentile."""

import pytest

from scripts.consent_rate import _percentile


@pytest.mark.parametrize(
    ("vals", "p", "expected"),
    [
        ([0.1, 0.2, 0.3, 0.4], 50, 0.3),
        ([0.1, 0.2, 0.3, 0.4], 25, 0.2),
        ([0.1, 0.2, 0.3, 0.4], 75, 0.4),
        ([0.1, 0.2, 0.3, 0.4], 0, 0.1),
        ([0.1, 0.2, 0.3, 0.4], 100, 0.4),
        ([0.5], 50, 0.5),
        ([0.1, 0.2, 0.3, 0.4, 0.5], 50, 0.3),
    ],
)
def test_percentile(vals, p, expected):
    assert _percentile(vals, p) == expected
