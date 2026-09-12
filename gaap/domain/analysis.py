"""Lecture d'une experience tarifaire : statistique, economie, elasticite.

L'analyse est construite sur des **agregats**, jamais sur les observations
unitaires. Ce choix a trois consequences utiles :

- le moteur d'analyse ne depend d'aucun stockage et se teste sur cinq lignes ;
- le volume de donnees traverse par la couche applicative reste constant, quel
  que soit le nombre de kilos presentes ;
- les agregats sont exactement ce qu'un controle de gestion peut recalculer a
  partir des remontees de caisse et d'inventaire, ce qui rend le resultat
  opposable.

La hierarchie des metriques est volontairement rigide :

    SRM  ->  ecoulement  ->  contribution par kilo presente  ->  elasticite

Un echec SRM invalide tout ce qui suit. Un gain d'ecoulement qui ne se traduit
pas en contribution n'est pas un gain. Une elasticite estimee hors de
l'enveloppe des prix testes n'est pas une mesure.

**Specificite du perissable.** Le plancher de rentabilite est recalcule au taux
d'ecoulement **observe** de chaque cellule, et non au taux declare dans le plan.
Comparer une cellule chere, qui tourne lentement et casse davantage, a un
plancher calcule sur la rotation du controle la flatterait mecaniquement.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import stats
from .models import Experiment, PriceCell
from .pricing import lerner_optimal_price, return_on_working_capital

__all__ = ["CellAggregate", "CellResult", "Elasticity", "SrmCheck", "ExperimentAnalysis",
           "analyse", "estimate_elasticity", "sequential_series"]

_SRM_ALPHA = 0.001  # Convention Kohavi : seuil severe, un SRM est rare et grave.
_EPS = 1e-12


def _format_p(value: float) -> str:
    """p-value lisible. "p = 0,0000" laisse croire a un zero qui n'existe pas."""
    return f"{value:.1e}" if value < 1e-4 else f"{value:.4f}"


@dataclass(frozen=True)
class CellAggregate:
    """Agregat brut d'une cellule, tel que produit par la couche de stockage.

    `presented` est le nombre de kilos mis en rayon, `sold` le nombre de kilos
    ecoules. Les sommes de carres de l'indice de fraîcheur permettent de
    reconstituer les variances sans relire les observations : c'est ce qui rend
    l'analyse O(nombre de cellules) et non O(nombre de kilos).
    """

    cell_key: str
    presented: int
    sold: int
    quality_sum_presented: float = 0.0
    quality_sq_sum_presented: float = 0.0
    quality_sum_sold: float = 0.0
    quality_sq_sum_sold: float = 0.0

    @property
    def sell_through(self) -> float:
        return self.sold / self.presented if self.presented else 0.0

    @property
    def mean_quality_presented(self) -> float:
        return self.quality_sum_presented / self.presented if self.presented else 0.0

    @property
    def mean_quality_sold(self) -> float:
        return self.quality_sum_sold / self.sold if self.sold else 0.0

    @property
    def var_quality_sold(self) -> float:
        n = self.sold
        if n < 2:
            return 0.0
        mean = self.mean_quality_sold
        return max(0.0, (self.quality_sq_sum_sold - n * mean * mean) / (n - 1))


@dataclass(frozen=True)
class CellResult:
    """Resultat consolide d'une cellule de prix."""

    cell: PriceCell
    presented: int
    sold: int
    sell_through: float
    sell_through_ci: tuple[float, float]
    effective_price: float
    delta_cents: float
    floor_observed: float
    margin_per_unit_sold: float
    value_of_sale: float
    contribution_per_unit: float
    contribution_total: float
    return_on_capital: float
    is_control: bool
    # Comparaison au controle (None pour le controle lui-meme)
    sell_through_test: stats.ProportionTest | None = None
    contribution_test: stats.MeanTest | None = None
    prob_beats_control: float | None = None
    expected_loss: float | None = None
    mean_quality_sold: float = 0.0
    quality_drift: float = 0.0
    quality_selection: bool = False
    boundary_crossed: bool = False

    @property
    def waste_rate(self) -> float:
        """Part des kilos presentes partie a la casse."""
        return 1.0 - self.sell_through


