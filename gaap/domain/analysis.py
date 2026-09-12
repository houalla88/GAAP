"""Lecture d'une experience tarifaire : statistique, economie, elasticite.

L'analyse est construite sur des **agregats**, jamais sur les observations
unitaires. Ce choix a trois consequences utiles :

- le moteur d'analyse ne depend d'aucun stockage et se teste sur cinq lignes ;
- le volume de donnees traverse par la couche applicative reste constant, quel
  que soit le nombre de leads exposes ;
- les agregats sont exactement ce qu'un controle ou un commissaire aux comptes
  peut recalculer a partir du datawarehouse, ce qui rend le resultat opposable.

La hierarchie des metriques est volontairement rigide :

    SRM  ->  take-up  ->  contribution ajustee du risque  ->  elasticite

Un echec SRM invalide tout ce qui suit. Un gain de take-up qui ne se traduit
pas en contribution n'est pas un gain. Une elasticite estimee hors de
l'enveloppe des prix testes n'est pas une mesure.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import stats
from .models import Experiment, PriceCell
from .pricing import contribution_per_contract, lerner_optimal_price, raroc

__all__ = ["CellAggregate", "CellResult", "Elasticity", "SrmCheck", "ExperimentAnalysis",
           "analyse", "estimate_elasticity", "sequential_series"]

def _format_p(value: float) -> str:
    """p-value lisible. "p = 0,0000" laisse croire a un zero qui n'existe pas."""
    return f"{value:.1e}" if value < 1e-4 else f"{value:.4f}"


_SRM_ALPHA = 0.001  # Convention Kohavi : seuil severe, un SRM est rare et grave.
_EPS = 1e-12


@dataclass(frozen=True)
class CellAggregate:
    """Agregat brut d'une cellule, tel que produit par la couche de stockage.

    Les sommes de carres permettent de reconstituer les variances sans relire
    les observations : c'est ce qui rend l'analyse O(nombre de cellules) et non
    O(nombre de leads).
    """

    cell_key: str
    exposed: int
    conversions: int
    pd_sum_exposed: float = 0.0
    pd_sq_sum_exposed: float = 0.0
    pd_sum_converted: float = 0.0
    pd_sq_sum_converted: float = 0.0

    @property
    def take_up(self) -> float:
        return self.conversions / self.exposed if self.exposed else 0.0

    @property
    def mean_pd_exposed(self) -> float:
        return self.pd_sum_exposed / self.exposed if self.exposed else 0.0

    @property
    def mean_pd_converted(self) -> float:
        return self.pd_sum_converted / self.conversions if self.conversions else 0.0

    @property
    def var_pd_converted(self) -> float:
        n = self.conversions
        if n < 2:
            return 0.0
        mean = self.mean_pd_converted
        return max(0.0, (self.pd_sq_sum_converted - n * mean * mean) / (n - 1))


@dataclass(frozen=True)
class CellResult:
    """Resultat consolide d'une cellule de prix."""

    cell: PriceCell
    exposed: int
    conversions: int
    take_up: float
    take_up_ci: tuple[float, float]
    effective_rate: float
    delta_bp: float
    margin_bp: float
    raroc: float
    contribution_per_contract: float
    rac_per_lead: float
    rac_total: float
    is_control: bool
    # Comparaison au controle (None pour le controle lui-meme)
    takeup_test: stats.ProportionTest | None = None
    rac_test: stats.MeanTest | None = None
    #: P(contribution de la cellule > contribution du controle). Porte sur la
    #: metrique de decision, jamais sur le seul taux de conversion.
    prob_beats_control: float | None = None
    #: Perte attendue en euros par lead expose en cas de bascule a tort.
    expected_loss: float | None = None
    mean_pd_exposed: float = 0.0
    mean_pd_converted: float = 0.0
    pd_drift_bp: float = 0.0
    adverse_selection: bool = False
    boundary_crossed: bool = False

    @property
    def rac_uplift_per_lead(self) -> float:
        return self.rac_test.difference if self.rac_test else 0.0


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
    optimal_rate: float | None = None
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
    total_exposed: int
    total_conversions: int
    information_fraction: float
    boundary: float
    alpha_adjusted: float
    floor_rate: float
    learning_cost: float
    rac_baseline_total: float
    rac_realised_total: float
    adverse_selection_alert: bool = False
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def control_result(self) -> CellResult:
        return next(r for r in self.results if r.is_control)

    @property
    def best_by_take_up(self) -> CellResult:
        return max(self.results, key=lambda r: r.take_up)

    @property
    def best_by_rac(self) -> CellResult:
        return max(self.results, key=lambda r: r.rac_per_lead)

    @property
    def metric_conflict(self) -> bool:
        """Vrai quand le meilleur prix en conversion n'est pas le meilleur en marge.

        C'est le cas le plus interessant d'un test tarifaire, et celui ou un
        outil d'A/B testing generaliste conduit a la mauvaise decision.
        """
        return self.best_by_take_up.cell.key != self.best_by_rac.cell.key


