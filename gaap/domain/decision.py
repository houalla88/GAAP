"""Moteur de decision : de la mesure a la recommandation tarifaire.

Separe de `analysis` a dessein. La mesure est une propriete des donnees ; la
regle de decision est une politique de l'etablissement. Les dissocier permet
de rejouer une politique differente sur des mesures inchangees - le seul
moyen honnete de comparer deux regles d'arret sans reecrire l'histoire.

La regle implementee ici est volontairement conservatrice, dans l'ordre :

    1. Validite  : un SRM invalide tout, sans exception.
    2. Protection: une cellule qui detruit de la valeur est coupee avant terme.
    3. Suffisance: aucune conclusion avant le volume minimal par cellule.
    4. Preuve    : franchissement de la frontiere sequentielle ET intervalle de
                   confiance sur la contribution strictement positif.
    5. Futilite  : si plus aucune variante ne peut battre le controle, arreter
                   plutot que laisser courir un test qui coute de la marge.

La condition 4 est double a dessein. Le franchissement seul est une preuve
statistique sur le taux de conversion ; l'intervalle sur la contribution est
une preuve economique. GAAP exige les deux, parce que l'histoire des tests
tarifaires est pleine de gagnants statistiques qui perdaient de l'argent.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .analysis import CellResult, ExperimentAnalysis
from .guardrails import GuardrailReport

__all__ = ["Verdict", "Recommendation", "recommend"]

#: Unite de normalisation de l'impact. Annoncer un impact annuel supposerait un
#: volume futur que le test ne mesure pas ; l'impact pour 10 000 leads exposes
#: est directement verifiable sur les donnees du test.
IMPACT_BASIS = 10_000


class Verdict(str, Enum):
    INVALID = "invalid"
    PROTECT = "protect"
    CONTINUE = "continue"
    SWITCH = "switch"
    KEEP = "keep"
    INSUFFICIENT = "insufficient"

    @property
    def label(self) -> str:
        return {
            "invalid": "Resultat invalide",
            "protect": "Arret de protection",
            "continue": "Poursuivre le test",
            "switch": "Basculer le prix",
            "keep": "Conserver le prix courant",
            "insufficient": "Volume insuffisant",
        }[self.value]

    @property
    def tone(self) -> str:
        """Classe semantique pour l'interface. Jamais portee par la couleur seule."""
        return {
            "invalid": "danger", "protect": "danger", "continue": "info",
            "switch": "success", "keep": "neutral", "insufficient": "neutral",
        }[self.value]


@dataclass(frozen=True)
class Recommendation:
    """Recommandation opposable : un verdict, une cible, et ses justifications."""

    verdict: Verdict
    headline: str
    rationale: tuple[str, ...]
    target_cell_key: str | None
    target_rate: float | None
    impact_per_basis: float
    impact_ci: tuple[float, float]
    confidence: float
    learning_cost: float
    caveats: tuple[str, ...] = ()

    @property
    def impact_basis(self) -> int:
        return IMPACT_BASIS

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict.value,
            "headline": self.headline,
            "rationale": list(self.rationale),
            "target_cell": self.target_cell_key,
            "target_rate": self.target_rate,
            "impact_per_basis": round(self.impact_per_basis, 2),
            "impact_basis": IMPACT_BASIS,
            "impact_ci": [round(self.impact_ci[0], 2), round(self.impact_ci[1], 2)],
            "confidence": round(self.confidence, 4),
            "learning_cost": round(self.learning_cost, 2),
            "caveats": list(self.caveats),
        }


def _fmt_pct(value: float) -> str:
    return f"{value * 100:.2f} %".replace(".", ",")


def _headline_cell(label: str, rate: float) -> str:
    """Intitule d'une cellule sans repeter son taux.

    Les libelles portent souvent deja le prix ("+90 bps (7,80 %)") ; y accoler
    le taux une seconde fois donne un titre de recommandation illisible.
    """
    formatted = _fmt_pct(rate)
    return label if formatted in label else f"{label} ({formatted})"


def _fmt_eur(value: float) -> str:
    return f"{value:,.0f} EUR".replace(",", " ")


