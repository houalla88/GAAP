"""Modele economique : plancher, contribution, RAROC, regle de Lerner."""

import pytest

from gaap.domain.pricing import (CostOfRisk, compute_price_floor, contribution_per_contract,
                                 contribution_per_lead, lerner_optimal_price, raroc)


class TestPlancher:
    def test_decomposition_recalculee_a_la_main(self, cost):
        """Le plancher doit etre reconstituable poste par poste par un controleur."""
        floor = compute_price_floor(cost)
        assert floor.funding == pytest.approx(0.0285)
        assert floor.operating == pytest.approx(0.0110)
        assert floor.expected_loss == pytest.approx(0.0210 * 0.62)          # PD x LGD
        assert floor.capital == pytest.approx(0.75 * 0.125 * (0.110 - 0.0285))
        assert floor.total == pytest.approx(0.0285 + 0.0110 + 0.01302 + 0.00764063, abs=1e-7)

    def test_somme_des_composantes_egale_le_total(self, cost):
        floor = compute_price_floor(cost)
        assert sum(v for _, v in floor.components) == pytest.approx(floor.total)

    def test_hausse_de_pd_releve_le_plancher(self, cost):
        base = compute_price_floor(cost).total
        degrade = compute_price_floor(
            CostOfRisk(cost.funding_rate, cost.operating_cost_rate, cost.pd * 2, cost.lgd,
                       cost.risk_weight, cost.capital_ratio, cost.hurdle_rate)
        ).total
        assert degrade - base == pytest.approx(cost.pd * cost.lgd)

    def test_capital_sans_surcout_quand_le_hurdle_egale_le_refinancement(self, cost):
        neutre = CostOfRisk(0.05, 0.01, 0.02, 0.5, hurdle_rate=0.05)
        assert compute_price_floor(neutre).capital == pytest.approx(0.0)

    def test_le_cout_du_capital_ne_devient_jamais_negatif(self):
        """Un hurdle inferieur au refinancement est une incoherence de parametrage :
        le plancher ne doit pas s'en trouver artificiellement abaisse."""
        incoherent = CostOfRisk(0.06, 0.01, 0.02, 0.5, hurdle_rate=0.03)
        assert compute_price_floor(incoherent).capital == 0.0


class TestContribution:
    def test_contribution_nulle_au_plancher(self, cost):
        floor = compute_price_floor(cost).total
        assert contribution_per_contract(floor, floor, 12_500, 2.4) == pytest.approx(0.0)

    def test_contribution_negative_sous_le_plancher(self, cost):
        floor = compute_price_floor(cost).total
        assert contribution_per_contract(floor - 0.005, floor, 12_500, 2.4) < 0

    def test_contribution_par_lead_est_ponderee_par_le_take_up(self, cost):
        floor = compute_price_floor(cost).total
        par_contrat = contribution_per_contract(0.069, floor, 12_500, 2.4)
        assert contribution_per_lead(0.06, 0.069, floor, 12_500, 2.4) == pytest.approx(
            0.06 * par_contrat
        )

    def test_la_duree_change_l_echelle_de_la_marge(self, cost):
        """60 bps sur 12 mois et 60 bps sur 84 mois ne valent pas la meme chose."""
        floor = compute_price_floor(cost).total
        court = contribution_per_contract(0.069, floor, 12_500, 1.0)
        long = contribution_per_contract(0.069, floor, 12_500, 3.5)
        assert long == pytest.approx(court * 3.5)


class TestRaroc:
    def test_raroc_au_plancher_egale_le_hurdle(self, cost):
        """Propriete structurante : le plancher est par construction le prix qui
        rend exactement le cout des fonds propres."""
        floor = compute_price_floor(cost).total
        assert raroc(floor, cost) == pytest.approx(cost.hurdle_rate, abs=1e-9)

    def test_raroc_croit_avec_le_prix(self, cost):
        assert raroc(0.078, cost) > raroc(0.069, cost) > raroc(0.0645, cost)


class TestLerner:
    def test_pas_d_optimum_en_demande_inelastique(self):
        """|e| <= 1 : la recette croit indefiniment avec le prix, l'optimum
        interieur n'existe pas. Retourner une valeur serait un faux."""
        assert lerner_optimal_price(-0.8, 0.06) is None
        assert lerner_optimal_price(-1.0, 0.06) is None

    def test_taux_de_marge_optimal_vaut_moins_un_sur_e(self):
        cout = 0.06
        for elasticite in (-1.5, -2.0, -4.0, -8.0):
            optimal = lerner_optimal_price(elasticite, cout)
            assert (optimal - cout) / optimal == pytest.approx(-1.0 / elasticite)

    def test_l_optimum_se_rapproche_du_cout_quand_la_demande_s_elastifie(self):
        assert lerner_optimal_price(-20.0, 0.06) < lerner_optimal_price(-2.0, 0.06)
