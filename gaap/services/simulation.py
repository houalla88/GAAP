"""Laboratoire : pre-mortem d'un plan tarifaire avant depense reelle.

Un test de prix consomme de la marge pendant qu'il tourne. Le lancer sans
savoir s'il est capable de conclure est la facon la plus courante de payer une
information qu'on n'obtiendra pas. Ce module repond a trois questions, avant
que le premier euro ne soit engage :

1. **Ce plan peut-il conclure ?** Probabilite de franchir la frontiere de
   decision si l'elasticite supposee est la vraie.
2. **Combien coute l'apprentissage ?** Distribution de la marge sacrifiee,
   pas seulement son esperance - c'est la queue de distribution qui se
   defend en comite, pas la moyenne.
3. **Avec quelle precision mesurera-t-on l'elasticite ?** Une elasticite
   estimee a +/- 1,2 ne permet aucune decision tarifaire ulterieure.

Le modele generateur est explicite : demande a elasticite constante
q(p) = q_ref x (p / p_ref)^e. C'est une hypothese forte (pas de courbure, pas
de seuil psychologique, pas d'effet de concurrence), assumee comme telle : elle
sert a dimensionner, pas a predire. Les resultats du laboratoire ne sont
jamais melanges aux resultats reels dans l'interface.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from ..domain.analysis import CellAggregate, analyse
from ..domain.decision import Verdict, recommend
from ..domain.guardrails import runtime
from ..domain.models import Experiment

__all__ = ["SimulationInput", "SimulationResult", "simulate"]


@dataclass(frozen=True)
class SimulationInput:
    """Hypotheses du pre-mortem. Toutes explicites, aucune valeur cachee."""

    true_elasticity: float
    baseline_take_up: float
    total_volume: int
    replications: int = 400
    seed: int = 20260912


@dataclass(frozen=True)
class SimulationResult:
    """Sortie du laboratoire."""

    verdict_counts: dict[str, int]
    replications: int
    power: float
    false_switch_rate: float
    learning_cost_mean: float
    learning_cost_p05: float
    learning_cost_p95: float
    elasticity_mean: float
    elasticity_sd: float
    elasticity_coverage: float
    true_best_cell: str
    true_best_rac: float
    per_cell_true_take_up: dict[str, float]
    assumptions: dict

    @property
    def conclusive_rate(self) -> float:
        """Part des replications aboutissant a une decision, quelle qu'elle soit."""
        decided = sum(
            n for v, n in self.verdict_counts.items()
            if v in (Verdict.SWITCH.value, Verdict.KEEP.value, Verdict.PROTECT.value)
        )
        return decided / self.replications if self.replications else 0.0


def _binomial(rng: random.Random, n: int, p: float) -> int:
    """Tirage binomial.

    Approximation normale avec correction de continuite des que n*p et n*(1-p)
    depassent 10 - regime dans lequel se trouve toujours un test tarifaire
    correctement dimensionne. En dehors, tirage exact par somme de Bernoulli,
    n etant alors petit. L'approximation est documentee ici plutot que
    dissimulee : elle affecte marginalement les queues de distribution du cout
    d'apprentissage, pas les conclusions de puissance.
    """
    if n <= 0:
        return 0
    p = min(1.0, max(0.0, p))
    if n * p >= 10 and n * (1 - p) >= 10:
        value = rng.gauss(n * p, math.sqrt(n * p * (1 - p)))
        return max(0, min(n, int(round(value))))
    return sum(1 for _ in range(n) if rng.random() < p)


