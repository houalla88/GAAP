"""Moteur d'analyse : hierarchie des metriques, elasticite, anti-selection."""

import pytest

from gaap.domain.analysis import CellAggregate, analyse


def _aggregats(plan, take_ups: dict[str, float], volume: int = 8_000,
               pd_par_cellule: dict[str, float] | None = None):
    """Fabrique des agregats coherents a partir de take-up cibles."""
    pd_par_cellule = pd_par_cellule or {}
    out = []
    for cell in plan.cells:
        exposes = volume * 2 if cell.is_control else volume
        conversions = int(round(exposes * take_ups[cell.key]))
        pd_moyenne = pd_par_cellule.get(cell.key, 0.021)
        out.append(CellAggregate(
            cell_key=cell.key, exposed=exposes, conversions=conversions,
            pd_sum_exposed=exposes * 0.021, pd_sq_sum_exposed=exposes * (0.021 ** 2 + 1e-4),
            pd_sum_converted=conversions * pd_moyenne,
            pd_sq_sum_converted=conversions * (pd_moyenne ** 2 + 1e-4),
        ))
    return out


class TestHierarchieDesMetriques:
    def test_le_meilleur_take_up_n_est_pas_le_meilleur_prix(self, plan):
        """Le cas qui justifie l'existence de GAAP : un outil d'A/B testing
        generaliste designerait ici la cellule la moins chere."""
        analysis = analyse(plan, _aggregats(plan, {
            "ctl": 0.061, "m45": 0.084, "p45": 0.047, "p90": 0.037,
        }))
        assert analysis.best_by_take_up.cell.key == "m45"
        assert analysis.best_by_rac.cell.key == "p90"
        assert analysis.metric_conflict

    def test_contribution_suit_la_definition(self, plan):
        analysis = analyse(plan, _aggregats(plan, {
            "ctl": 0.06, "m45": 0.06, "p45": 0.06, "p90": 0.06,
        }))
        control = analysis.control_result
        attendu = 0.06 * (plan.control.rate - analysis.floor_rate) * plan.principal * plan.duration_factor
        assert control.rac_per_lead == pytest.approx(attendu, rel=1e-3)

    def test_cout_d_apprentissage_negatif_quand_le_test_rapporte(self, plan):
        analysis = analyse(plan, _aggregats(plan, {
            "ctl": 0.061, "m45": 0.084, "p45": 0.047, "p90": 0.037,
        }))
        assert analysis.learning_cost < 0  # le plan a cree de la valeur pendant le test

    def test_cout_d_apprentissage_positif_quand_le_test_coute(self, plan):
        analysis = analyse(plan, _aggregats(plan, {
            "ctl": 0.061, "m45": 0.065, "p45": 0.040, "p90": 0.030,
        }))
        assert analysis.learning_cost > 0


class TestIntegrite:
    def test_srm_conforme_sur_une_allocation_respectee(self, plan):
        analysis = analyse(plan, _aggregats(plan, {k.key: 0.06 for k in plan.cells}))
        assert analysis.srm.passed

    def test_srm_detecte_une_cellule_amputee(self, plan):
        aggregats = _aggregats(plan, {k.key: 0.06 for k in plan.cells})
        ampute = [
            CellAggregate(a.cell_key, int(a.exposed * 0.8), int(a.conversions * 0.8),
                          a.pd_sum_exposed, a.pd_sq_sum_exposed,
                          a.pd_sum_converted, a.pd_sq_sum_converted)
            if a.cell_key == "p45" else a
            for a in aggregats
        ]
        analysis = analyse(plan, ampute)
        assert not analysis.srm.passed
        assert analysis.warnings and "SRM" in analysis.warnings[0]


class TestElasticite:
    def test_la_pente_vraie_est_retrouvee(self, plan):
        """Take-up construits sur une elasticite exacte de -4 : l'estimation doit
        la retrouver a la precision de l'echantillonnage pres."""
        reference = plan.control.rate
        vraies = {
            cell.key: 0.061 * (cell.rate / reference) ** -4.0
            for cell in plan.cells
        }
        analysis = analyse(plan, _aggregats(plan, vraies, volume=60_000))
        assert analysis.elasticity is not None
        assert analysis.elasticity.value == pytest.approx(-4.0, abs=0.05)
        assert analysis.elasticity.r_squared > 0.99
        assert analysis.elasticity.ci_low < -4.0 < analysis.elasticity.ci_high

    def test_extrapolation_signalee_hors_enveloppe(self, plan):
        analysis = analyse(plan, _aggregats(plan, {
            "ctl": 0.061, "m45": 0.066, "p45": 0.056, "p90": 0.052,
        }))
        elasticity = analysis.elasticity
        assert elasticity.optimal_rate is not None
        borne_basse, borne_haute = elasticity.tested_range
        dedans = borne_basse <= elasticity.optimal_rate <= borne_haute
        assert elasticity.optimal_is_extrapolated == (not dedans)

    def test_deux_cellules_donnent_une_elasticite_d_arc_sans_incertitude(self, plan):
        duo = plan.with_status(plan.status, cells=plan.cells[:2])
        analysis = analyse(duo, _aggregats(duo, {"ctl": 0.061, "m45": 0.084}))
        assert analysis.elasticity.points == 2
        assert analysis.elasticity.std_error == 0.0
        assert "arc" in analysis.elasticity.method.lower()


class TestAntiSelection:
    def test_derive_de_pd_detectee(self, plan):
        """Signal propre au credit : le prix monte, les dossiers acceptes se degradent."""
        analysis = analyse(plan, _aggregats(
            plan, {"ctl": 0.061, "m45": 0.084, "p45": 0.047, "p90": 0.037},
            pd_par_cellule={"ctl": 0.020, "m45": 0.019, "p45": 0.026, "p90": 0.031},
        ))
        assert analysis.adverse_selection_alert
        degrades = [r for r in analysis.results if r.adverse_selection]
        assert {r.cell.key for r in degrades} >= {"p90"}
        assert all(r.pd_drift_bp > 0 for r in degrades)

    def test_pas_d_alerte_quand_le_melange_est_stable(self, plan):
        analysis = analyse(plan, _aggregats(
            plan, {"ctl": 0.061, "m45": 0.084, "p45": 0.047, "p90": 0.037},
            pd_par_cellule={k.key: 0.021 for k in plan.cells},
        ))
        assert not analysis.adverse_selection_alert


class TestSequentiel:
    def test_la_frontiere_se_detend_avec_l_information(self, plan):
        petit = analyse(plan, _aggregats(plan, {k.key: 0.06 for k in plan.cells}, volume=500))
        grand = analyse(plan, _aggregats(plan, {k.key: 0.06 for k in plan.cells}, volume=8_000))
        assert petit.information_fraction < grand.information_fraction
        assert petit.boundary > grand.boundary

    def test_alpha_est_corrige_du_nombre_de_comparaisons(self, plan):
        analysis = analyse(plan, _aggregats(plan, {k.key: 0.06 for k in plan.cells}))
        assert analysis.alpha_adjusted == pytest.approx(plan.alpha / 3)
