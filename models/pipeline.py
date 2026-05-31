import logging
import warnings
import numpy as np
import pandas as pd
import sqlalchemy as sa

# LightGBM stores feature names internally; suppress the harmless sklearn
# warning that fires when predict() receives a plain numpy array.
warnings.filterwarnings(
    "ignore",
    message="X does not have valid feature names",
    category=UserWarning,
)
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from models.base import DemandModel
from models.loader import DataLoader
from models.evaluator import Evaluator


class TrainPipeline:
    """
    Orchestrates: load → split → [tune] → fit → evaluate → save → persist metrics → publish.
    Inject a different DataLoader, DemandModel, or Evaluator to swap any step.
    Set tune=True to run RandomizedSearchCV with TimeSeriesSplit before the final fit.
    """

    def __init__(
        self,
        loader: DataLoader,
        model: DemandModel,
        evaluator: Evaluator,
        engine: sa.Engine,
        models_dir: Path,
        publish_handler: Callable | None = None,
        versions_to_keep: int = 3,
        tune: bool = False,
        tune_iterations: int = 30,
    ) -> None:
        self.loader           = loader
        self.model            = model
        self.evaluator        = evaluator
        self.engine           = engine
        self.models_dir       = models_dir
        self.publish_handler  = publish_handler
        self.versions_to_keep = versions_to_keep
        self.tune             = tune
        self.tune_iterations  = tune_iterations

    def _tune(self, X: np.ndarray, y: np.ndarray) -> None:
        """Route to Optuna if available, fall back to RandomizedSearchCV."""
        if not self.model.param_grid():
            logging.info("[TrainPipeline] %s — skipping tune (no param_grid)", self.model.name)
            return
        try:
            import optuna  # noqa: F401
            self._tune_optuna(X, y)
        except ImportError:
            logging.info("[TrainPipeline] Optuna not installed — falling back to RandomizedSearchCV")
            self._tune_randomized(X, y)

    def _tune_randomized(self, X: np.ndarray, y: np.ndarray) -> None:
        from sklearn.model_selection import RandomizedSearchCV, TimeSeriesSplit

        logging.info("[TrainPipeline] %s — RandomizedSearchCV %d iters x 5-fold ...",
                     self.model.name, self.tune_iterations)

        search = RandomizedSearchCV(
            self.model.model,
            self.model.param_grid(),
            n_iter=self.tune_iterations,
            cv=TimeSeriesSplit(n_splits=5),
            scoring="neg_root_mean_squared_error",
            n_jobs=-1,
            random_state=42,
            refit=False,
        )
        search.fit(X, y)
        self.model.model.set_params(**search.best_params_)
        logging.info("[TrainPipeline] %s — best CV-RMSE=%.2f  params=%s",
                     self.model.name, -search.best_score_, search.best_params_)

    def _tune_optuna(self, X: np.ndarray, y: np.ndarray) -> None:
        import optuna
        from sklearn.model_selection import TimeSeriesSplit

        optuna.logging.set_verbosity(optuna.logging.WARNING)

        logging.info("[TrainPipeline] %s — Optuna %d trials x 5-fold TimeSeriesSplit ...",
                     self.model.name, self.tune_iterations)

        tscv = TimeSeriesSplit(n_splits=5)

        def objective(trial: optuna.Trial) -> float:
            params = self.model.optuna_space(trial)
            fold_rmses = []
            for step, (train_idx, val_idx) in enumerate(tscv.split(X)):
                fold_model = type(self.model)()
                fold_model.model.set_params(**params)
                fold_model.fit(X[train_idx], y[train_idx])
                preds = fold_model.predict(X[val_idx])
                fold_rmses.append(float(np.sqrt(np.mean((y[val_idx] - preds) ** 2))))
                # Report progress so Optuna can prune bad trials early
                trial.report(np.mean(fold_rmses), step)
                if trial.should_prune():
                    raise optuna.TrialPruned()
            return float(np.mean(fold_rmses))

        sampler = optuna.samplers.TPESampler(seed=42)
        pruner  = optuna.pruners.MedianPruner(n_startup_trials=5, n_warmup_steps=2)
        study   = optuna.create_study(direction="minimize", sampler=sampler, pruner=pruner)
        study.optimize(objective, n_trials=self.tune_iterations, show_progress_bar=False)

        best = study.best_params
        self.model.model.set_params(**best)
        logging.info("[TrainPipeline] %s — Optuna best CV-RMSE=%.2f  params=%s",
                     self.model.name, study.best_value, best)

    def _cv_evaluate(self, df: pd.DataFrame, feature_cols: list[str], target_col: str) -> tuple[float, float]:
        """5-fold TimeSeriesSplit CV using the same hyperparams as the final model."""
        from sklearn.model_selection import TimeSeriesSplit

        X = df[feature_cols].values
        y = df[target_col].values

        try:
            current_params = self.model.model.get_params()
        except AttributeError:
            current_params = {}

        fold_rmses = []
        for fold, (train_idx, val_idx) in enumerate(TimeSeriesSplit(n_splits=5).split(X), start=1):
            fold_model = type(self.model)()
            if current_params:
                try:
                    fold_model.model.set_params(**current_params)
                except Exception:
                    pass
            fold_model.fit(X[train_idx], y[train_idx])
            preds = fold_model.predict(X[val_idx])
            rmse  = float(np.sqrt(np.mean((y[val_idx] - preds) ** 2)))
            fold_rmses.append(rmse)
            logging.info("[TrainPipeline] %s  CV fold %d — val-RMSE=%.2f  (n=%d)",
                         self.model.name, fold, rmse, len(val_idx))

        return float(np.mean(fold_rmses)), float(np.std(fold_rmses))

    def run(self, feature_cols: list[str], target_col: str, split: float = 0.8) -> dict:
        df = self.loader.load(self.engine)
        df = df.dropna(subset=feature_cols + [target_col]).reset_index(drop=True)

        if len(df) < 60:
            raise RuntimeError(f"Only {len(df)} rows — run backfill first")

        split_idx = int(len(df) * split)
        train_df  = df.iloc[:split_idx]
        test_df   = df.iloc[split_idx:]

        logging.info("[TrainPipeline] %s — dataset %d rows (%s → %s), train=%d test=%d",
                     self.model.name, len(df),
                     df["gas_date"].min(), df["gas_date"].max(),
                     len(train_df), len(test_df))

        X_train = train_df[feature_cols].values
        y_train = train_df[target_col].values

        if self.tune:
            self._tune(X_train, y_train)

        self.model.fit(X_train, y_train)

        # Test-set evaluation
        result = self.evaluator.evaluate(
            self.model.name,
            test_df[target_col].values,
            self.model.predict(test_df[feature_cols].values),
        )

        # Train-set evaluation — used to diagnose overfit via the gap
        train_result = self.evaluator.evaluate(
            self.model.name, y_train, self.model.predict(X_train)
        )
        result["train_rmse_mcm"] = round(train_result["rmse_mcm"], 4)

        gap = result["rmse_mcm"] - train_result["rmse_mcm"]
        overfit_flag = "  *** possible overfit ***" if gap > result["rmse_mcm"] * 0.5 else ""
        logging.info("[TrainPipeline] %s  train-RMSE=%.2f  test-RMSE=%.2f  gap=+%.2f%s",
                     self.model.name, train_result["rmse_mcm"],
                     result["rmse_mcm"], gap, overfit_flag)

        # 5-fold TimeSeriesSplit CV — most honest generalisation estimate
        cv_rmse, cv_std = self._cv_evaluate(df, feature_cols, target_col)
        result["cv_rmse_mcm"] = round(cv_rmse, 4)
        result["cv_rmse_std"] = round(cv_std, 4)
        logging.info("[TrainPipeline] %s  CV-RMSE=%.2f ± %.2f (5-fold TimeSeriesSplit)",
                     self.model.name, cv_rmse, cv_std)

        importance = self.model.feature_importance(feature_cols)
        top = sorted(importance.items(), key=lambda x: abs(x[1]), reverse=True)
        logging.info("[TrainPipeline] %s top features: %s", self.model.name,
                     "  ".join(f"{k}={v:.3f}" for k, v in top[:4]))

        ts         = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        versioned  = self.models_dir / f"{self.model.name}_{ts}.pkl"
        canonical  = self.models_dir / f"{self.model.name}.pkl"
        self.model.save(versioned)
        self.model.save(canonical)
        logging.info("[TrainPipeline] Saved → %s  (canonical: %s)", versioned.name, canonical.name)
        self._prune_old_versions(self.model.name)

        result["trained_at"] = datetime.now(timezone.utc).isoformat()
        result["train_rows"] = len(train_df)
        result["test_rows"]  = len(test_df)
        pd.DataFrame([result]).to_sql("ModelEvaluation", self.engine, schema="dbo",
                                      if_exists="append", index=False)

        self._publish(result)
        return result

    def _prune_old_versions(self, model_name: str) -> None:
        versioned = sorted(
            self.models_dir.glob(f"{model_name}_????????T??????.pkl")
        )
        to_delete = versioned[: max(0, len(versioned) - self.versions_to_keep)]
        for path in to_delete:
            path.unlink(missing_ok=True)
            logging.info("[TrainPipeline] Pruned old version: %s", path.name)

    def _publish(self, result: dict) -> None:
        if not self.publish_handler:
            return
        try:
            self.publish_handler([result])
        except Exception as e:
            logging.warning("[TrainPipeline] Publish failed: %s", e)


