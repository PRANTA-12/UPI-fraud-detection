"""Import a legacy pickled sklearn-API XGBoost model as an additional, NON-active model version.

    python -m ml.import_legacy --model fraud_model.pkl --features features.pkl

* Converts the pickle to XGBoost's portable JSON once (pickles are version-fragile and unsafe to load from
  untrusted sources - only run this on a file you created) and verifies the converted model scores identically.
* Registers it as version "legacy" (threshold 0.5, as the original API used). The active version is not changed.
* Writes NO evaluation metrics: its training split is unknown, and it scores near-perfectly on rows it appears to have
  trained on, so any metric computed on this dataset would be misleading.
"""
import argparse
import json
import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb

RAW_FOR = {"Time": "transaction_time", "Amount": "amount", **{f"V{i}": f"v{i}" for i in range(1, 29)}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="fraud_model.pkl"); ap.add_argument("--features", default="features.pkl")
    ap.add_argument("--models-dir", default=os.getenv("MODELS_DIR", "models")); ap.add_argument("--threshold", type=float, default=0.5)
    a = ap.parse_args()
    clf = joblib.load(a.model); feats = list(joblib.load(a.features))
    out = Path(a.models_dir) / "versions" / "legacy"; out.mkdir(parents=True, exist_ok=True)
    clf.get_booster().save_model(out / "model.json")
    booster = xgb.Booster(); booster.load_model(out / "model.json")
    probe = pd.DataFrame(np.random.default_rng(0).normal(0, 1, (500, len(feats))), columns=feats)
    diff = float(np.max(np.abs(clf.predict_proba(probe)[:, 1] - booster.predict(xgb.DMatrix(probe, feature_names=feats)))))
    assert diff < 1e-5, f"converted model differs from the pickle (max diff {diff})"
    params = clf.get_params()
    meta = {"version": "legacy", "name": "XGBoost", "algorithm": "xgboost.XGBClassifier (imported from pickle)", "created_at": None,
            "feature_columns": feats, "feature_source": {f: RAW_FOR[f] for f in feats}, "threshold": a.threshold,
            "threshold_policy": "fixed 0.50 (original API)", "hyperparameters": {k: params.get(k) for k in ("n_estimators", "max_depth", "learning_rate", "subsample", "colsample_bytree")},
            "conversion_check_max_abs_diff": diff,
            "note": "Original project model. Training split unknown; it appears to have been trained on the full dataset, so its scores on this data are in-sample. No evaluation metrics are shown on purpose."}
    (out / "metadata.json").write_text(json.dumps(meta, indent=2))
    reg_path = Path(a.models_dir) / "registry.json"
    reg = json.loads(reg_path.read_text()) if reg_path.exists() else {"active": None, "versions": []}
    reg["versions"] = [v for v in reg["versions"] if v["version"] != "legacy"]
    reg["versions"].insert(0, {"version": "legacy", "created_at": None, "threshold": a.threshold, "note": "imported original model (not evaluated)"})
    reg_path.write_text(json.dumps(reg, indent=2))
    print(f"imported legacy model -> {out}  (conversion max abs diff {diff:.2e}); active stays {reg['active']}")


if __name__ == "__main__":
    main()
