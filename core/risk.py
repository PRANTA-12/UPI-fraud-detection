"""Risk banding. Defaults reproduce the original README rules:
   < 0.30 Low | 0.30 - < 0.70 Medium | >= 0.70 High
Thresholds are configurable (admin only, stored in app_settings) and validated."""
from __future__ import annotations

DEFAULT_LOW_MAX = 0.30
DEFAULT_HIGH_MIN = 0.70
LEVELS = ("Low", "Medium", "High")


def risk_level(prob: float, low_max: float = DEFAULT_LOW_MAX, high_min: float = DEFAULT_HIGH_MIN) -> str:
    if prob >= high_min:
        return "High"
    if prob >= low_max:
        return "Medium"
    return "Low"


def risk_case_sql(prob_expr: str, low_max: float, high_min: float) -> tuple[str, list]:
    """SQL CASE for the *current* thresholds, so historical rows are re-banded consistently."""
    return (f"(CASE WHEN {prob_expr} >= %s THEN 'High' WHEN {prob_expr} >= %s THEN 'Medium' ELSE 'Low' END)",
            [high_min, low_max])
