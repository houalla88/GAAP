"""Regle de decision : chaque verdict est atteint pour la bonne raison."""

import pytest

from gaap.domain.analysis import CellAggregate, analyse
from gaap.domain.decision import Verdict, recommend
from gaap.domain.guardrails import runtime


def _decide(plan, take_ups, volume=8_000, pd_par_cellule=None):
    pd_par_cellule = pd_par_cellule or {}
    aggregats = []
    for cell in plan.cells:
        exposes = volume * (2 if cell.is_control else 1)
        conversions = int(round(exposes * take_ups[cell.key]))
        pd_moyenne = pd_par_cellule.get(cell.key, 0.021)
        aggregats.append(CellAggregate(
            cell.key, exposes, conversions,
            exposes * 0.021, exposes * (0.021 ** 2 + 1e-4),
            conversions * pd_moyenne, conversions * (pd_moyenne ** 2 + 1e-4),
        ))
    analysis = analyse(plan, aggregats)
    return analysis, recommend(analysis, runtime(analysis))


class TestVerdicts:
    def test_volume_insuffisant_interdit_de_conclure(self, plan):
        _, reco = _decide(plan, {k.key: 0.06 for k in plan.cells}, volume=500)
        assert reco.verdict is Verdict.INSUFFICIENT
        assert reco.target_cell_key is None
        assert "peeking" in " ".join(reco.rationale).lower()

    def test_srm_invalide_tout(self, plan):
        aggregats = [
            CellAggregate(c.key, 16_000 if c.is_control else (3_000 if c.key == "p45" else 8_000),
                          int((16_000 if c.is_control else (3_000 if c.key == "p45" else 8_000)) * 0.06),
                          0.0, 0.0, 0.0, 0.0)
            for c in plan.cells
        ]
        analysis = analyse(plan, aggregats)
        reco = recommend(analysis, runtime(analysis))
        assert reco.verdict is Verdict.INVALID
        assert reco.confidence == 0.0
        assert "purger" in " ".join(reco.rationale).lower()

    def test_bascule_sur_preuve_economique(self, plan):
        analysis, reco = _decide(plan, {
            "ctl": 0.061, "m45": 0.084, "p45": 0.047, "p90": 0.037,
        }, volume=12_000)
        assert reco.verdict is Verdict.SWITCH
        assert reco.target_cell_key == "p90"
        assert reco.impact_ci[0] > 0            # borne basse strictement positive
        assert reco.confidence >= 0.0

    def test_l_arbitrage_est_explicite_dans_la_motivation(self, plan):
        analysis, reco = _decide(plan, {
            "ctl": 0.061, "m45": 0.084, "p45": 0.047, "p90": 0.037,
        }, volume=12_000)
        assert analysis.metric_conflict
        assert any("convertit mieux" in line for line in reco.rationale)

    def test_conserver_quand_l_ecart_est_economiquement_neutre(self, plan):
        """Cas important : un ecart de conversion significatif mais sans effet
        sur la contribution ne justifie aucune bascule."""
        floor = plan.price_floor.total
        marge_ctl = plan.control.rate - floor
        marge_p45 = 0.0735 - floor
        take_up_neutre = 0.061 * marge_ctl / marge_p45
        duo = plan.with_status(plan.status, cells=(plan.control, plan.cell("p45")))
        analysis, reco = _decide(duo, {"ctl": 0.061, "p45": take_up_neutre}, volume=15_000)
        assert reco.verdict is Verdict.KEEP
        assert reco.target_cell_key == "ctl"

    def test_arret_de_protection_prime_sur_la_preuve(self, plan):
        serre = plan.with_status(plan.status, loss_tolerance_per_lead=1.0)
        _, reco = _decide(serre, {
            "ctl": 0.061, "m45": 0.075, "p45": 0.047, "p90": 0.037,
        }, volume=12_000)
        assert reco.verdict is Verdict.PROTECT
        assert reco.target_cell_key == "ctl"


class TestReserves:
    def test_toute_recommandation_porte_ses_limites(self, plan):
        """Une recommandation tarifaire sans ses reserves est incomplete, meme
        quand tout va bien."""
        for take_ups in (
            {"ctl": 0.061, "m45": 0.084, "p45": 0.047, "p90": 0.037},
            {k.key: 0.06 for k in plan.cells},
        ):
            _, reco = _decide(plan, take_ups, volume=12_000)
            assert reco.caveats
            assert any("fenetre du test" in note for note in reco.caveats)

    def test_extrapolation_signalee_quand_l_optimum_sort_de_l_enveloppe(self, plan):
        """Elasticite proche de -4 : l'optimum de Lerner tombe au-dela du palier
        le plus haut teste. La recommandation doit dire que c'est une hypothese
        de modele, pas une mesure."""
        analysis, reco = _decide(plan, {
            "ctl": 0.061, "m45": 0.084, "p45": 0.047, "p90": 0.037,
        }, volume=12_000)
        assert analysis.elasticity.optimal_is_extrapolated
        assert any("extrapolation" in note.lower() or "enveloppe" in note.lower()
                   for note in reco.caveats)

    def test_pas_de_reserve_d_extrapolation_quand_l_optimum_est_teste(self, plan):
        """Demande tres elastique : l'optimum tombe a l'interieur des paliers
        testes, donc il est soutenu par des observations."""
        analysis, reco = _decide(plan, {
            "ctl": 0.061, "m45": 0.1047, "p45": 0.0368, "p90": 0.0229,
        }, volume=12_000)
        borne_basse, borne_haute = analysis.elasticity.tested_range
        assert borne_basse <= analysis.elasticity.optimal_rate <= borne_haute
        assert not analysis.elasticity.optimal_is_extrapolated
        assert not any("extrapolation" in note.lower() for note in reco.caveats)

    def test_anti_selection_signalee_dans_les_reserves(self, plan):
        _, reco = _decide(plan, {
            "ctl": 0.061, "m45": 0.084, "p45": 0.047, "p90": 0.037,
        }, volume=12_000, pd_par_cellule={
            "ctl": 0.020, "m45": 0.019, "p45": 0.027, "p90": 0.033,
        })
        assert any("melange de risque" in note for note in reco.caveats)


def test_serialisation_pour_la_piste_d_audit(plan):
    _, reco = _decide(plan, {"ctl": 0.061, "m45": 0.084, "p45": 0.047, "p90": 0.037}, volume=12_000)
    payload = reco.to_dict()
    assert payload["verdict"] == "switch"
    assert isinstance(payload["rationale"], list) and payload["rationale"]
    assert payload["impact_basis"] == 10_000
    import json
    json.dumps(payload)  # doit etre serialisable sans encodeur specifique
