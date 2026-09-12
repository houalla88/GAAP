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
statistique sur l'ecoulement ; l'intervalle sur la contribution est
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
#: volume futur que le test ne mesure pas ; l'impact pour 10 000 kilos presentes
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
    target_price: float | None
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
            "target_price": self.target_price,
            "impact_per_basis": round(self.impact_per_basis, 2),
            "impact_basis": IMPACT_BASIS,
            "impact_ci": [round(self.impact_ci[0], 2), round(self.impact_ci[1], 2)],
            "confidence": round(self.confidence, 4),
            "learning_cost": round(self.learning_cost, 2),
            "caveats": list(self.caveats),
        }


def _fmt_pct(value: float) -> str:
    return f"{value * 100:.1f} %".replace(".", ",")


def _fmt_price(value: float) -> str:
    return f"{value:.2f} EUR/kg".replace(".", ",")


def _headline_cell(label: str, price: float) -> str:
    """Intitule d'une cellule sans repeter son prix.

    Les libelles portent souvent deja le prix ("+20 c (3,15 EUR)") ; l'accoler
    une seconde fois donne un titre de recommandation illisible.
    """
    formatted = f"{price:.2f}".replace(".", ",")
    return label if formatted in label else f"{label} ({_fmt_price(price)})"


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
            f"[{_fmt_price(elasticity.tested_range[0])} ; "
            f"{_fmt_price(elasticity.tested_range[1])}] : c'est une extrapolation de modele, "
            "pas une mesure. Un palier de test supplementaire est necessaire avant de "
            "l'appliquer."
        )
    if elasticity and elasticity.points == 2:
        notes.append(
            "Elasticite estimee sur deux points : aucune incertitude n'est calculable "
            "et aucune courbure n'est observable."
        )
    if analysis.quality_selection_alert:
        notes.append(
            "Selection par la qualite detectee : le stock residuel se degrade plus vite que "
            "ne l'explique le ralentissement de rotation. La casse constatee en fin de "
            "periode risque de depasser celle qu'anticipe ce calcul."
        )
    notes.append(
        "Les kilos d'un meme lot ne sont pas independants : ils partagent une implantation, "
        "une fraîcheur de depart et un flux client. Les intervalles calcules sous hypothese "
        "binomiale sont donc optimistes, et un correctif d'effet de grappe leur serait "
        "applicable."
    )
    notes.append(
        "La quantite mise en rayon est traitee comme donnee. L'optimisation conjointe du "
        "prix et de la quantite commandee, qui releve du probleme du vendeur de journaux, "
        "n'est pas modelisee ici."
    )
    notes.append(
        "Effet mesure sur la fenetre du test uniquement : ni la reaction de la concurrence, "
        "ni l'effet de gamme sur les produits voisins, ni la saisonnalite ne sont captures."
    )
    return tuple(notes)


