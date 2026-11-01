"""Log a saved model version (params, metrics, artifacts) to MLflow.

    python -m ml.mlflow_log v1

Tracking URI comes from MLFLOW_TRACKING_URI (default: local SQLite file ./mlflow.db).
In docker-compose the optional `mlflow` service (profile `mlops`) provides a tracking server + UI.
"""
import json
import os
import sys
from pathlib import Path


def log_version(version: str, models_dir: str | None = None) -> str:
    import mlflow
    d = Path(models_dir or os.getenv("MODELS_DIR", "models")) / "versions" / version
    meta = json.loads((d / "metadata.json").read_text())
    metrics = json.loads((d / "metrics.json").read_text())
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "sqlite:///mlflow.db"))
    mlflow.set_experiment("upi-sentinel-fraud")
    with mlflow.start_run(run_name=version) as run:
        mlflow.log_params({**meta["hyperparameters"], "threshold": meta["threshold"], "model_version": version,
                           "train_rows": meta["data"]["train_rows"], "split": meta["data"]["split"]})
        mlflow.log_metrics({f"test_{k}": v for k, v in metrics["test"].items() if isinstance(v, float)})
        for name, comp in metrics["comparison"].items():
            cv = comp.get("cv_5fold_at_0.5")
            if cv:
                mlflow.log_metric(f"cv_pr_auc_{name}", cv["pr_auc"]["mean"])
        mlflow.log_artifacts(str(d), artifact_path="model_version")
        return run.info.run_id


if __name__ == "__main__":
    print("MLflow run:", log_version(sys.argv[1]))