@dataclass(frozen=True)
class Elasticity:
    """Elasticite-prix de la demande estimee sur les cellules du test."""

    value: float
    std_error: float
    r_squared: float
    points: int
    method: str
    ci_low: float
    ci_high: float
    tested_range: tuple[float, float]
    optimal_price: float | None = None
    optimal_is_extrapolated: bool = False

    @property
    def is_elastic(self) -> bool:
        """|e| > 1 : une baisse de prix augmente le chiffre d'affaires."""
        return self.value < -1.0

    @property
    def lerner_index(self) -> float | None:
        """Taux de marge optimal theorique : (p* - c) / p* = -1/e."""
        return -1.0 / self.value if self.value < -_EPS else None


@dataclass(frozen=True)
class SrmCheck:
    """Controle d'adequation de l'allocation observee aux poids theoriques."""

    chi_square: float
    df: int
    p_value: float

    @property
    def passed(self) -> bool:
        return self.p_value >= _SRM_ALPHA or self.df == 0


@dataclass(frozen=True)
class ExperimentAnalysis:
    """Lecture complete d'une experience a un instant donne."""

    experiment: Experiment
    results: tuple[CellResult, ...]
    srm: SrmCheck
    elasticity: Elasticity | None
    total_presented: int
    total_sold: int
    information_fraction: float
    boundary: float
    alpha_adjusted: float
    floor_planned: float
    learning_cost: float
    contribution_baseline: float
    contribution_realised: float
    quality_selection_alert: bool = False
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def control_result(self) -> CellResult:
        return next(r for r in self.results if r.is_control)

    @property
    def best_by_sell_through(self) -> CellResult:
        return max(self.results, key=lambda r: r.sell_through)

    @property
    def best_by_contribution(self) -> CellResult:
        return max(self.results, key=lambda r: r.contribution_per_unit)

    @property
    def metric_conflict(self) -> bool:
        """Vrai quand le prix qui ecoule le mieux n'est pas le plus rentable.

        C'est le cas le plus interessant d'un test tarifaire, et celui ou un
        outil d'A/B testing generaliste conduit a la mauvaise decision.
        """
        return self.best_by_sell_through.cell.key != self.best_by_contribution.cell.key


def _weighted_ols(xs: list[float], ys: list[float], ws: list[float]) -> tuple[float, float, float]:
    """Regression lineaire ponderee. Retourne (pente, erreur-type, R2).

    Les poids utilises en amont sont w_i = n_i * s_i / (1 - s_i), soit l'inverse
    de la variance de log(s) par la methode delta. Une cellule peu exposee ou a
    faible ecoulement pese donc moins dans l'estimation de l'elasticite, ce qui
    est exactement le comportement souhaite : c'est la cellule dont la mesure est
    la plus bruitee.
    """
    total_w = sum(ws)
    if total_w <= 0 or len(xs) < 2:
        return (0.0, 0.0, 0.0)
    mean_x = sum(w * x for w, x in zip(ws, xs)) / total_w
    mean_y = sum(w * y for w, y in zip(ws, ys)) / total_w
    sxx = sum(w * (x - mean_x) ** 2 for w, x in zip(ws, xs))
    sxy = sum(w * (x - mean_x) * (y - mean_y) for w, x, y in zip(ws, xs, ys))
    if sxx <= _EPS:
        return (0.0, 0.0, 0.0)
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    rss = sum(w * (y - intercept - slope * x) ** 2 for w, x, y in zip(ws, xs, ys))
    tss = sum(w * (y - mean_y) ** 2 for w, y in zip(ws, ys))
    dof = len(xs) - 2
    sigma2 = rss / dof if dof > 0 else 0.0
    std_error = math.sqrt(sigma2 / sxx) if sigma2 > 0 else 0.0
    r_squared = 1.0 - rss / tss if tss > _EPS else 1.0
    return (slope, std_error, max(0.0, min(1.0, r_squared)))


