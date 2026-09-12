"""Garde-fous : ce que GAAP refuse de laisser passer.

Un test visuel rate se rattrape par un retour arriere. Un test tarifaire rate
laisse de la marchandise perissable vendue sous son cout complet, ou jetee faute
d'avoir tourne, et le stock ne se rattrape pas. La logique de GAAP est donc
inversee par rapport a un outil d'experimentation classique : **une experience
est refusee par defaut et doit prouver qu'elle est admissible.**

Deux familles de controles :

- **Avant lancement** (`pre_launch`) : le plan est-il economiquement,
  statistiquement et deontologiquement admissible ?
- **En cours de test** (`runtime`) : les conditions de validite tiennent-elles
  toujours, et faut-il declencher un arret de protection ?

Chaque controle porte un code stable, repris tel quel dans la piste d'audit.
Un controle qui change de libelle ne doit pas casser l'historique.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from . import stats
from .analysis import ExperimentAnalysis
from .models import Experiment

__all__ = ["Severity", "Check", "GuardrailReport", "pre_launch", "runtime", "PROTECTED_TERMS"]


#: Termes dont la presence dans un ciblage revele une segmentation tarifaire
#: sur un critere protege. La liste couvre les criteres de discrimination
#: prohibes en droit belge et europeen (loi anti-discrimination du 10 mai 2007,
#: directive 2004/113/CE). Un test de prix differencie selon la composition
#: sociale d'un quartier tomberait sous le coup de ces textes, meme sans
#: intention. Elle est volontairement large : un faux positif se leve par une
#: revue humaine, un faux negatif se decouvre en contentieux.
PROTECTED_TERMS = (
    "age", "sexe", "genre", "femme", "homme", "nationalite", "origine", "ethnie",
    "religion", "handicap", "grossesse", "maternite", "sante", "syndicat",
    "orientation", "conviction", "naissance", "fortune",
)


class Severity(str, Enum):
    BLOCKING = "blocking"
    WARNING = "warning"
    INFO = "info"

    @property
    def label(self) -> str:
        return {"blocking": "Bloquant", "warning": "Avertissement", "info": "Information"}[self.value]


@dataclass(frozen=True)
class Check:
    """Resultat d'un controle unitaire."""

    code: str
    label: str
    severity: Severity
    passed: bool
    detail: str

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "label": self.label,
            "severity": self.severity.value,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class GuardrailReport:
    checks: tuple[Check, ...]

    @property
    def blocking(self) -> tuple[Check, ...]:
        return tuple(c for c in self.checks if not c.passed and c.severity is Severity.BLOCKING)

    @property
    def warnings(self) -> tuple[Check, ...]:
        return tuple(c for c in self.checks if not c.passed and c.severity is Severity.WARNING)

    @property
    def cleared(self) -> bool:
        """Vrai si aucun controle bloquant n'est en echec."""
        return not self.blocking

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    def to_dict(self) -> dict:
        return {
            "cleared": self.cleared,
            "passed": self.passed_count,
            "total": len(self.checks),
            "checks": [c.to_dict() for c in self.checks],
        }


def _cents(value: float) -> str:
    return f"{value:+.0f} centimes"