class ForecastPipeline:
    """
    Orchestrates: load features → predict (all models) → persist → publish.
    Inject a different DataLoader to swap the feature source (ECMWF / Open-Meteo).
    """

    def __init__(
        self,
        loader: DataLoader,
        models: list[DemandModel],
        engine: sa.Engine,
        publish_handler: Callable | None = None,
    ) -> None:
        self.loader          = loader
        self.models          = models
        self.engine          = engine
        self.publish_handler = publish_handler

    def run(self, feature_cols: list[str]) -> list[dict]:
        features_df = self.loader.load(self.engine)
        if features_df.empty:
            logging.error("[ForecastPipeline] No features available")
            return []

        created_at = datetime.now(timezone.utc).isoformat()
        rows = []

        for _, feat_row in features_df.iterrows():
            X = feat_row[feature_cols].values.reshape(1, -1)
            for model in self.models:
                pred = float(model.predict(X)[0])
                rows.append({
                    "forecast_date":       str(feat_row["gas_date"]),
                    "model_name":          model.name,
                    "forecast_demand_mcm": round(pred, 2),
                    "hdd":                 round(float(feat_row["hdd"]), 2),
                    "avg_wind_ms":         round(float(feat_row["avg_wind_ms"]), 2),
                    "created_at":          created_at,
                })

        logging.info("[ForecastPipeline] %d-day outlook (%d models):",
                     len(features_df), len(self.models))
        for r in rows:
            logging.info("  %s  %-8s  %6.1f mcm  hdd=%.1f  wind=%.1f m/s",
                         r["forecast_date"], r["model_name"],
                         r["forecast_demand_mcm"], r["hdd"], r["avg_wind_ms"])

        self._persist(rows)
        self._publish(rows)
        return rows

    def _persist(self, rows: list[dict]) -> None:
        df        = pd.DataFrame(rows)
        inspector = sa.inspect(self.engine)
        if not inspector.has_table("GasForecast", schema="dbo"):
            df.head(0).to_sql("GasForecast", self.engine, schema="dbo",
                              if_exists="fail", index=False)
        tmp = "GasForecast_tmp"
        df.to_sql(tmp, self.engine, schema="dbo", if_exists="replace", index=False)
        with self.engine.begin() as conn:
            conn.execute(sa.text("""
                MERGE [dbo].[GasForecast] AS tgt
                USING [dbo].[GasForecast_tmp] AS src
                  ON tgt.forecast_date = src.forecast_date
                 AND tgt.model_name    = src.model_name
                WHEN MATCHED THEN
                    UPDATE SET tgt.forecast_demand_mcm = src.forecast_demand_mcm,
                               tgt.hdd                 = src.hdd,
                               tgt.avg_wind_ms         = src.avg_wind_ms,
                               tgt.created_at          = src.created_at
                WHEN NOT MATCHED THEN
                    INSERT (forecast_date, model_name, forecast_demand_mcm,
                            hdd, avg_wind_ms, created_at)
                    VALUES (src.forecast_date, src.model_name, src.forecast_demand_mcm,
                            src.hdd, src.avg_wind_ms, src.created_at);
            """))
            conn.execute(sa.text(
                "IF OBJECT_ID('[dbo].[GasForecast_tmp]') IS NOT NULL "
                "DROP TABLE [dbo].[GasForecast_tmp]"
            ))

    def _publish(self, rows: list[dict]) -> None:
        if not self.publish_handler or not rows:
            return
        try:
            self.publish_handler(rows)
        except Exception as e:
            logging.warning("[ForecastPipeline] Publish failed (forecast still written): %s", e)