def estimate_elasticity(
    results: list[CellResult], floor_price: float, alpha: float = 0.05
) -> Elasticity | None:
    """Estime l'elasticite-prix a partir des cellules exposees.

    Deux regimes :

    - **>= 3 cellules** : regression log-log ponderee, avec erreur-type et R2.
      C'est le regime a viser, une elasticite sans intervalle de confiance
      n'etant pas exploitable pour tarifer.
    - **2 cellules** : elasticite d'arc (formule du point milieu), sans
      incertitude estimable. Utilisable pour cadrer, pas pour decider.

    Le prix optimal derive de la regle de Lerner est borne a l'enveloppe des prix
    testes. Le drapeau `optimal_is_extrapolated` signale toute sortie de cette
    enveloppe : dans ce cas la recommandation est une hypothese de modele, pas un
    resultat de mesure, et le moteur de decision refuse de s'en servir seul.
    """
    usable = [r for r in results
              if r.presented > 0 and r.sell_through > _EPS and r.effective_price > _EPS]
    if len(usable) < 2:
        return None

    prices = [r.effective_price for r in usable]
    tested_range = (min(prices), max(prices))

    if len(usable) == 2:
        low, high = sorted(usable, key=lambda r: r.effective_price)
        dp = high.effective_price - low.effective_price
        dq = high.sell_through - low.sell_through
        mid_p = (high.effective_price + low.effective_price) / 2.0
        mid_q = (high.sell_through + low.sell_through) / 2.0
        if abs(dp) < _EPS or mid_q < _EPS:
            return None
        value = (dq / mid_q) / (dp / mid_p)
        optimal = lerner_optimal_price(value, floor_price)
        return Elasticity(
            value=value, std_error=0.0, r_squared=0.0, points=2,
            method="Elasticite d'arc (point milieu)",
            ci_low=value, ci_high=value, tested_range=tested_range,
            optimal_price=optimal,
            optimal_is_extrapolated=optimal is not None
            and not (tested_range[0] <= optimal <= tested_range[1]),
        )

    xs = [math.log(r.effective_price) for r in usable]
    ys = [math.log(r.sell_through) for r in usable]
    ws = [r.presented * r.sell_through / max(_EPS, 1.0 - r.sell_through) for r in usable]
    slope, std_error, r2 = _weighted_ols(xs, ys, ws)
    crit = stats.norm_ppf(1.0 - alpha / 2.0)
    optimal = lerner_optimal_price(slope, floor_price)
    return Elasticity(
        value=slope,
        std_error=std_error,
        r_squared=r2,
        points=len(usable),
        method="Regression log-log ponderee",
        ci_low=slope - crit * std_error,
        ci_high=slope + crit * std_error,
        tested_range=tested_range,
        optimal_price=optimal,
        optimal_is_extrapolated=optimal is not None
        and not (tested_range[0] <= optimal <= tested_range[1]),
    )


