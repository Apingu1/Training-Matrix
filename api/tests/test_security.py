import pytest

from app.routers.audit import csv_safe
from app.security import validate_password_strength


@pytest.mark.parametrize(
    "password",
    ["Short1", "alllowercase1", "ALLUPPERCASE", "NoNumberPassword"],
)
def test_password_policy_rejects_weak_passwords(password):
    with pytest.raises(ValueError):
        validate_password_strength(password)


@pytest.mark.parametrize("password", ["Password1", "ABCDEFG1", "NoSpecialPassword1"])
def test_password_policy_accepts_valid_password(password):
    validate_password_strength(password)


@pytest.mark.parametrize("value", ["=1+1", "+SUM(A1:A2)", "-2+3", "@COMMAND"])
def test_audit_csv_neutralises_formula_cells(value):
    assert csv_safe(value).startswith("'")
