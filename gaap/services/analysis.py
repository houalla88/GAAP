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
            "floor_planned": self.analysis.floor_planned,
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
                    "price": r.cell.price,
                    "pack_discount": r.cell.pack_discount,
                    "effective_price": r.effective_price,
                    "delta_cents": r.delta_cents,
                    "is_control": r.is_control,
                    "presented": r.presented,
                    "sold": r.sold,
                    "sell_through": r.sell_through,
                    "sell_through_ci": [r.sell_through_ci[0], r.sell_through_ci[1]],
                    "waste_rate": round(r.waste_rate, 6),
                    "floor_observed": (round(r.floor_observed, 4)
                                       if r.floor_observed != float("inf") else None),
                    "margin_per_unit_sold": round(r.margin_per_unit_sold, 4),
                    "return_on_capital": r.return_on_capital,
                    "contribution_per_unit": round(r.contribution_per_unit, 4),
                    "p_value": r.sell_through_test.p_value if r.sell_through_test else None,
                    "z": round(r.sell_through_test.z, 4) if r.sell_through_test else None,
                    "t": round(r.contribution_test.t, 4) if r.contribution_test else None,
                    "boundary_crossed": r.boundary_crossed,
                    "prob_beats_control": r.prob_beats_control,
                    "mean_quality_sold": r.mean_quality_sold,
                    "quality_drift": round(r.quality_drift, 2),
                    "quality_selection": r.quality_selection,
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
                    "optimal_price": self.analysis.elasticity.optimal_price,
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