def analyse(experiment: Experiment, aggregates: list[CellAggregate],
            bayesian: bool = True) -> ExperimentAnalysis:
    """Produit la lecture complete d'une experience.

    Aucune decision n'est prise ici : `analyse` mesure, `decision.recommend`
    tranche. La separation est volontaire, elle permet de rejouer une politique
    de decision differente sur des mesures inchangees, ce qui est la seule
    maniere honnete de comparer deux regles d'arret.

    `bayesian=False` desactive la lecture bayesienne, dont la perte attendue est
    estimee par Monte-Carlo et domine le temps de calcul. Le laboratoire, qui
    rejoue le plan plusieurs centaines de fois, s'en passe ; la lecture d'une
    experience reelle, jamais.

    **Decomposition exacte de la contribution.** Un kilo presente rapporte
    `prix - sauvetage - immobilisation` s'il se vend, et coute
    `acquisition - sauvetage` s'il casse. La contribution par kilo presente vaut
    donc `s x V + K`, avec `V` la valeur d'une vente et `K` la perte seche d'un
    invendu, et sa variance vaut exactement `s (1 - s) V^2`. Aucune observation
    unitaire n'a besoin d'etre relue.
    """
    by_key = {a.cell_key: a for a in aggregates}
    control_cell = experiment.control
    control_agg = by_key.get(control_cell.key, CellAggregate(control_cell.key, 0, 0))
    cost = experiment.cost
    floor_planned = experiment.price_floor.total
    alpha_adjusted = stats.bonferroni(experiment.alpha, experiment.comparisons)
    dead_loss = cost.salvage_value - cost.acquisition_cost   # K, identique a toutes les cellules

    def value_of_sale(cell: PriceCell) -> float:
        """V : ce que rapporte de vendre un kilo plutot que de le casser."""
        return cell.effective_price - cost.salvage_value - cost.capital_cost

    control_value = value_of_sale(control_cell)
    control_contribution = control_agg.sell_through * control_value + dead_loss

    total_presented = sum(a.presented for a in aggregates)
    target_total = experiment.min_sample_per_cell * len(experiment.cells)
    information_fraction = min(1.0, total_presented / target_total) if target_total else 0.0
    boundary = stats.obrien_fleming_bound(max(1e-6, information_fraction), alpha_adjusted)

    results: list[CellResult] = []
    warnings: list[str] = []
    selection_alert = False

    for cell in experiment.cells:
        agg = by_key.get(cell.key, CellAggregate(cell.key, 0, 0))
        rate = agg.sell_through
        value = value_of_sale(cell)
        contribution = rate * value + dead_loss
        # Plancher recalcule a la rotation observee : une cellule qui tourne
        # lentement casse davantage et supporte donc un plancher plus haut.
        floor_observed = (experiment.floor_at(rate).total if rate > _EPS else float("inf"))
        is_control = cell.key == control_cell.key

        sell_test = contribution_test = None
        prob_beats = expected_loss = None
        crossed = False
        drift = 0.0
        selection = False

        if not is_control and agg.presented > 0 and control_agg.presented > 0:
            sell_test = stats.two_proportion_ztest(
                control_agg.sold, control_agg.presented,
                agg.sold, agg.presented, alpha_adjusted,
            )
            var_control = control_value ** 2 * control_agg.sell_through * (1 - control_agg.sell_through)
            var_variant = value ** 2 * rate * (1 - rate)
            contribution_test = stats.welch_ttest(
                control_contribution, var_control, control_agg.presented,
                contribution, var_variant, agg.presented, alpha_adjusted,
            )
            if bayesian:
                posterior = stats.contribution_posterior(
                    control_agg.sold, control_agg.presented, control_value,
                    agg.sold, agg.presented, value,
                )
                prob_beats = posterior.probability
                expected_loss = posterior.expected_loss
            crossed = abs(contribution_test.t) >= boundary
            drift = (agg.mean_quality_sold - control_agg.mean_quality_sold) * 100.0
            # Selection par la qualite : quand le prix monte, le client devient
            # plus exigeant et prend les meilleurs articles. Le stock residuel
            # se degrade, donc la casse s'aggrave au-dela de ce que le seul
            # ralentissement de rotation explique. Signal propre au perissable,
            # invisible d'un test d'ecoulement.
            if agg.sold > 30 and control_agg.sold > 30:
                quality_test = stats.welch_ttest(
                    control_agg.mean_quality_sold, control_agg.var_quality_sold, control_agg.sold,
                    agg.mean_quality_sold, agg.var_quality_sold, agg.sold, 0.05,
                )
                selection = quality_test.significant and quality_test.difference > 0
                if selection:
                    selection_alert = True
                    warnings.append(
                        f"Selection par la qualite detectee sur {cell.label} : l'indice de "
                        f"fraîcheur des kilos vendus progresse de {drift:+.1f} points "
                        f"(p = {_format_p(quality_test.p_value)}). Le stock residuel se degrade "
                        "plus vite que ne l'explique le seul ralentissement de rotation."
                    )

        results.append(CellResult(
            cell=cell,
            presented=agg.presented,
            sold=agg.sold,
            sell_through=rate,
            sell_through_ci=stats.wilson_interval(agg.sold, agg.presented, alpha_adjusted),
            effective_price=cell.effective_price,
            delta_cents=round(experiment.delta_cents(cell), 1),
            floor_observed=floor_observed,
            margin_per_unit_sold=(cell.effective_price - floor_observed
                                  if math.isfinite(floor_observed) else 0.0),
            value_of_sale=value,
            contribution_per_unit=contribution,
            contribution_total=contribution * agg.presented,
            return_on_capital=(return_on_working_capital(cell.effective_price, cost, rate)
                               if rate > _EPS else 0.0),
            is_control=is_control,
            sell_through_test=sell_test,
            contribution_test=contribution_test,
            prob_beats_control=prob_beats,
            expected_loss=expected_loss,
            mean_quality_sold=agg.mean_quality_sold,
            quality_drift=drift,
            quality_selection=selection,
            boundary_crossed=crossed,
        ))

    srm_stat, srm_df, srm_p = stats.chi_square_goodness_of_fit(
        [by_key.get(c.key, CellAggregate(c.key, 0, 0)).presented for c in experiment.cells],
        [c.weight for c in experiment.cells],
    )
    srm = SrmCheck(srm_stat, srm_df, srm_p)
    if not srm.passed:
        warnings.insert(0, (
            f"SRM detecte (p = {_format_p(srm_p)}) : l'allocation observee s'ecarte des poids "
            "declares. Les resultats ci-dessous ne doivent pas etre lus tant que la cause n'est "
            "pas identifiee."
        ))

    # Cout d'apprentissage : marge sacrifiee sur les cellules servies a un prix
    # moins rentable que le prix courant. C'est le prix reel de l'information.
    contribution_realised = sum(r.contribution_total for r in results)
    contribution_baseline = control_contribution * total_presented

    return ExperimentAnalysis(
        experiment=experiment,
        results=tuple(results),
        srm=srm,
        elasticity=estimate_elasticity(results, floor_planned, experiment.alpha),
        total_presented=total_presented,
        total_sold=sum(a.sold for a in aggregates),
        information_fraction=information_fraction,
        boundary=boundary,
        alpha_adjusted=alpha_adjusted,
        floor_planned=floor_planned,
        learning_cost=contribution_baseline - contribution_realised,
        contribution_baseline=contribution_baseline,
        contribution_realised=contribution_realised,
        quality_selection_alert=selection_alert,
        warnings=tuple(warnings),
    )


