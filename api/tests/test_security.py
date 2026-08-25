import pytest

from app.routers.audit import csv_safe
from app.security import validate_password_strength


@pytest.mark.parametrize(
    "password", ["short", "alllowercasebutlong1!", "ALLUPPERCASEBUTLONG1!", "NoNumberPassword!", "NoSpecialPassword1"]
)
def test_password_policy_rejects_weak_passwords(password):
    with pytest.raises(ValueError):
        validate_password_strength(password)


def test_password_policy_accepts_strong_password():
    validate_password_strength("A-Strong-Password-2026!")


@pytest.mark.parametrize("value", ["=1+1", "+SUM(A1:A2)", "-2+3", "@COMMAND"])
def test_audit_csv_neutralises_formula_cells(value):
    assert csv_safe(value).startswith("'")
