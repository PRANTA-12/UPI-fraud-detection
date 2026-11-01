import math

import pandas as pd
import pytest
from pydantic import ValidationError

from core.features import FEATURE_COLUMNS, RAW_COLUMNS, build_features
from core.platform_settings import PlatformSettings
from core.risk import risk_case_sql, risk_level


def _raw(**over):
    row = {"transaction_time": 7200.0, "amount": 25.0, **{f"v{i}": 0.1 * i for i in range(1, 29)}}
    row.update(over)
    return pd.DataFrame([row])


def test_feature_columns_contract():
    f = build_features(_raw())
    assert list(f.columns) == FEATURE_COLUMNS and len(f) == 1


def test_engineered_features():
    f = build_features(_raw(amount=100.0, transaction_time=3 * 3600))
    assert f["log_amount"][0] == pytest.approx(math.log1p(100.0))
    assert f["is_round_amount"][0] == 1.0
    assert f["hour_sin"][0] == pytest.approx(math.sin(2 * math.pi * 3 / 24))
    assert build_features(_raw(amount=12.5))["is_round_amount"][0] == 0.0
    assert build_features(_raw(amount=0.0))["is_round_amount"][0] == 0.0


def test_missing_columns_rejected():
    with pytest.raises(ValueError):
        build_features(_raw().drop(columns=["v5"]))


def test_batch_equals_single():
    a = pd.concat([_raw(amount=5), _raw(amount=900)], ignore_index=True)
    b = build_features(a)
    assert b.iloc[1].equals(build_features(_raw(amount=900)).iloc[0])


@pytest.mark.parametrize("p,expected", [(0.0, "Low"), (0.2999, "Low"), (0.30, "Medium"), (0.6999, "Medium"), (0.70, "High"), (1.0, "High")])
def test_risk_bands_match_original_rules(p, expected):
    assert risk_level(p) == expected


def test_risk_sql_uses_parameters():
    sql, params = risk_case_sql("p", 0.3, 0.7)
    assert "%s" in sql and params == [0.7, 0.3] and "0.3" not in sql


def test_settings_validation():
    with pytest.raises(ValidationError):
        PlatformSettings(risk_low_max=0.8, risk_high_min=0.5)
    with pytest.raises(ValidationError):
        PlatformSettings(refresh_seconds=1)
    assert PlatformSettings().risk_low_max == 0.30


def test_config_validation(monkeypatch):
    from core.config import Settings
    with pytest.raises(ValueError):
        Settings(app_env="production", jwt_secret="short")
    with pytest.raises(ValueError):
        Settings(app_env="production", jwt_secret="x" * 40, auth_required=False)
    with pytest.raises(ValueError):
        Settings(app_env="test", producer_min_delay_ms=900, producer_max_delay_ms=100)
    assert "secret" not in Settings(app_env="test", db_password="p@ss/word").dsn.replace("p%40ss%2Fword", "")


def test_password_and_jwt_roundtrip():
    from core.security import create_token, decode_token, hash_password, verify_password
    h = hash_password("correct horse")
    assert h != "correct horse" and verify_password("correct horse", h) and not verify_password("wrong", h)
    tok, _ = create_token("alice", "analyst")
    assert decode_token(tok)["role"] == "analyst"
