"""Laboratoire : le pre-mortem doit etre reproductible et honnete."""

import pytest

from gaap.services.simulation import SimulationInput, simulate


class TestReproductibilite:
    def test_meme_graine_meme_resultat(self, plan):
        params = SimulationInput(-3.5, 0.061, 40_000, replications=60)
        assert simulate(plan, params).verdict_counts == simulate(plan, params).verdict_counts

    def test_graine_differente_resultat_different(self, plan):
        a = simulate(plan, SimulationInput(-3.5, 0.061, 40_000, 60, seed=1))
        b = simulate(plan, SimulationInput(-3.5, 0.061, 40_000, 60, seed=2))
        assert a.learning_cost_mean != b.learning_cost_mean


class TestPuissance:
    def test_le_volume_augmente_la_puissance(self, plan):
        faible = simulate(plan, SimulationInput(-4.0, 0.061, 6_000, 80))
        fort = simulate(plan, SimulationInput(-4.0, 0.061, 80_000, 80))
        assert fort.power >= faible.power

    def test_la_cellule_optimale_est_identifiee(self, plan):
        """Avec une elasticite de -4 sur ce plan, la contribution est maximale au
        palier le plus haut : le laboratoire doit le savoir avant le test."""
        resultat = simulate(plan, SimulationInput(-4.0, 0.061, 80_000, 60))
        assert resultat.true_best_cell == "p90"
        assert resultat.power > 0.7

    def test_demande_tres_elastique_favorise_la_baisse(self, plan):
        resultat = simulate(plan, SimulationInput(-12.0, 0.061, 80_000, 40))
        assert resultat.true_best_cell == "m45"


class TestSorties:
    def test_quantiles_ordonnes(self, plan):
        resultat = simulate(plan, SimulationInput(-3.5, 0.061, 40_000, 80))
        assert resultat.learning_cost_p05 <= resultat.learning_cost_mean <= resultat.learning_cost_p95

    def test_elasticite_estimee_sans_biais_notable(self, plan):
        resultat = simulate(plan, SimulationInput(-3.5, 0.061, 120_000, 60))
        assert resultat.elasticity_mean == pytest.approx(-3.5, abs=0.25)

    def test_couverture_des_intervalles_proche_du_nominal(self, plan):
        """Une couverture tres eloignee de 95 % signalerait des intervalles qui
        mentent - defaut plus grave qu'un manque de puissance."""
        resultat = simulate(plan, SimulationInput(-3.5, 0.061, 120_000, 120))
        assert 0.80 <= resultat.elasticity_coverage <= 1.0

    def test_hypotheses_conservees_avec_le_resultat(self, plan):
        resultat = simulate(plan, SimulationInput(-3.5, 0.061, 40_000, 40))
        assert resultat.assumptions["true_elasticity"] == -3.5
        assert "elasticite constante" in resultat.assumptions["demand_model"].lower()

    def test_somme_des_verdicts_egale_le_nombre_de_replications(self, plan):
        resultat = simulate(plan, SimulationInput(-3.5, 0.061, 40_000, 50))
        assert sum(resultat.verdict_counts.values()) == 50
