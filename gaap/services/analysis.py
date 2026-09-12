"""Orchestration de la lecture d'une experience.

Assemble agregats, analyse, garde-fous d'execution et recommandation en un
objet unique consomme aussi bien par l'interface que par l'API. Un seul chemin
de calcul : le tableau de bord et l'API ne peuvent pas diverger.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..domain import guardrails
from ..domain.analysis import ExperimentAnalysis, analyse
from ..domain.decision import Recommendation, recommend
from ..domain.guardrails import GuardrailReport
from ..domain.models import Experiment
from ..infrastructure.repositories import DailyPoint, ExperimentRepository, ObservationRepository

__all__ = ["ExperimentReport", "AnalysisService"]


@dataclass(frozen=True)
class ExperimentReport:
    """Vue complete et coherente d'une experience a un instant donne."""

    experiment: Experiment
    analysis: ExperimentAnalysis
    pre_launch: GuardrailReport
    runtime: GuardrailReport
    recommendation: Recommendation
    daily: tuple[DailyPoint, ...]

    def to_dict(self) -> dict:
        return {
            "experiment": self.experiment.to_dict(),
            "floor_rate": self.analysis.floor_rate,
            "floor_breakdown": self.experiment.price_floor.to_dict(),
            "srm": {
                "chi_square": round(self.analysis.srm.chi_square, 4),
                "df": self.analysis.srm.df,
                "p_value": self.analysis.srm.p_value,
                "passed": self.analysis.srm.passed,
            },
            "information_fraction": round(self.analysis.information_fraction, 4),
            "sequential_boundary": round(self.analysis.boundary, 4),
            "alpha_adjusted": round(self.analysis.alpha_adjusted, 5),
            "learning_cost": round(self.analysis.learning_cost, 2),
            "cells": [
                {
                    "key": r.cell.key,
                    "label": r.cell.label,
                    "rate": r.cell.rate,
                    "fee": r.cell.fee,
                    "effective_rate": r.effective_rate,
                    "delta_bp": r.delta_bp,
                    "is_control": r.is_control,
                    "exposed": r.exposed,
                    "conversions": r.conversions,
                    "take_up": r.take_up,
                    "take_up_ci": [r.take_up_ci[0], r.take_up_ci[1]],
                    "margin_bp": round(r.margin_bp, 1),
                    "raroc": r.raroc,
                    "contribution_per_contract": round(r.contribution_per_contract, 2),
                    "rac_per_lead": round(r.rac_per_lead, 4),
                    "p_value": r.takeup_test.p_value if r.takeup_test else None,
                    "z": round(r.takeup_test.z, 4) if r.takeup_test else None,
                    "boundary_crossed": r.boundary_crossed,
                    "prob_beats_control": r.prob_beats_control,
                    "mean_pd_converted": r.mean_pd_converted,
                    "pd_drift_bp": round(r.pd_drift_bp, 1),
                    "adverse_selection": r.adverse_selection,
                }
                for r in self.analysis.results
            ],
            "elasticity": (
                {
                    "value": self.analysis.elasticity.value,
                    "std_error": self.analysis.elasticity.std_error,
                    "ci": [self.analysis.elasticity.ci_low, self.analysis.elasticity.ci_high],
                    "r_squared": self.analysis.elasticity.r_squared,
                    "points": self.analysis.elasticity.points,
                    "method": self.analysis.elasticity.method,
                    "tested_range": list(self.analysis.elasticity.tested_range),
                    "optimal_rate": self.analysis.elasticity.optimal_rate,
                    "optimal_is_extrapolated": self.analysis.elasticity.optimal_is_extrapolated,
                }
                if self.analysis.elasticity else None
            ),
            "guardrails": {
                "pre_launch": self.pre_launch.to_dict(),
                "runtime": self.runtime.to_dict(),
            },
            "recommendation": self.recommendation.to_dict(),
            "warnings": list(self.analysis.warnings),
        }


class AnalysisService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._experiments = ExperimentRepository(conn)
        self._observations = ObservationRepository(conn)

    def report(self, key: str) -> ExperimentReport | None:
        experiment = self._experiments.get(key)
        if experiment is None:
            return None
        aggregates = self._observations.aggregates(key)
        analysis = analyse(experiment, aggregates)
        runtime_report = guardrails.runtime(analysis)
        return ExperimentReport(
            experiment=experiment,
            analysis=analysis,
            pre_launch=guardrails.pre_launch(experiment),
            runtime=runtime_report,
            recommendation=recommend(analysis, runtime_report),
            daily=tuple(self._observations.daily(key)),
        )

    def portfolio(self) -> list[ExperimentReport]:
        """Vue consolidee de toutes les experiences, pour le cockpit."""
        reports = []
        for experiment in self._experiments.list():
            report = self.report(experiment.key)
            if report is not None:
                reports.append(report)
        return reports