def _fmt_learning_cost(value: float) -> str:
    """Le cout d'apprentissage peut etre negatif.

    Un test qui releve le prix sur une partie du trafic peut rapporter plus que
    le prix courant pendant sa duree meme. Nommer cela un "cout" negatif serait
    illisible en comite : la phrase est donc adaptee au signe.
    """
    if value >= 0:
        return f"cout d'apprentissage de {_fmt_eur(value)}"
    return (f"gain net de {_fmt_eur(-value)} pendant le test "
            "(l'apprentissage s'est autofinance)")


def _caveats(analysis: ExperimentAnalysis) -> tuple[str, ...]:
    """Reserves systematiquement jointes a toute recommandation.

    Elles ne sont pas conditionnelles a un echec : une recommandation
    tarifaire livree sans ses limites d'interpretation est une recommandation
    incomplete, meme quand tout va bien.
    """
    notes: list[str] = []
    elasticity = analysis.elasticity
    if elasticity and elasticity.optimal_is_extrapolated:
        notes.append(
            "Le prix optimal theorique sort de l'enveloppe des prix testes "
            f"[{_fmt_pct(elasticity.tested_range[0])} ; {_fmt_pct(elasticity.tested_range[1])}] : "
            "c'est une extrapolation de modele, pas une mesure. Un palier de test "
            "supplementaire est necessaire avant de l'appliquer."
        )
    if elasticity and elasticity.points == 2:
        notes.append(
            "Elasticite estimee sur deux points : aucune incertitude n'est calculable "
            "et aucune courbure n'est observable."
        )
    if analysis.adverse_selection_alert:
        notes.append(
            "Derive du melange de risque detectee : la contribution mesuree utilise la PD "
            "d'octroi et ne capte pas encore la perte reellement constatee. Confirmer sur "
            "les cohortes a 12 mois avant generalisation."
        )
    notes.append(
        "Effet mesure sur la fenetre du test uniquement : ni la reaction concurrentielle, "
        "ni l'effet sur la valeur client a long terme, ni la saisonnalite ne sont captures."
    )
    return tuple(notes)


def _impact(result: CellResult) -> tuple[float, tuple[float, float]]:
    """Impact de contribution rapporte a `IMPACT_BASIS` leads exposes."""
    if not result.rac_test:
        return (0.0, (0.0, 0.0))
    test = result.rac_test
    return (
        test.difference * IMPACT_BASIS,
        (test.ci_low * IMPACT_BASIS, test.ci_high * IMPACT_BASIS),
    )