def pre_launch(experiment: Experiment) -> GuardrailReport:
    """Controles d'admissibilite d'un plan de test tarifaire."""
    checks: list[Check] = []
    floor = experiment.price_floor.total

    # 1. Structure du plan -------------------------------------------------
    has_control = any(c.is_control for c in experiment.cells)
    checks.append(Check(
        "PLAN_CONTROL", "Cellule de controle presente", Severity.BLOCKING, has_control,
        "Le prix courant sert de reference." if has_control
        else "Aucune cellule de controle : aucun contrefactuel, donc aucune mesure d'effet possible.",
    ))

    positive_weights = all(c.weight > 0 for c in experiment.cells) and len(experiment.cells) >= 2
    checks.append(Check(
        "PLAN_WEIGHTS", "Poids d'allocation valides", Severity.BLOCKING, positive_weights,
        f"{len(experiment.cells)} cellules, poids strictement positifs." if positive_weights
        else "Au moins deux cellules avec un poids strictement positif sont requises.",
    ))

    # 2. Plancher de rentabilite ------------------------------------------
    breaches = [
        f"{cell.label} ({cell.effective_price:.2f} EUR vs plancher {floor:.2f} EUR)"
        for cell in experiment.cells if cell.effective_price < floor
    ]
    checks.append(Check(
        "ECO_FLOOR", "Plancher de rentabilite respecte", Severity.BLOCKING, not breaches,
        f"Toutes les cellules couvrent achat, logistique, manutention, perte attendue sur "
        f"invendus et immobilisation (plancher {floor:.2f} EUR/kg)." if not breaches
        else "Cellules sous le plancher economique : " + " ; ".join(breaches),
    ))

    # 3. Amplitude tarifaire ----------------------------------------------
    out_of_band = [
        f"{c.label} ({_cents(experiment.delta_cents(c))})"
        for c in experiment.cells if abs(experiment.delta_cents(c)) > experiment.max_delta_cents
    ]
    checks.append(Check(
        "ECO_BAND", "Amplitude tarifaire dans la bande autorisee", Severity.BLOCKING, not out_of_band,
        f"Ecart maximal autorise : {experiment.max_delta_cents:.0f} centimes par kilo."
        if not out_of_band else "Cellules hors bande : " + " ; ".join(out_of_band),
    ))

    # 4. Exposition --------------------------------------------------------
    within_exposure = experiment.exposure <= experiment.max_exposure + 1e-9
    checks.append(Check(
        "RISK_EXPOSURE", "Exposition du volume plafonnee", Severity.BLOCKING, within_exposure,
        f"{experiment.exposure * 100:.1f} % du volume servi a un prix de test "
        f"(plafond {experiment.max_exposure * 100:.0f} %).",
    ))

    # 5. Criteres proteges -------------------------------------------------
    suspicious = sorted({
        term for rule in tuple(experiment.targeting) + tuple(experiment.excluded_segments)
        for term in PROTECTED_TERMS if term in rule.lower()
    })
    checks.append(Check(
        "COMP_PROTECTED", "Aucune segmentation sur critere protege", Severity.BLOCKING, not suspicious,
        "Le ciblage ne mobilise aucun critere protege." if not suspicious
        else "Termes sensibles detectes dans le ciblage : " + ", ".join(suspicious)
        + ". Une differenciation tarifaire sur ces criteres est prohibee.",
    ))

    # 6. Quatre yeux -------------------------------------------------------
    four_eyes = bool(experiment.approved_by) and experiment.approved_by != experiment.created_by
    checks.append(Check(
        "GOV_FOUR_EYES", "Validation par un second intervenant", Severity.BLOCKING, four_eyes,
        f"Valide par {experiment.approved_by} le {experiment.approved_at or 'n/c'}." if four_eyes
        else "Le concepteur du test ne peut pas etre son propre validateur "
             "(segregation des taches).",
    ))

    # 7. Puissance statistique --------------------------------------------
    required = stats.required_sample_size_per_arm(
        experiment.baseline_sell_through, experiment.target_mde,
        stats.bonferroni(experiment.alpha, experiment.comparisons), experiment.power,
    )
    available = experiment.planned_volume // max(1, len(experiment.cells))
    ratio = available / required if required else 0.0
    power_ok = ratio >= 1.0
    checks.append(Check(
        "STAT_POWER", "Puissance statistique suffisante",
        Severity.BLOCKING if ratio < 0.5 else Severity.WARNING, power_ok,
        f"{available:,} kilos par cellule pour {required:,} requis "
        f"(MDE {experiment.target_mde * 100:.0f} %, puissance {experiment.power * 100:.0f} %, "
        f"alpha corrige {stats.bonferroni(experiment.alpha, experiment.comparisons):.4f})."
        .replace(",", " "),
    ))

    # 8. Temoin preserve ---------------------------------------------------
    has_holdout = experiment.holdout_share > 0
    checks.append(Check(
        "STAT_HOLDOUT", "Groupe temoin preserve", Severity.WARNING, has_holdout,
        f"{experiment.holdout_share * 100:.0f} % du volume conserve hors test, reference "
        "de long terme." if has_holdout
        else "Sans temoin preserve, aucun effet de derive ne sera mesurable apres bascule.",
    ))

    # 9. Duree -------------------------------------------------------------
    duration_ok = 7 <= experiment.max_duration_days <= 120
    checks.append(Check(
        "PLAN_DURATION", "Duree du test bornee", Severity.WARNING, duration_ok,
        f"{experiment.max_duration_days} jours."
        + ("" if duration_ok else " Une duree hors de [7, 120] jours expose soit a un effet de "
                                  "nouveaute, soit a une derive saisonniere non controlee."),
    ))

    return GuardrailReport(tuple(checks))


