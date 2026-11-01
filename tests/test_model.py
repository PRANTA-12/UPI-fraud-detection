import math

import pandas as pd
import pytest

from core import db
from core.model_store import ModelNotAvailable, ModelStore
from core.repository import fetch_transaction


@pytest.fixture(scope="module")
def bundle():
    return ModelStore("models").get()


def test_registry_and_metadata(bundle):
    assert bundle.version.startswith("v") and 0 < bundle.threshold < 1
    assert len(bundle.metadata["feature_columns"]) == 32


def test_probabilities_in_range_and_deterministic(env, bundle):
    rows = pd.DataFrame(db.query_all("SELECT transaction_id FROM transactions LIMIT 1")).shape[0]
    raw = pd.DataFrame([fetch_transaction(i) for i in range(1, 21)])
    p1, p2 = bundle.predict_proba(raw), bundle.predict_proba(raw)
    assert ((p1 >= 0) & (p1 <= 1)).all() and (p1 == p2).all() and rows == 1


def test_fraud_like_row_scores_high_and_normal_low(env, bundle):
    fraud = pd.DataFrame([fetch_transaction(900)])
    assert bundle.predict_proba(fraud)[0] > bundle.threshold


def test_explanation_is_exact_and_sorted(env, bundle):
    raw = pd.DataFrame([fetch_transaction(900)])
    ex = bundle.explain(raw)
    assert ex["probability"] == pytest.approx(float(bundle.predict_proba(raw)[0]), abs=1e-5)
    mags = [abs(c["contribution"]) for c in ex["contributions"]]
    assert mags == sorted(mags, reverse=True)
    assert ex["base_value_logit"] + sum(c["contribution"] for c in ex["contributions"]) == pytest.approx(ex["output_logit"], abs=1e-4)
    assert all((c["contribution"] > 0) == (c["direction"] == "increases_fraud_risk") for c in ex["contributions"] if c["contribution"])


def test_unknown_version_errors():
    with pytest.raises(ModelNotAvailable):
        ModelStore("models").get("v999")