def recommend(analysis: ExperimentAnalysis, runtime_report: GuardrailReport) -> Recommendation:
    """Applique la regle de decision de GAAP a une lecture d'experience."""
    exp = analysis.experiment
    control = analysis.control_result
    caveats = _caveats(analysis)

    # 1. Validite ----------------------------------------------------------
    if not analysis.srm.passed:
        return Recommendation(
            verdict=Verdict.INVALID,
            headline="Allocation corrompue : aucune conclusion recevable",
            rationale=(
                f"Test SRM en echec (chi2 = {analysis.srm.chi_square:.1f}, "
                f"p = {analysis.srm.p_value:.2e}).",
                "L'ecart a l'allocation theorique signale une perte de trafic ou un filtre "
                "applique apres le routage. Les populations comparees ne sont plus "
                "echangeables, donc tout ecart mesure est inexploitable.",
                "Action : identifier la cause dans la chaîne de service, purger les donnees "
                "et relancer. Ne pas 'corriger' les effectifs a posteriori.",
            ),
            target_cell_key=None, target_rate=None,
            impact_per_basis=0.0, impact_ci=(0.0, 0.0), confidence=0.0,
            learning_cost=analysis.learning_cost, caveats=caveats,
        )

    # 2. Protection --------------------------------------------------------
    stoploss = next((c for c in runtime_report.blocking if c.code == "ECO_STOPLOSS"), None)
    if stoploss:
        harmful = [r for r in analysis.results if r.rac_test and r.rac_test.ci_high < 0]
        worst = min(harmful, key=lambda r: r.rac_per_lead) if harmful else control
        impact, ci = _impact(worst)
        return Recommendation(
            verdict=Verdict.PROTECT,
            headline=f"Couper {worst.cell.label} : perte de contribution avertie",
            rationale=(
                stoploss.detail,
                f"Contribution de {worst.cell.label} : {worst.rac_per_lead:.2f} EUR par lead, "
                f"contre {control.rac_per_lead:.2f} EUR pour le prix courant.",
                f"Bilan economique du test a ce stade : {_fmt_learning_cost(analysis.learning_cost)}.",
                "Le reste du plan peut continuer si les autres cellules restent dans la "
                "tolerance : couper la cellule, pas l'experience.",
            ),
            target_cell_key=control.cell.key, target_rate=control.cell.rate,
            impact_per_basis=impact, impact_ci=ci, confidence=0.0,
            learning_cost=analysis.learning_cost, caveats=caveats,
        )

    # 3. Suffisance --------------------------------------------------------
    below = [r for r in analysis.results if r.exposed < exp.min_sample_per_cell]
    if below:
        missing = sum(exp.min_sample_per_cell - r.exposed for r in below)
        return Recommendation(
            verdict=Verdict.INSUFFICIENT,
            headline=f"Volume insuffisant : {missing:,} leads manquants".replace(",", " "),
            rationale=(
                f"{len(below)} cellule(s) sous le seuil de {exp.min_sample_per_cell:,} leads."
                .replace(",", " "),
                f"Information accumulee : {analysis.information_fraction * 100:.0f} % du plan. "
                f"Frontiere d'arret courante : |z| >= {analysis.boundary:.2f}.",
                "Lire un resultat maintenant reviendrait a du peeking : le risque de faux "
                "positif reel depasserait largement le seuil affiche.",
            ),
            target_cell_key=None, target_rate=None,
            impact_per_basis=0.0, impact_ci=(0.0, 0.0),
            confidence=analysis.information_fraction,
            learning_cost=analysis.learning_cost, caveats=caveats,
        )

    # 4. Preuve ------------------------------------------------------------
    challengers = [r for r in analysis.results if not r.is_control and r.rac_test]
    proven = [
        r for r in challengers
        if r.boundary_crossed and r.rac_test.ci_low > 0 and r.rac_per_lead > control.rac_per_lead
    ]
    if proven:
        winner = max(proven, key=lambda r: r.rac_per_lead)
        impact, ci = _impact(winner)
        rationale = [
            f"{winner.cell.label} porte la contribution a {winner.rac_per_lead:.2f} EUR par lead "
            f"expose, contre {control.rac_per_lead:.2f} EUR pour le prix courant "
            f"({winner.rac_test.difference:+.2f} EUR).",
            f"Frontiere sequentielle franchie sur la contribution : |t| = "
            f"{abs(winner.rac_test.t):.2f} pour un seuil de {analysis.boundary:.2f} a "
            f"{analysis.information_fraction * 100:.0f} % d'information "
            f"(take-up : z = {winner.takeup_test.z:+.2f}).",
            f"Intervalle de confiance a {(1 - analysis.alpha_adjusted) * 100:.1f} % sur l'impact : "
            f"[{ci[0]:+,.0f} ; {ci[1]:+,.0f}] EUR pour {IMPACT_BASIS:,} leads exposes."
            .replace(",", " "),
            f"Marge sur plancher : {winner.margin_bp:.0f} bps, RAROC {winner.raroc * 100:.1f} % "
            f"contre un cout des fonds propres de {exp.cost.hurdle_rate * 100:.1f} %.",
        ]
        if analysis.metric_conflict:
            best_takeup = analysis.best_by_take_up
            rationale.append(
                f"Arbitrage explicite : {best_takeup.cell.label} convertit mieux "
                f"({_fmt_pct(best_takeup.take_up)} contre {_fmt_pct(winner.take_up)}) mais "
                f"rapporte moins ({best_takeup.rac_per_lead:.2f} EUR contre "
                f"{winner.rac_per_lead:.2f} EUR par lead). GAAP tranche sur la contribution."
            )
        return Recommendation(
            verdict=Verdict.SWITCH,
            headline=f"Basculer sur {_headline_cell(winner.cell.label, winner.cell.rate)}",
            rationale=tuple(rationale),
            target_cell_key=winner.cell.key, target_rate=winner.cell.rate,
            impact_per_basis=impact, impact_ci=ci,
            confidence=winner.prob_beats_control or 0.0,
            learning_cost=analysis.learning_cost, caveats=caveats,
        )

    # 5. Futilite ----------------------------------------------------------
    exhausted = analysis.information_fraction >= 1.0
    hopeless = all(r.rac_test.ci_high <= 0 for r in challengers) if challengers else True
    if exhausted or hopeless:
        best_challenger = max(challengers, key=lambda r: r.rac_per_lead) if challengers else None
        rationale = [
            "Aucune cellule ne demontre de gain de contribution significatif face au prix courant.",
            f"Information accumulee : {analysis.information_fraction * 100:.0f} %.",
        ]
        if best_challenger:
            test = best_challenger.rac_test
            straddles_zero = test.ci_low <= 0.0 <= test.ci_high
            rationale.append(
                f"Meilleure variante ({best_challenger.cell.label}) : "
                f"{test.difference:+.2f} EUR par lead, intervalle "
                f"[{test.ci_low:+.2f} ; {test.ci_high:+.2f}]"
                + (" - compatible avec l'absence d'effet." if straddles_zero
                   else " - ecart mesure mais frontiere sequentielle non franchie a ce stade.")
            )
            if best_challenger.takeup_test and best_challenger.takeup_test.significant and straddles_zero:
                rationale.append(
                    f"Cas a signaler en comite : l'ecart de take-up est statistiquement "
                    f"significatif (z = {best_challenger.takeup_test.z:+.2f}) mais "
                    "economiquement neutre. Conclure sur la conversion aurait conduit a "
                    "une decision que la contribution ne justifie pas."
                )
        rationale.append(
            f"Bilan economique du test : {_fmt_learning_cost(analysis.learning_cost)}. Un cout "
            "d'apprentissage n'est pas une perte seche : il achete une borne superieure credible "
            "sur l'elasticite, reutilisable pour le prochain plan tarifaire."
        )
        if analysis.elasticity:
            rationale.append(
                f"Elasticite estimee : {analysis.elasticity.value:.2f} "
                f"({analysis.elasticity.method}, R2 = {analysis.elasticity.r_squared:.2f})."
            )
        return Recommendation(
            verdict=Verdict.KEEP,
            headline=f"Conserver le prix courant ({_fmt_pct(control.cell.rate)})",
            rationale=tuple(rationale),
            target_cell_key=control.cell.key, target_rate=control.cell.rate,
            impact_per_basis=0.0, impact_ci=(0.0, 0.0),
            confidence=1.0 - max((r.prob_beats_control or 0.0) for r in challengers) if challengers else 1.0,
            learning_cost=analysis.learning_cost, caveats=caveats,
        )

    # 6. Poursuite ---------------------------------------------------------
    leader = max(challengers, key=lambda r: r.rac_per_lead)
    impact, ci = _impact(leader)
    return Recommendation(
        verdict=Verdict.CONTINUE,
        headline=f"Poursuivre : {leader.cell.label} en tete, preuve non acquise",
        rationale=(
            f"{leader.cell.label} mene sur la contribution "
            f"({leader.rac_test.difference:+.2f} EUR par lead) mais l'intervalle "
            f"[{leader.rac_test.ci_low:+.2f} ; {leader.rac_test.ci_high:+.2f}] contient encore zero.",
            f"Frontiere sequentielle sur la contribution : |t| = {abs(leader.rac_test.t):.2f} "
            f"pour un seuil de {analysis.boundary:.2f}. Le seuil se detend a mesure que "
            f"l'information s'accumule.",
            f"Probabilite que {leader.cell.label} rapporte davantage : "
            f"{(leader.prob_beats_control or 0) * 100:.1f} % ; perte attendue en cas de bascule "
            f"immediate : {(leader.expected_loss or 0):.2f} EUR par lead expose, pour une "
            f"tolerance fixee a {exp.loss_tolerance_per_lead:.2f} EUR.",
            f"Information accumulee : {analysis.information_fraction * 100:.0f} %.",
        ),
        target_cell_key=None, target_rate=None,
        impact_per_basis=impact, impact_ci=ci,
        confidence=leader.prob_beats_control or 0.0,
        learning_cost=analysis.learning_cost, caveats=caveats,
    )