def _impact(result: CellResult) -> tuple[float, tuple[float, float]]:
    """Impact de contribution rapporte a `IMPACT_BASIS` kilos presentes."""
    if not result.contribution_test:
        return (0.0, (0.0, 0.0))
    test = result.contribution_test
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
            target_cell_key=None, target_price=None,
            impact_per_basis=0.0, impact_ci=(0.0, 0.0), confidence=0.0,
            learning_cost=analysis.learning_cost, caveats=caveats,
        )

    # 2. Protection --------------------------------------------------------
    stoploss = next((c for c in runtime_report.blocking if c.code == "ECO_STOPLOSS"), None)
    if stoploss:
        harmful = [r for r in analysis.results if r.contribution_test and r.contribution_test.ci_high < 0]
        worst = min(harmful, key=lambda r: r.contribution_per_unit) if harmful else control
        impact, ci = _impact(worst)
        return Recommendation(
            verdict=Verdict.PROTECT,
            headline=f"Couper {worst.cell.label} : perte de contribution avertie",
            rationale=(
                stoploss.detail,
                f"Contribution de {worst.cell.label} : {worst.contribution_per_unit:.3f} EUR par "
                f"kilo presente, contre {control.contribution_per_unit:.3f} EUR pour le prix courant.",
                f"Bilan economique du test a ce stade : {_fmt_learning_cost(analysis.learning_cost)}.",
                "Le reste du plan peut continuer si les autres cellules restent dans la "
                "tolerance : couper la cellule, pas l'experience.",
            ),
            target_cell_key=control.cell.key, target_price=control.cell.price,
            impact_per_basis=impact, impact_ci=ci, confidence=0.0,
            learning_cost=analysis.learning_cost, caveats=caveats,
        )

    # 3. Suffisance --------------------------------------------------------
    below = [r for r in analysis.results if r.presented < exp.min_sample_per_cell]
    if below:
        missing = sum(exp.min_sample_per_cell - r.presented for r in below)
        return Recommendation(
            verdict=Verdict.INSUFFICIENT,
            headline=f"Volume insuffisant : {missing:,} kilos manquants".replace(",", " "),
            rationale=(
                f"{len(below)} cellule(s) sous le seuil de {exp.min_sample_per_cell:,} kilos."
                .replace(",", " "),
                f"Information accumulee : {analysis.information_fraction * 100:.0f} % du plan. "
                f"Frontiere d'arret courante : |t| >= {analysis.boundary:.2f}.",
                "Lire un resultat maintenant reviendrait a du peeking : le risque de faux "
                "positif reel depasserait largement le seuil affiche.",
            ),
            target_cell_key=None, target_price=None,
            impact_per_basis=0.0, impact_ci=(0.0, 0.0),
            confidence=analysis.information_fraction,
            learning_cost=analysis.learning_cost, caveats=caveats,
        )

    # 4. Preuve ------------------------------------------------------------
    challengers = [r for r in analysis.results if not r.is_control and r.contribution_test]
    proven = [
        r for r in challengers
        if r.boundary_crossed and r.contribution_test.ci_low > 0 and r.contribution_per_unit > control.contribution_per_unit
    ]
    if proven:
        winner = max(proven, key=lambda r: r.contribution_per_unit)
        impact, ci = _impact(winner)
        rationale = [
            f"{winner.cell.label} porte la contribution a {winner.contribution_per_unit:.3f} EUR "
            f"par kilo presente, contre {control.contribution_per_unit:.3f} EUR pour le prix "
            f"courant ({winner.contribution_test.difference:+.3f} EUR).",
            f"Frontiere sequentielle franchie sur la contribution : |t| = "
            f"{abs(winner.contribution_test.t):.2f} pour un seuil de {analysis.boundary:.2f} a "
            f"{analysis.information_fraction * 100:.0f} % d'information "
            f"(ecoulement : z = {winner.sell_through_test.z:+.2f}).",
            f"Intervalle de confiance a {(1 - analysis.alpha_adjusted) * 100:.1f} % sur l'impact : "
            f"[{ci[0]:+,.0f} ; {ci[1]:+,.0f}] EUR pour {IMPACT_BASIS:,} kilos presentes."
            .replace(",", " "),
            f"Marge sur plancher recalcule a la rotation observee : "
            f"{winner.margin_per_unit_sold:.3f} EUR par kilo vendu, pour un plancher de "
            f"{winner.floor_observed:.2f} EUR et une casse de {winner.waste_rate * 100:.1f} %.",
        ]
        if analysis.metric_conflict:
            best_flow = analysis.best_by_sell_through
            rationale.append(
                f"Arbitrage explicite : {best_flow.cell.label} ecoule mieux "
                f"({_fmt_pct(best_flow.sell_through)} contre {_fmt_pct(winner.sell_through)}) et "
                f"casse moins ({_fmt_pct(best_flow.waste_rate)} contre "
                f"{_fmt_pct(winner.waste_rate)}), mais rapporte moins "
                f"({best_flow.contribution_per_unit:.3f} EUR contre "
                f"{winner.contribution_per_unit:.3f} EUR par kilo presente). Un objectif de "
                "reduction du gaspillage aurait donc designe le prix le moins rentable."
            )
        return Recommendation(
            verdict=Verdict.SWITCH,
            headline=f"Basculer sur {_headline_cell(winner.cell.label, winner.cell.price)}",
            rationale=tuple(rationale),
            target_cell_key=winner.cell.key, target_price=winner.cell.price,
            impact_per_basis=impact, impact_ci=ci,
            confidence=winner.prob_beats_control or 0.0,
            learning_cost=analysis.learning_cost, caveats=caveats,
        )

    # 5. Futilite ----------------------------------------------------------
    exhausted = analysis.information_fraction >= 1.0
    hopeless = all(r.contribution_test.ci_high <= 0 for r in challengers) if challengers else True
    if exhausted or hopeless:
        best_challenger = max(challengers, key=lambda r: r.contribution_per_unit) if challengers else None
        rationale = [
            "Aucune cellule ne demontre de gain de contribution significatif face au prix courant.",
            f"Information accumulee : {analysis.information_fraction * 100:.0f} %.",
        ]
        if best_challenger:
            test = best_challenger.contribution_test
            straddles_zero = test.ci_low <= 0.0 <= test.ci_high
            rationale.append(
                f"Meilleure variante ({best_challenger.cell.label}) : "
                f"{test.difference:+.3f} EUR par kilo presente, intervalle "
                f"[{test.ci_low:+.3f} ; {test.ci_high:+.3f}]"
                + (" - compatible avec l'absence d'effet." if straddles_zero
                   else " - ecart mesure mais frontiere sequentielle non franchie a ce stade.")
            )
            if best_challenger.sell_through_test and best_challenger.sell_through_test.significant and straddles_zero:
                rationale.append(
                    f"Cas a signaler en comite : l'ecart d'ecoulement est statistiquement "
                    f"significatif (z = {best_challenger.sell_through_test.z:+.2f}) mais "
                    "economiquement neutre. Conclure sur l'ecoulement aurait conduit a une "
                    "decision que la contribution ne justifie pas."
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
            headline=f"Conserver le prix courant ({_fmt_price(control.cell.price)})",
            rationale=tuple(rationale),
            target_cell_key=control.cell.key, target_price=control.cell.price,
            impact_per_basis=0.0, impact_ci=(0.0, 0.0),
            confidence=1.0 - max((r.prob_beats_control or 0.0) for r in challengers) if challengers else 1.0,
            learning_cost=analysis.learning_cost, caveats=caveats,
        )

    # 6. Poursuite ---------------------------------------------------------
    leader = max(challengers, key=lambda r: r.contribution_per_unit)
    impact, ci = _impact(leader)
    return Recommendation(
        verdict=Verdict.CONTINUE,
        headline=f"Poursuivre : {leader.cell.label} en tete, preuve non acquise",
        rationale=(
            f"{leader.cell.label} mene sur la contribution "
            f"({leader.contribution_test.difference:+.3f} EUR par kilo presente) mais "
            f"l'intervalle [{leader.contribution_test.ci_low:+.3f} ; "
            f"{leader.contribution_test.ci_high:+.3f}] contient encore zero.",
            f"Frontiere sequentielle sur la contribution : |t| = {abs(leader.contribution_test.t):.2f} "
            f"pour un seuil de {analysis.boundary:.2f}. Le seuil se detend a mesure que "
            f"l'information s'accumule.",
            f"Probabilite que {leader.cell.label} rapporte davantage : "
            f"{(leader.prob_beats_control or 0) * 100:.1f} % ; perte attendue en cas de bascule "
            f"immediate : {(leader.expected_loss or 0):.3f} EUR par kilo presente, pour une "
            f"tolerance fixee a {exp.loss_tolerance_per_unit:.2f} EUR.",
            f"Information accumulee : {analysis.information_fraction * 100:.0f} %.",
        ),
        target_cell_key=None, target_price=None,
        impact_per_basis=impact, impact_ci=ci,
        confidence=leader.prob_beats_control or 0.0,
        learning_cost=analysis.learning_cost, caveats=caveats,
    )