def simulate(experiment: Experiment, params: SimulationInput) -> SimulationResult:
    """Rejoue le plan `replications` fois sous l'hypothese d'elasticite fournie."""
    rng = random.Random(params.seed)
    control = experiment.control
    reference_rate = control.rate
    denominator = experiment.principal * experiment.duration_factor

    def effective(cell) -> float:
        return cell.rate + (cell.fee / denominator if denominator > 0 else 0.0)

    ref_eff = effective(control)
    true_take_up = {
        cell.key: max(1e-6, min(0.999, params.baseline_take_up
                                * (effective(cell) / ref_eff) ** params.true_elasticity))
        for cell in experiment.cells
    }

    # Verite terrain : quelle cellule maximise reellement la contribution ?
    floor = experiment.price_floor.total
    true_rac = {
        cell.key: true_take_up[cell.key] * (effective(cell) - floor) * denominator
        for cell in experiment.cells
    }
    best_cell = max(true_rac, key=true_rac.get)

    total_weight = sum(c.weight for c in experiment.cells)
    verdicts: dict[str, int] = {}
    costs: list[float] = []
    elasticities: list[float] = []
    covered = 0
    switches_to_best = 0
    switches_elsewhere = 0

    for _ in range(params.replications):
        aggregates = []
        for cell in experiment.cells:
            exposed = int(round(params.total_volume * cell.weight / total_weight))
            conversions = _binomial(rng, exposed, true_take_up[cell.key])
            # La PD est simulee sans derive : le laboratoire dimensionne la
            # detection d'un effet de prix, pas celle d'une anti-selection, qui
            # demanderait un modele de selection explicite.
            pd_mean = experiment.cost.pd
            aggregates.append(CellAggregate(
                cell_key=cell.key, exposed=exposed, conversions=conversions,
                pd_sum_exposed=exposed * pd_mean,
                pd_sq_sum_exposed=exposed * pd_mean * pd_mean,
                pd_sum_converted=conversions * pd_mean,
                pd_sq_sum_converted=conversions * pd_mean * pd_mean,
            ))

        analysis = analyse(experiment, aggregates, bayesian=False)
        rec = recommend(analysis, runtime(analysis))
        verdicts[rec.verdict.value] = verdicts.get(rec.verdict.value, 0) + 1
        costs.append(analysis.learning_cost)
        if analysis.elasticity:
            elasticities.append(analysis.elasticity.value)
            if analysis.elasticity.points >= 3 and analysis.elasticity.std_error > 0:
                if analysis.elasticity.ci_low <= params.true_elasticity <= analysis.elasticity.ci_high:
                    covered += 1
        if rec.verdict is Verdict.SWITCH:
            if rec.target_cell_key == best_cell:
                switches_to_best += 1
            else:
                switches_elsewhere += 1

    reps = max(1, params.replications)
    ordered_costs = sorted(costs)

    def quantile(q: float) -> float:
        if not ordered_costs:
            return 0.0
        idx = min(len(ordered_costs) - 1, max(0, int(round(q * (len(ordered_costs) - 1)))))
        return ordered_costs[idx]

    mean_eps = sum(elasticities) / len(elasticities) if elasticities else 0.0
    var_eps = (sum((e - mean_eps) ** 2 for e in elasticities) / (len(elasticities) - 1)
               if len(elasticities) > 1 else 0.0)

    return SimulationResult(
        verdict_counts=verdicts,
        replications=reps,
        power=switches_to_best / reps,
        false_switch_rate=switches_elsewhere / reps,
        learning_cost_mean=sum(costs) / len(costs) if costs else 0.0,
        learning_cost_p05=quantile(0.05),
        learning_cost_p95=quantile(0.95),
        elasticity_mean=mean_eps,
        elasticity_sd=math.sqrt(var_eps),
        elasticity_coverage=covered / reps,
        true_best_cell=best_cell,
        true_best_rac=true_rac[best_cell],
        per_cell_true_take_up=true_take_up,
        assumptions={
            "true_elasticity": params.true_elasticity,
            "baseline_take_up": params.baseline_take_up,
            "total_volume": params.total_volume,
            "replications": params.replications,
            "seed": params.seed,
            "demand_model": "Elasticite constante q(p) = q_ref x (p / p_ref)^e",
        },
    )
