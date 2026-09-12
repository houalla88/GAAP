"""Regle de decision : chaque verdict est atteint pour la bonne raison."""

import pytest

from gaap.domain.analysis import CellAggregate, analyse
from gaap.domain.decision import Verdict, recommend
from gaap.domain.guardrails import runtime


def _isoelastique(plan, elasticite: float, base: float = 0.82) -> dict[str, float]:
    reference = plan.control.effective_price
    return {c.key: min(0.99, base * (c.effective_price / reference) ** elasticite)
            for c in plan.cells}


def _decide(plan, taux, volume=12_000, qualite=None):
    qualite = qualite or {}
    aggregats = []
    for cell in plan.cells:
        presente = volume * (2 if cell.is_control else 1)
        vendu = int(round(presente * taux[cell.key]))
        q = qualite.get(cell.key, 0.70)
        aggregats.append(CellAggregate(
            cell.key, presente, vendu,
            presente * 0.70, presente * (0.70 ** 2 + 0.02),
            vendu * q, vendu * (q ** 2 + 0.02),
        ))
    analysis = analyse(plan, aggregats)
    return analysis, recommend(analysis, runtime(analysis))


class TestVerdicts:
    def test_volume_insuffisant_interdit_de_conclure(self, plan):
        _, reco = _decide(plan, {c.key: 0.82 for c in plan.cells}, volume=500)
        assert reco.verdict is Verdict.INSUFFICIENT
        assert reco.target_cell_key is None
        assert "peeking" in " ".join(reco.rationale).lower()

    def test_srm_invalide_tout(self, plan):
        aggregats = [
            CellAggregate(c.key,
                          n := (24_000 if c.is_control else (5_000 if c.key == "p20" else 12_000)),
                          int(n * 0.82), 0.0, 0.0, 0.0, 0.0)
            for c in plan.cells
        ]
        analysis = analyse(plan, aggregats)
        reco = recommend(analysis, runtime(analysis))
        assert reco.verdict is Verdict.INVALID
        assert reco.confidence == 0.0
        assert "purger" in " ".join(reco.rationale).lower()

    def test_bascule_sur_preuve_economique(self, plan):
        analysis, reco = _decide(plan, _isoelastique(plan, -0.7))
        assert reco.verdict is Verdict.SWITCH
        assert reco.target_cell_key == "p40"
        assert reco.impact_ci[0] > 0
        assert reco.target_price == pytest.approx(3.35)

    def test_l_arbitrage_est_explicite_dans_la_motivation(self, plan):
        """La motivation doit dire, noir sur blanc, que l'ecoulement et la casse
        designaient l'autre cellule."""
        analysis, reco = _decide(plan, _isoelastique(plan, -0.7))
        assert analysis.metric_conflict
        motivation = " ".join(reco.rationale)
        assert "ecoule mieux" in motivation
        assert "casse moins" in motivation
        assert "gaspillage" in motivation

    def test_conserver_quand_l_ecart_est_economiquement_neutre(self, plan):
        """Un ecart d'ecoulement significatif mais sans effet sur la
        contribution ne justifie aucune bascule."""
        cost = plan.cost
        control_value = plan.control.effective_price - cost.salvage_value - cost.capital_cost
        variante = plan.cell("p20")
        variant_value = variante.effective_price - cost.salvage_value - cost.capital_cost
        neutre = 0.82 * control_value / variant_value
        duo = plan.with_status(plan.status, cells=(plan.control, variante))
        analysis, reco = _decide(duo, {"ctl": 0.82, "p20": neutre}, volume=15_000)
        assert reco.verdict is Verdict.KEEP
        assert reco.target_cell_key == "ctl"

    def test_arret_de_protection_prime_sur_la_preuve(self, plan):
        serre = plan.with_status(plan.status, loss_tolerance_per_unit=0.01)
        _, reco = _decide(serre, _isoelastique(serre, -0.7))
        assert reco.verdict is Verdict.PROTECT
        assert reco.target_cell_key == "ctl"


class TestReserves:
    def test_toute_recommandation_porte_ses_limites(self, plan):
        """Une recommandation tarifaire sans ses reserves est incomplete, meme
        quand tout va bien."""
        for taux in (_isoelastique(plan, -0.7), {c.key: 0.82 for c in plan.cells}):
            _, reco = _decide(plan, taux)
            assert reco.caveats
            assert any("fenetre du test" in note for note in reco.caveats)

    def test_la_non_independance_des_kilos_est_signalee(self, plan):
        """Limite reelle du choix d'unite d'observation : les kilos d'un meme lot
        partagent une implantation et une fraîcheur de depart."""
        _, reco = _decide(plan, _isoelastique(plan, -0.7))
        assert any("grappe" in note for note in reco.caveats)

    def test_le_couplage_prix_quantite_est_signale(self, plan):
        _, reco = _decide(plan, _isoelastique(plan, -0.7))
        assert any("vendeur de journaux" in note for note in reco.caveats)

    def test_extrapolation_signalee_quand_l_optimum_sort_de_l_enveloppe(self, plan):
        analysis, reco = _decide(plan, _isoelastique(plan, -3.0, base=0.60))
        assert analysis.elasticity.optimal_is_extrapolated
        assert any("extrapolation" in note.lower() or "enveloppe" in note.lower()
                   for note in reco.caveats)

    def test_selection_par_la_qualite_signalee_dans_les_reserves(self, plan):
        _, reco = _decide(plan, _isoelastique(plan, -0.7), qualite={
            "ctl": 0.700, "m20": 0.694, "p20": 0.722, "p40": 0.741,
        })
        assert any("stock residuel" in note for note in reco.caveats)


def test_serialisation_pour_la_piste_d_audit(plan):
    _, reco = _decide(plan, _isoelastique(plan, -0.7))
    payload = reco.to_dict()
    assert payload["verdict"] == "switch"
    assert isinstance(payload["rationale"], list) and payload["rationale"]
    assert payload["impact_basis"] == 10_000
    import json
    json.dumps(payload)  # doit etre serialisable sans encodeur specifique
