"""Shared feature engineering.

The SAME function is used by training (ml/train.py), the API (/predict) and the
streaming consumer, so there is no training/serving skew.

Raw input contract (works for any transaction source, not just the replay):
    transaction_time (float, seconds), amount (float), v1..v28 (float)

NOTE ON `hour_sin/hour_cos`: the Kaggle dataset's `Time` is seconds elapsed since the
first transaction, NOT a wall-clock time. The "hour" is therefore hours-since-start
modulo 24 - a cyclic position in the 2-day capture window. When native UPI data with
real timestamps is integrated, replace this with the real hour of day.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

V_COLUMNS = [f"v{i}" for i in range(1, 29)]
RAW_COLUMNS = ["transaction_time", "amount", *V_COLUMNS]
ENGINEERED_COLUMNS = ["log_amount", "is_round_amount", "hour_sin", "hour_cos"]
FEATURE_COLUMNS = [*V_COLUMNS, *ENGINEERED_COLUMNS]


def hour_of_cycle(transaction_time: pd.Series) -> pd.Series:
    return (transaction_time.astype(float) // 3600) % 24


def build_features(raw: pd.DataFrame) -> pd.DataFrame:
    """raw must contain RAW_COLUMNS. Returns a frame with exactly FEATURE_COLUMNS."""
    missing = [c for c in RAW_COLUMNS if c not in raw.columns]
    if missing:
        raise ValueError(f"Missing raw columns: {missing}")
    amount = raw["amount"].astype(float).clip(lower=0)
    hour = hour_of_cycle(raw["transaction_time"])
    out = raw[V_COLUMNS].astype(float).copy()
    out["log_amount"] = np.log1p(amount)
    out["is_round_amount"] = ((amount > 0) & (amount % 1 == 0)).astype(float)
    out["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    out["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    return out[FEATURE_COLUMNS]


def records_to_frame(records: list[dict]) -> pd.DataFrame:
    return pd.DataFrame.from_records(records)[RAW_COLUMNS]