def _effective_rate(cell: PriceCell, principal: float, duration_factor: float) -> float:
    """Prix unique exprime en taux, frais de dossier inclus.

    Les frais sont amortis sur l'encours moyen x duree pour devenir comparables
    a un taux. Sans cette mise en equivalence, un test qui deplace 150 EUR de
    frais et un test qui deplace 40 bps de taux seraient illisibles l'un a cote
    de l'autre, alors qu'ils touchent la meme poche du client.
    """
    denominator = principal * duration_factor
    if denominator <= 0:
        return cell.rate
    return cell.rate + cell.fee / denominator


def _weighted_ols(xs: list[float], ys: list[float], ws: list[float]) -> tuple[float, float, float]:
    """Regression lineaire ponderee. Retourne (pente, erreur-type, R2).

    Les poids utilises en amont sont w_i = n_i * p_i / (1 - p_i), soit l'inverse
    de la variance de log(p) par la methode delta. Une cellule peu exposee ou a
    faible take-up pese donc moins dans l'estimation de l'elasticite, ce qui est
    exactement le comportement souhaite : c'est la cellule dont la mesure est la
    plus bruitee.
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
    results: list[CellResult], floor_rate: float, alpha: float = 0.05
) -> Elasticity | None:
    """Estime l'elasticite-prix a partir des cellules exposees.

    Deux regimes :

    - **>= 3 cellules** : regression log-log ponderee, avec erreur-type et R2.
      C'est le regime a viser - une elasticite sans intervalle de confiance
      n'est pas exploitable pour tarifer.
    - **2 cellules** : elasticite d'arc (formule du point milieu), sans
      incertitude estimable. Utilisable pour cadrer, pas pour decider.

    Le prix optimal derive de la regle de Lerner est borne a l'enveloppe des
    prix testes. Le drapeau `optimal_is_extrapolated` signale toute sortie de
    cette enveloppe : dans ce cas la recommandation est une hypothese de
    modele, pas un resultat de mesure, et le moteur de decision refuse de s'en
    servir seul.
    """
    usable = [r for r in results if r.exposed > 0 and r.take_up > _EPS and r.effective_rate > _EPS]
    if len(usable) < 2:
        return None

    rates = [r.effective_rate for r in usable]
    tested_range = (min(rates), max(rates))

    if len(usable) == 2:
        low, high = sorted(usable, key=lambda r: r.effective_rate)
        dp = high.effective_rate - low.effective_rate
        dq = high.take_up - low.take_up
        mid_p = (high.effective_rate + low.effective_rate) / 2.0
        mid_q = (high.take_up + low.take_up) / 2.0
        if abs(dp) < _EPS or mid_q < _EPS:
            return None
        value = (dq / mid_q) / (dp / mid_p)
        optimal = lerner_optimal_price(value, floor_rate)
        return Elasticity(
            value=value, std_error=0.0, r_squared=0.0, points=2,
            method="Elasticite d'arc (point milieu)",
            ci_low=value, ci_high=value, tested_range=tested_range,
            optimal_rate=optimal,
            optimal_is_extrapolated=optimal is not None
            and not (tested_range[0] <= optimal <= tested_range[1]),
        )

    xs = [math.log(r.effective_rate) for r in usable]
    ys = [math.log(r.take_up) for r in usable]
    ws = [r.exposed * r.take_up / max(_EPS, 1.0 - r.take_up) for r in usable]
    slope, std_error, r2 = _weighted_ols(xs, ys, ws)
    crit = stats.norm_ppf(1.0 - alpha / 2.0)
    optimal = lerner_optimal_price(slope, floor_rate)
    return Elasticity(
        value=slope,
        std_error=std_error,
        r_squared=r2,
        points=len(usable),
        method="Regression log-log ponderee",
        ci_low=slope - crit * std_error,
        ci_high=slope + crit * std_error,
        tested_range=tested_range,
        optimal_rate=optimal,
        optimal_is_extrapolated=optimal is not None
        and not (tested_range[0] <= optimal <= tested_range[1]),
    )


def analyse(experiment: Experiment, aggregates: list[CellAggregate],
            bayesian: bool = True) -> ExperimentAnalysis:
    """Produit la lecture complete d'une experience.

    Aucune decision n'est prise ici : `analyse` mesure, `decision.recommend`
    tranche. La separation est volontaire - elle permet de rejouer une
    politique de decision differente sur des mesures inchangees, ce qui est la
    seule maniere honnete de comparer deux regles d'arret.

    `bayesian=False` desactive la lecture bayesienne (probabilite de
    superiorite et perte attendue). Elle n'intervient pas dans le verdict, mais
    sa perte attendue est estimee par Monte-Carlo et domine le temps de calcul.
    Le laboratoire, qui rejoue le plan plusieurs centaines de fois, s'en passe ;
    la lecture d'une experience reelle, jamais.
    """
    by_key = {a.cell_key: a for a in aggregates}
    control_cell = experiment.control
    control_agg = by_key.get(
        control_cell.key, CellAggregate(control_cell.key, 0, 0)
    )
    floor_rate = experiment.price_floor.total
    alpha_adjusted = stats.bonferroni(experiment.alpha, experiment.comparisons)

    control_contribution = contribution_per_contract(
        _effective_rate(control_cell, experiment.principal, experiment.duration_factor),
        floor_rate, experiment.principal, experiment.duration_factor,
    )
    control_rac = control_agg.take_up * control_contribution

    total_exposed = sum(a.exposed for a in aggregates)
    target_total = experiment.min_sample_per_cell * len(experiment.cells)
    information_fraction = min(1.0, total_exposed / target_total) if target_total else 0.0
    boundary = stats.obrien_fleming_bound(max(1e-6, information_fraction), alpha_adjusted)

    results: list[CellResult] = []
    warnings: list[str] = []
    adverse_alert = False

    for cell in experiment.cells:
        agg = by_key.get(cell.key, CellAggregate(cell.key, 0, 0))
        eff_rate = _effective_rate(cell, experiment.principal, experiment.duration_factor)
        contribution = contribution_per_contract(
            eff_rate, floor_rate, experiment.principal, experiment.duration_factor
        )
        rac_per_lead = agg.take_up * contribution
        is_control = cell.key == control_cell.key

        takeup_test = rac_test = None
        prob_beats = expected_loss = None
        crossed = False
        pd_drift = 0.0
        adverse = False

        if not is_control and agg.exposed > 0 and control_agg.exposed > 0:
            takeup_test = stats.two_proportion_ztest(
                control_agg.conversions, control_agg.exposed,
                agg.conversions, agg.exposed, alpha_adjusted,
            )
            # Variance exacte de la contribution par lead : la contribution est
            # une Bernoulli multipliee par une constante connue, donc
            # Var = c^2 * p * (1 - p). Inutile de stocker les valeurs unitaires.
            var_control = control_contribution ** 2 * control_agg.take_up * (1 - control_agg.take_up)
            var_variant = contribution ** 2 * agg.take_up * (1 - agg.take_up)
            rac_test = stats.welch_ttest(
                control_rac, var_control, control_agg.exposed,
                rac_per_lead, var_variant, agg.exposed, alpha_adjusted,
            )
            if bayesian:
                # Le posterior porte sur la contribution, la metrique de
                # decision, et non sur le taux de conversion : sur un test de
                # prix les deux lectures sont regulierement opposees.
                posterior = stats.contribution_posterior(
                    control_agg.conversions, control_agg.exposed, control_contribution,
                    agg.conversions, agg.exposed, contribution,
                )
                prob_beats = posterior.probability
                expected_loss = posterior.expected_loss
            # La frontiere sequentielle s'applique a la METRIQUE DE DECISION,
            # c'est-a-dire a la contribution, pas au taux de conversion. Un
            # test tarifaire peut deplacer la marge sans deplacer la
            # conversion de maniere detectable - et inversement. Proteger du
            # peeking la statistique sur laquelle on ne decide pas n'a aucun
            # sens.
            crossed = abs(rac_test.t) >= boundary
            pd_drift = (agg.mean_pd_converted - control_agg.mean_pd_converted) * 10_000.0
            # Anti-selection : le melange de risque accepte se degrade
            # significativement alors que le prix monte. Signal specifique au
            # credit, invisible d'un test de conversion.
            if agg.conversions > 30 and control_agg.conversions > 30:
                pd_test = stats.welch_ttest(
                    control_agg.mean_pd_converted, control_agg.var_pd_converted, control_agg.conversions,
                    agg.mean_pd_converted, agg.var_pd_converted, agg.conversions, 0.05,
                )
                adverse = pd_test.significant and pd_test.difference > 0
                if adverse:
                    adverse_alert = True
                    warnings.append(
                        f"Anti-selection detectee sur {cell.label} : la PD moyenne des dossiers "
                        f"acceptes progresse de {pd_drift:+.0f} bps "
                        f"(p = {_format_p(pd_test.p_value)})."
                    )

        results.append(CellResult(
            cell=cell,
            exposed=agg.exposed,
            conversions=agg.conversions,
            take_up=agg.take_up,
            take_up_ci=stats.wilson_interval(agg.conversions, agg.exposed, alpha_adjusted),
            effective_rate=eff_rate,
            delta_bp=round(experiment.delta_bp(cell), 1),
            margin_bp=(eff_rate - floor_rate) * 10_000.0,
            raroc=raroc(eff_rate, experiment.cost),
            contribution_per_contract=contribution,
            rac_per_lead=rac_per_lead,
            rac_total=rac_per_lead * agg.exposed,
            is_control=is_control,
            takeup_test=takeup_test,
            rac_test=rac_test,
            prob_beats_control=prob_beats,
            expected_loss=expected_loss,
            mean_pd_exposed=agg.mean_pd_exposed,
            mean_pd_converted=agg.mean_pd_converted,
            pd_drift_bp=pd_drift,
            adverse_selection=adverse,
            boundary_crossed=crossed,
        ))

    srm_stat, srm_df, srm_p = stats.chi_square_goodness_of_fit(
        [by_key.get(c.key, CellAggregate(c.key, 0, 0)).exposed for c in experiment.cells],
        [c.weight for c in experiment.cells],
    )
    srm = SrmCheck(srm_stat, srm_df, srm_p)
    if not srm.passed:
        warnings.insert(0, (
            f"SRM detecte (p = {srm_p:.2e}) : l'allocation observee s'ecarte des poids "
            "declares. Les resultats ci-dessous ne doivent pas etre lus tant que la cause "
            "n'est pas identifiee."
        ))

    # Cout d'apprentissage : marge sacrifiee sur les cellules servies a un prix
    # moins rentable que le prix courant. C'est le prix reel de l'information.
    rac_realised = sum(r.rac_total for r in results)
    rac_baseline = control_rac * total_exposed
    learning_cost = rac_baseline - rac_realised

    return ExperimentAnalysis(
        experiment=experiment,
        results=tuple(results),
        srm=srm,
        elasticity=estimate_elasticity(results, floor_rate, experiment.alpha),
        total_exposed=total_exposed,
        total_conversions=sum(a.conversions for a in aggregates),
        information_fraction=information_fraction,
        boundary=boundary,
        alpha_adjusted=alpha_adjusted,
        floor_rate=floor_rate,
        learning_cost=learning_cost,
        rac_baseline_total=rac_baseline,
        rac_realised_total=rac_realised,
        adverse_selection_alert=adverse_alert,
        warnings=tuple(warnings),
    )


def sequential_series(
    experiment: Experiment, daily: list, cell_key: str
) -> list[tuple[float, float]]:
    """Trajectoire de la statistique de decision au fil du temps.

    Retourne une liste de couples (fraction d'information, |t| sur la
    contribution) pour une cellule donnee, en cumulant les observations jour
    apres jour.

    Ce calcul est deliberement leger - il ne recalcule ni les posteriors
    bayesiens ni les tests de PD, qui n'ont pas de sens en trajectoire et
    coutent cher. Ce qui est trace est exactement ce que la regle d'arret
    surveille : rien de plus, rien de moins.
    """
    control_key = experiment.control.key
    if cell_key == control_key:
        return []

    floor_rate = experiment.price_floor.total
    control_cell = experiment.control
    variant_cell = experiment.cell(cell_key)
    if variant_cell is None:
        return []

    contribution_control = contribution_per_contract(
        _effective_rate(control_cell, experiment.principal, experiment.duration_factor),
        floor_rate, experiment.principal, experiment.duration_factor,
    )
    contribution_variant = contribution_per_contract(
        _effective_rate(variant_cell, experiment.principal, experiment.duration_factor),
        floor_rate, experiment.principal, experiment.duration_factor,
    )
    target_total = experiment.min_sample_per_cell * len(experiment.cells)
    alpha_adjusted = stats.bonferroni(experiment.alpha, experiment.comparisons)

    by_day: dict[str, dict[str, tuple[int, int]]] = {}
    for point in daily:
        by_day.setdefault(point.day, {})[point.cell_key] = (point.exposed, point.conversions)

    totals: dict[str, list[int]] = {}
    grand_total = 0
    series: list[tuple[float, float]] = []
    for day in sorted(by_day):
        for key, (exposed, conversions) in by_day[day].items():
            bucket = totals.setdefault(key, [0, 0])
            bucket[0] += exposed
            bucket[1] += conversions
            grand_total += exposed
        control = totals.get(control_key)
        variant = totals.get(cell_key)
        if not control or not variant or control[0] < 30 or variant[0] < 30:
            continue
        rate_control = control[1] / control[0]
        rate_variant = variant[1] / variant[0]
        test = stats.welch_ttest(
            rate_control * contribution_control,
            contribution_control ** 2 * rate_control * (1 - rate_control), control[0],
            rate_variant * contribution_variant,
            contribution_variant ** 2 * rate_variant * (1 - rate_variant), variant[0],
            alpha_adjusted,
        )
        fraction = min(1.0, grand_total / target_total) if target_total else 0.0
        series.append((fraction, test.t))
    return series
