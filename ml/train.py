"""Training pipeline: compare LR / RF / XGBoost, tune, pick a threshold, explain, version.

    python -m ml.train --csv creditcard.csv

Leakage controls (documented in README):
  * exact-duplicate rows removed BEFORE splitting (the raw dataset has ~1k duplicates)
  * TEMPORAL split: first 80% by Time = train, last 20% = untouched test set
  * all model selection / tuning / threshold choice uses only the train portion
    (stratified 5-fold CV; threshold from out-of-fold predictions)
  * no resampling (class weights / scale_pos_weight instead), so nothing synthetic
    can leak across folds; scaling for LR lives inside a Pipeline (fit per fold)
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn
import xgboost as xgb
from scipy.stats import loguniform, randint, uniform
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score, confusion_matrix, f1_score,
                             precision_recall_curve, precision_score, recall_score,
                             roc_auc_score, roc_curve)
from sklearn.model_selection import RandomizedSearchCV, StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from core.features import FEATURE_COLUMNS, RAW_COLUMNS, build_features

SEED = 42
MODELS_DIR = Path(os.getenv("MODELS_DIR", "models"))
MIN_PRECISION = 0.75     # threshold policy: maximize F2 subject to precision >= this
TEST_FRACTION = 0.20


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_dataset(csv_path: str):
    df = pd.read_csv(csv_path)
    df = df.rename(columns={"Time": "transaction_time", "Amount": "amount", "Class": "actual_class",
                            **{f"V{i}": f"v{i}" for i in range(1, 29)}})
    n_raw = len(df)
    df = df.drop_duplicates().sort_values("transaction_time", kind="stable").reset_index(drop=True)
    info = {"rows_raw": int(n_raw), "duplicates_removed": int(n_raw - len(df)), "rows_used": int(len(df))}
    return df, info


def metrics_at(y, p, thr):
    pred = (p >= thr).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    return {
        "threshold": float(thr),
        "precision": float(precision_score(y, pred, zero_division=0)),
        "recall": float(recall_score(y, pred, zero_division=0)),
        "f1": float(f1_score(y, pred, zero_division=0)),
        "roc_auc": float(roc_auc_score(y, p)),
        "pr_auc": float(average_precision_score(y, p)),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }


def make_models(spw: float):
    return {
        "LogisticRegression": make_pipeline(
            StandardScaler(), LogisticRegression(max_iter=2000, class_weight="balanced", C=0.1)),
        "RandomForest": RandomForestClassifier(
            n_estimators=80, max_depth=12, min_samples_leaf=3, max_samples=0.3,
            class_weight="balanced_subsample", n_jobs=-1, random_state=SEED),
        "XGBoost": xgb.XGBClassifier(
            n_estimators=200, max_depth=5, learning_rate=0.1, subsample=0.8, colsample_bytree=0.8,
            scale_pos_weight=spw, tree_method="hist", eval_metric="aucpr", random_state=SEED, n_jobs=-1),
    }


def cv_oof(model_factory, X, y, folds=5):
    skf = StratifiedKFold(n_splits=folds, shuffle=True, random_state=SEED)
    oof = np.zeros(len(y))
    per_fold = []
    for k, (tr, va) in enumerate(skf.split(X, y), 1):
        m = model_factory()
        m.fit(X.iloc[tr], y.iloc[tr])
        p = m.predict_proba(X.iloc[va])[:, 1]
        oof[va] = p
        per_fold.append(metrics_at(y.iloc[va], p, 0.5))
        log(f"    fold {k}/{folds}: PR-AUC={per_fold[-1]['pr_auc']:.4f} recall={per_fold[-1]['recall']:.3f}")
    keys = ["precision", "recall", "f1", "roc_auc", "pr_auc"]
    summary = {k: {"mean": float(np.mean([f[k] for f in per_fold])),
                   "std": float(np.std([f[k] for f in per_fold]))} for k in keys}
    return oof, summary


def choose_threshold(y, p, min_precision=MIN_PRECISION, beta=2.0):
    prec, rec, thr = precision_recall_curve(y, p)
    prec, rec = prec[:-1], rec[:-1]
    f_beta = (1 + beta**2) * prec * rec / np.maximum(beta**2 * prec + rec, 1e-12)
    ok = prec >= min_precision
    idx_pool = np.where(ok)[0] if ok.any() else np.arange(len(thr))
    best = idx_pool[np.argmax(f_beta[idx_pool])]
    policy = (f"maximize F{beta:g} on out-of-fold train predictions subject to precision >= {min_precision}"
              + ("" if ok.any() else " (constraint unattainable; fell back to unconstrained F2)"))
    return float(thr[best]), policy


def downsample_curve(x, y, n=150):
    if len(x) <= n:
        return [[float(a), float(b)] for a, b in zip(x, y)]
    idx = np.unique(np.linspace(0, len(x) - 1, n).astype(int))
    return [[float(x[i]), float(y[i])] for i in idx]


def next_version() -> str:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    existing = [int(p.name[1:]) for p in (MODELS_DIR / "versions").glob("v*") if p.name[1:].isdigit()]
    return f"v{max(existing, default=0) + 1}"


def psi_reference(series: np.ndarray, bins=10):
    qs = np.unique(np.quantile(series, np.linspace(0, 1, bins + 1)))
    if len(qs) < 3:
        return None
    edges = qs.copy(); edges[0], edges[-1] = -np.inf, np.inf
    counts, _ = np.histogram(series, bins=edges)
    return {"edges": [None if np.isinf(e) else float(e) for e in edges],
            "expected": (counts / counts.sum()).tolist()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="creditcard.csv")
    ap.add_argument("--search-iter", type=int, default=8)
    ap.add_argument("--no-mlflow", action="store_true")
    args = ap.parse_args()
    t0 = time.time()

    df, data_info = load_dataset(args.csv)
    X_all = build_features(df[RAW_COLUMNS]); y_all = df["actual_class"].astype(int)
    split = int(len(df) * (1 - TEST_FRACTION))
    X_tr, y_tr, X_te, y_te = X_all.iloc[:split], y_all.iloc[:split], X_all.iloc[split:], y_all.iloc[split:]
    spw = float((y_tr == 0).sum() / max((y_tr == 1).sum(), 1))
    data_info.update({
        "train_rows": int(len(X_tr)), "test_rows": int(len(X_te)),
        "train_fraud": int(y_tr.sum()), "test_fraud": int(y_te.sum()),
        "split": "temporal (first 80% by Time = train, last 20% = test)",
        "train_time_max": float(df["transaction_time"].iloc[split - 1]),
        "scale_pos_weight": spw,
    })
    log(f"data: {data_info}")

    # ---- 1. model comparison (5-fold stratified CV on TRAIN only) -------------------------
    comparison = {}
    for name in ["LogisticRegression", "RandomForest", "XGBoost"]:
        log(f"CV {name}")
        _, summ = cv_oof(lambda n=name: make_models(spw)[n], X_tr, y_tr)
        comparison[name] = {"cv_5fold_at_0.5": summ}

    # ---- 2. hyperparameter search for XGBoost (PR-AUC, 3-fold on TRAIN only) ----------------
    log(f"RandomizedSearchCV XGBoost ({args.search_iter} iterations)")
    space = {"n_estimators": randint(150, 400), "max_depth": randint(3, 8),
             "learning_rate": loguniform(0.03, 0.2), "subsample": uniform(0.6, 0.4),
             "colsample_bytree": uniform(0.5, 0.5), "min_child_weight": randint(1, 8),
             "gamma": uniform(0, 2), "reg_lambda": loguniform(0.5, 10)}
    search = RandomizedSearchCV(
        xgb.XGBClassifier(scale_pos_weight=spw, tree_method="hist", eval_metric="aucpr",
                          random_state=SEED, n_jobs=-1),
        space, n_iter=args.search_iter, scoring="average_precision",
        cv=StratifiedKFold(3, shuffle=True, random_state=SEED), random_state=SEED, n_jobs=1, refit=False)
    search.fit(X_tr, y_tr)
    best_params = {k: (float(v) if isinstance(v, (np.floating,)) else int(v) if isinstance(v, np.integer) else v)
                   for k, v in search.best_params_.items()}
    log(f"best params {best_params} (CV PR-AUC {search.best_score_:.4f})")
    comparison["XGBoost_tuned"] = {"cv_search_pr_auc": float(search.best_score_), "params": best_params}

    tuned = lambda: xgb.XGBClassifier(scale_pos_weight=spw, tree_method="hist", eval_metric="aucpr",
                                      random_state=SEED, n_jobs=-1, **best_params)

    # ---- 3. OOF predictions of tuned model -> threshold --------------------------------------
    log("CV tuned XGBoost (OOF for threshold)")
    oof, tuned_summary = cv_oof(tuned, X_tr, y_tr)
    comparison["XGBoost_tuned"]["cv_5fold_at_0.5"] = tuned_summary
    threshold, policy = choose_threshold(y_tr, oof)
    log(f"threshold={threshold:.4f} ({policy})")

    # ---- 4. final fit on TRAIN, evaluate once on untouched TEST -------------------------------
    log("final fits + test evaluation")
    final = tuned(); final.fit(X_tr, y_tr)
    p_te = final.predict_proba(X_te)[:, 1]
    test_metrics = metrics_at(y_te, p_te, threshold)
    test_metrics_at_05 = metrics_at(y_te, p_te, 0.5)
    fpr, tpr, _ = roc_curve(y_te, p_te)
    pr_p, pr_r, _ = precision_recall_curve(y_te, p_te)
    for name in ["LogisticRegression", "RandomForest"]:
        m = make_models(spw)[name]; m.fit(X_tr, y_tr)
        comparison[name]["test_at_0.5"] = metrics_at(y_te, m.predict_proba(X_te)[:, 1], 0.5)
    comparison["XGBoost_tuned"]["test_at_0.5"] = test_metrics_at_05
    comparison["XGBoost"]["test_at_0.5"] = metrics_at(
        y_te, (lambda m: (m.fit(X_tr, y_tr), m.predict_proba(X_te)[:, 1])[1])(make_models(spw)["XGBoost"]), 0.5)

    # ---- 5. SHAP ---------------------------------------------------------------------------------
    log("SHAP")
    import shap
    rng = np.random.default_rng(SEED)
    fraud_idx = np.where(y_te.values == 1)[0]
    legit_idx = rng.choice(np.where(y_te.values == 0)[0], size=min(2000, int((y_te == 0).sum())), replace=False)
    sample = X_te.iloc[np.concatenate([fraud_idx, legit_idx])]
    sv = shap.TreeExplainer(final).shap_values(sample)
    booster = final.get_booster()
    contribs = booster.predict(xgb.DMatrix(sample, feature_names=FEATURE_COLUMNS), pred_contribs=True)[:, :-1]
    shap_diff = float(np.max(np.abs(np.asarray(sv) - contribs)))
    gain = booster.get_score(importance_type="total_gain")
    gain_total = sum(gain.values()) or 1.0
    importance = sorted(
        [{"feature": f, "mean_abs_shap": float(np.abs(sv[:, i]).mean()),
          "mean_shap_when_fraud_pred": float(sv[(p_te[np.concatenate([fraud_idx, legit_idx])] >= threshold), i].mean())
          if (p_te[np.concatenate([fraud_idx, legit_idx])] >= threshold).any() else None,
          "gain_share": float(gain.get(f, 0.0) / gain_total)}
         for i, f in enumerate(FEATURE_COLUMNS)], key=lambda d: -d["mean_abs_shap"])
    log(f"shap vs xgboost pred_contribs max abs diff = {shap_diff:.2e}")

    # ---- 6. drift reference (training distribution) -------------------------------------------------
    drift_feats = [d["feature"] for d in importance[:8]]
    if "log_amount" not in drift_feats:
        drift_feats.append("log_amount")
    drift_ref = {f: psi_reference(X_tr[f].values) for f in drift_feats}
    drift_ref["fraud_probability"] = psi_reference(final.predict_proba(X_tr)[:, 1])
    drift_ref = {k: v for k, v in drift_ref.items() if v}

    # ---- 7. persist + register ------------------------------------------------------------------------
    version = next_version()
    out = MODELS_DIR / "versions" / version
    out.mkdir(parents=True, exist_ok=True)
    final.save_model(out / "model.json")
    metadata = {
        "version": version, "name": "XGBoost", "algorithm": "xgboost.XGBClassifier",
        "created_at": datetime.now(timezone.utc).isoformat(), "feature_columns": FEATURE_COLUMNS,
        "threshold": threshold, "threshold_policy": policy, "hyperparameters": best_params,
        "data": data_info, "seed": SEED, "training_seconds": round(time.time() - t0, 1),
        "libraries": {"xgboost": xgb.__version__, "scikit-learn": sklearn.__version__,
                      "numpy": np.__version__, "pandas": pd.__version__},
        "shap_consistency_max_abs_diff": shap_diff,
        "dataset_disclaimer": ("Trained on the public Credit Card Fraud Detection dataset (anonymised V1-V28). "
                               "It is NOT native UPI data."),
    }
    metrics = {"test": test_metrics, "test_at_0.5": test_metrics_at_05, "comparison": comparison,
               "roc_curve": downsample_curve(fpr, tpr), "pr_curve": downsample_curve(pr_r, pr_p),
               "oof_threshold_cv": {"threshold": threshold}}
    (out / "metadata.json").write_text(json.dumps(metadata, indent=2))
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2))
    (out / "importance.json").write_text(json.dumps(importance, indent=2))
    (out / "drift_reference.json").write_text(json.dumps(drift_ref, indent=2))

    reg_path = MODELS_DIR / "registry.json"
    reg = json.loads(reg_path.read_text()) if reg_path.exists() else {"active": None, "versions": []}
    reg["versions"].append({"version": version, "created_at": metadata["created_at"], "threshold": threshold,
                            "test_pr_auc": test_metrics["pr_auc"], "test_recall": test_metrics["recall"],
                            "test_precision": test_metrics["precision"], "test_f1": test_metrics["f1"]})
    reg["active"] = version        # newest model becomes active; edit registry.json to roll back
    reg_path.write_text(json.dumps(reg, indent=2))
    log(f"saved {out}  | TEST {json.dumps({k: round(v, 4) for k, v in test_metrics.items() if isinstance(v, float)})}")

    # ---- 8. MLflow (optional; tracking must never break training) ---------------------------------------
    if not args.no_mlflow:
        try:
            from ml.mlflow_log import log_version
            log(f"logged to MLflow, run {log_version(version, str(MODELS_DIR))}")
        except Exception as exc:
            log(f"MLflow logging skipped: {exc}")
    log(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