def sequential_series(
    experiment: Experiment, daily: list, cell_key: str
) -> list[tuple[float, float]]:
    """Trajectoire de la statistique de decision au fil du temps.

    Retourne une liste de couples (fraction d'information, t sur la
    contribution) pour une cellule donnee, en cumulant les observations jour
    apres jour.

    Ce calcul est deliberement leger : il ne recalcule ni les posteriors
    bayesiens ni les tests de qualite, qui n'ont pas de sens en trajectoire et
    coutent cher. Ce qui est trace est exactement ce que la regle d'arret
    surveille, rien de plus.
    """
    control_key = experiment.control.key
    if cell_key == control_key:
        return []

    variant_cell = experiment.cell(cell_key)
    if variant_cell is None:
        return []

    cost = experiment.cost
    dead_loss = cost.salvage_value - cost.acquisition_cost
    control_value = experiment.control.effective_price - cost.salvage_value - cost.capital_cost
    variant_value = variant_cell.effective_price - cost.salvage_value - cost.capital_cost
    target_total = experiment.min_sample_per_cell * len(experiment.cells)
    alpha_adjusted = stats.bonferroni(experiment.alpha, experiment.comparisons)

    by_day: dict[str, dict[str, tuple[int, int]]] = {}
    for point in daily:
        by_day.setdefault(point.day, {})[point.cell_key] = (point.presented, point.sold)

    totals: dict[str, list[int]] = {}
    grand_total = 0
    series: list[tuple[float, float]] = []
    for day in sorted(by_day):
        for key, (presented, sold) in by_day[day].items():
            bucket = totals.setdefault(key, [0, 0])
            bucket[0] += presented
            bucket[1] += sold
            grand_total += presented
        control = totals.get(control_key)
        variant = totals.get(cell_key)
        if not control or not variant or control[0] < 30 or variant[0] < 30:
            continue
        rate_control = control[1] / control[0]
        rate_variant = variant[1] / variant[0]
        test = stats.welch_ttest(
            rate_control * control_value + dead_loss,
            control_value ** 2 * rate_control * (1 - rate_control), control[0],
            rate_variant * variant_value + dead_loss,
            variant_value ** 2 * rate_variant * (1 - rate_variant), variant[0],
            alpha_adjusted,
        )
        fraction = min(1.0, grand_total / target_total) if target_total else 0.0
        series.append((fraction, test.t))
    return series