def runtime(analysis: ExperimentAnalysis, loss_tolerance_per_unit: float | None = None) -> GuardrailReport:
    """Controles en cours de test, incluant les conditions d'arret de protection.

    La tolerance de perte par kilo presente est lue dans le plan pre-enregistre
    de l'experience : c'est une decision de comite, prise avant de voir les
    resultats, l'equivalent tarifaire d'une limite de perte de trading. La
    surcharger par argument reste possible pour rejouer une politique
    alternative, jamais pour assouplir un test en cours.
    """
    checks: list[Check] = []
    exp = analysis.experiment
    if loss_tolerance_per_unit is None:
        loss_tolerance_per_unit = exp.loss_tolerance_per_unit

    checks.append(Check(
        "STAT_SRM", "Integrite de l'allocation (SRM)", Severity.BLOCKING, analysis.srm.passed,
        f"chi2 = {analysis.srm.chi_square:.2f}, ddl = {analysis.srm.df}, "
        f"p = {analysis.srm.p_value:.3f}." if analysis.srm.passed
        else f"Ecart significatif a l'allocation theorique (p = {analysis.srm.p_value:.2e}). "
             "Cause probable : filtre applique en aval du routage, exclusion asymetrique "
             "ou perte de trafic sur une cellule.",
    ))

    under = [r.cell.label for r in analysis.results if r.presented < exp.min_sample_per_cell]
    checks.append(Check(
        "STAT_SAMPLE", "Volume minimal par cellule atteint", Severity.WARNING, not under,
        f"Toutes les cellules depassent {exp.min_sample_per_cell:,} kilos.".replace(",", " ")
        if not under else "Cellules encore sous le seuil : " + ", ".join(under),
    ))

    harmful = [
        r for r in analysis.results
        if r.contribution_test and r.contribution_test.ci_high < -loss_tolerance_per_unit
    ]
    checks.append(Check(
        "ECO_STOPLOSS", "Aucune cellule au-dela de la tolerance de perte",
        Severity.BLOCKING, not harmful,
        f"Tolerance : {loss_tolerance_per_unit:.2f} EUR de contribution par kilo presente."
        if not harmful else "Arret de protection requis sur : " + ", ".join(
            f"{r.cell.label} ({r.contribution_test.ci_high:+.2f} EUR/kg en borne haute)"
            for r in harmful
        ),
    ))

    checks.append(Check(
        "RISK_QUALITY", "Pas de selection par la qualite",
        Severity.WARNING, not analysis.quality_selection_alert,
        "L'indice de fraîcheur des kilos vendus reste stable entre cellules."
        if not analysis.quality_selection_alert
        else "Le relevement de prix rend le client plus selectif : le stock residuel se degrade, "
             "et la marge supplementaire est partiellement compensee par une casse plus lourde.",
    ))

    # Le plancher se recalcule a la rotation observee : une cellule peut le
    # franchir en cours de test sans qu'aucun prix n'ait bouge, simplement parce
    # qu'elle tourne moins vite que prevu.
    sunk = [r.cell.label for r in analysis.results
            if r.presented > 0 and r.effective_price < r.floor_observed]
    checks.append(Check(
        "ECO_FLOOR_LIVE", "Plancher toujours couvert a la rotation observee",
        Severity.BLOCKING, not sunk,
        f"Plancher du plan : {analysis.floor_planned:.2f} EUR/kg, recalcule cellule par cellule "
        "sur l'ecoulement constate." if not sunk
        else "Passees sous leur plancher faute de rotation : " + ", ".join(sunk),
    ))

    return GuardrailReport(tuple(checks))
