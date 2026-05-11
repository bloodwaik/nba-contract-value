"""Market-rate regression model.

Trains on historical free-agent signings: given a player's prior-season
stats, what fraction of the cap did the open market actually pay them?
The fitted model is then applied to current rosters to ask "what *would*
this player command on the open market today?" — and the difference
between that and their actual cap hit is surplus value.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import KFold, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .features import ALL_FEATURES, TARGET, build_feature_matrix


@dataclass
class TrainedModel:
    pipeline: Pipeline
    coefficients: pd.Series
    in_sample_r2: float
    in_sample_mae: float
    cv_mae: float

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        X = build_feature_matrix(df)
        preds = self.pipeline.predict(X)
        # Cap predictions to the league's structural floor/ceiling.
        # Veteran minimum sits ~1% of the cap; super-max tops out ~35%.
        return np.clip(preds, 0.01, 0.35)


def train_market_rate_model(signings: pd.DataFrame, alpha: float = 1.0) -> TrainedModel:
    """Fit a Ridge regression from prior-season stats -> cap_pct at signing.

    Ridge is used over plain OLS because BPM, DWS, VORP, TS%, USG% are
    correlated — Ridge stabilises the coefficients without changing the
    interpretation. Set alpha=0 to recover OLS.
    """
    X = build_feature_matrix(signings)
    if TARGET not in signings.columns:
        raise ValueError(f"Training data must include `{TARGET}`")
    y = signings[TARGET].astype(float)

    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("ridge", Ridge(alpha=alpha, random_state=0)),
    ])
    pipeline.fit(X, y)

    preds = pipeline.predict(X)
    in_r2 = r2_score(y, preds)
    in_mae = mean_absolute_error(y, preds)

    # 5-fold CV for an honest generalisation estimate. neg-MAE → MAE.
    cv_scores = cross_val_score(
        pipeline, X, y, cv=KFold(n_splits=5, shuffle=True, random_state=0),
        scoring="neg_mean_absolute_error",
    )
    cv_mae = -cv_scores.mean()

    # Coefficients are on standardised features, so they're directly
    # comparable as "marginal cap-percent per 1-sd of this stat."
    ridge: Ridge = pipeline.named_steps["ridge"]
    coefs = pd.Series(ridge.coef_, index=ALL_FEATURES, name="coef_per_sd")

    return TrainedModel(
        pipeline=pipeline,
        coefficients=coefs.sort_values(ascending=False),
        in_sample_r2=in_r2,
        in_sample_mae=in_mae,
        cv_mae=cv_mae,
    )
