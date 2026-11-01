"""Loads versioned model artifacts and scores transactions.

Inference uses the native XGBoost booster. Per-transaction explanations use
`pred_contribs=True`, which is XGBoost's exact TreeSHAP implementation (identical to
shap.TreeExplainer; ml/train.py verifies the max difference and stores it in metadata.json).
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

from core.config import get_settings
from core.features import FEATURE_COLUMNS, RAW_COLUMNS, build_features


class ModelNotAvailable(RuntimeError):
    pass


@dataclass
class ModelBundle:
    version: str
    booster: xgb.Booster
    metadata: dict
    path: Path

    @property
    def threshold(self) -> float:
        return float(self.metadata["threshold"])

    @property
    def name(self) -> str:
        return self.metadata.get("name", "XGBoost")

    @property
    def feature_names(self) -> list[str]:
        return list(self.metadata.get("feature_columns") or FEATURE_COLUMNS)

    def feature_frame(self, raw: pd.DataFrame) -> pd.DataFrame:
        src = self.metadata.get("feature_source")
        if src:      # imported legacy model: trained on the raw columns under their original names
            return pd.DataFrame({n: raw[c].astype(float) for n, c in src.items()})[self.feature_names]
        return build_features(raw[RAW_COLUMNS])

    def predict_proba(self, raw: pd.DataFrame) -> np.ndarray:
        feats = self.feature_frame(raw)
        return self.booster.predict(xgb.DMatrix(feats, feature_names=self.feature_names))

    def explain(self, raw: pd.DataFrame) -> dict:
        feats = self.feature_frame(raw)
        contribs = self.booster.predict(xgb.DMatrix(feats, feature_names=self.feature_names), pred_contribs=True)[0]
        bias, vals = float(contribs[-1]), contribs[:-1]
        logit = float(vals.sum() + bias)
        rows = [{"feature": f, "value": float(feats.iloc[0][f]), "contribution": float(c),
                 "direction": "increases_fraud_risk" if c > 0 else "decreases_fraud_risk" if c < 0 else "neutral"}
                for f, c in zip(self.feature_names, vals)]
        rows.sort(key=lambda r: -abs(r["contribution"]))
        return {"model_version": self.version, "base_value_logit": bias, "output_logit": logit,
                "probability": float(1 / (1 + np.exp(-logit))), "unit": "log-odds (TreeSHAP)",
                "contributions": rows}


class ModelStore:
    def __init__(self, models_dir: str | None = None):
        self.dir = Path(models_dir or get_settings().models_dir)
        self._bundles: dict[str, ModelBundle] = {}
        self._lock = threading.Lock()

    def registry(self) -> dict:
        p = self.dir / "registry.json"
        if not p.exists():
            raise ModelNotAvailable(f"{p} not found - run `python -m ml.train` first")
        return json.loads(p.read_text())

    def versions(self) -> list[str]:
        return [v["version"] for v in self.registry()["versions"]]

    def active_version(self) -> str:
        active = self.registry().get("active")
        if not active:
            raise ModelNotAvailable("No active model in registry.json")
        return active

    def get(self, version: str | None = None) -> ModelBundle:
        version = version or self.active_version()
        with self._lock:
            if version not in self._bundles:
                d = self.dir / "versions" / version
                if not (d / "model.json").exists():
                    raise ModelNotAvailable(f"Model version '{version}' not found")
                booster = xgb.Booster(); booster.load_model(d / "model.json")
                self._bundles[version] = ModelBundle(
                    version, booster, json.loads((d / "metadata.json").read_text()), d)
            return self._bundles[version]

    def metadata(self, version: str | None = None) -> dict:
        """Metadata only - does not load the booster (used by the producer)."""
        v = version or self.active_version()
        return json.loads((self.dir / "versions" / v / "metadata.json").read_text())

    def artifact(self, version: str, name: str):
        p = self.dir / "versions" / version / name
        if not p.exists():
            raise ModelNotAvailable(f"{name} missing for {version}")
        return json.loads(p.read_text())


_store: ModelStore | None = None


def get_store() -> ModelStore:
    global _store
    if _store is None:
        _store = ModelStore()
    return _store


def reset_store() -> None:
    global _store
    _store = None
