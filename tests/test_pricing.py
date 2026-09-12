"""Modele economique : plancher, marge, contribution, regle de Lerner."""

import pytest

from gaap.domain.pricing import (CostStack, compute_price_floor, contribution_per_unit_presented,
                                 lerner_optimal_price, margin_per_unit_sold,
                                 return_on_working_capital)


class TestStructureDeCout:
    def test_freinte_divise_plutot_qu_elle_ne_soustrait(self, cost):
        """Si 6 % du poids livre part au parage, il faut acheter 1 / 0,94 kilo
        pour en presenter un. Soustraire la freinte serait une sous-estimation."""
        brut = cost.purchase_cost + cost.logistics_cost + cost.handling_cost
        assert cost.acquisition_cost == pytest.approx(brut / 0.94)
        assert cost.acquisition_cost > brut

    def test_cotes_d_invendu(self, cost):
        """A 82 % d'ecoulement, chaque kilo vendu traîne 0,22 kilo d'invendu."""
        assert cost.waste_odds == pytest.approx(0.18 / 0.82)

    def test_perte_attendue_est_l_analogue_de_pd_fois_lgd(self, cost):
        """Probabilite d'echec multipliee par la perte encourue en cas d'echec."""
        attendu = cost.waste_odds * (cost.acquisition_cost - cost.salvage_value)
        assert cost.expected_waste_loss == pytest.approx(attendu)

    def test_valeur_de_sauvetage_reduit_la_perte(self, cost):
        sans_sauvetage = CostStack(
            cost.purchase_cost, cost.logistics_cost, cost.handling_cost,
            cost.known_shrink, 0.0, cost.expected_sell_through, cost.capital_cost,
        )
        assert sans_sauvetage.expected_waste_loss > cost.expected_waste_loss


class TestPlancher:
    def test_decomposition_recalculee_a_la_main(self, cost):
        """Le plancher doit etre reconstituable poste par poste par un controleur."""
        floor = compute_price_floor(cost)
        assert floor.purchase == pytest.approx(1.45 / 0.94)
        assert floor.logistics == pytest.approx(0.18 / 0.94)
        assert floor.handling == pytest.approx(0.22 / 0.94)
        assert floor.waste == pytest.approx(cost.expected_waste_loss)
        assert floor.capital == pytest.approx(0.012)

    def test_somme_des_composantes_egale_le_total(self, cost):
        floor = compute_price_floor(cost)
        assert sum(v for _, v in floor.components) == pytest.approx(floor.total)

    def test_valeur_de_reference(self, cost):
        """Valeur figee : toute derive du modele doit etre visible."""
        assert compute_price_floor(cost).total == pytest.approx(2.3902, abs=5e-4)

    def test_le_plancher_monte_quand_la_rotation_ralentit(self, cost):
        """Propriete distinctive du perissable : le plancher depend du prix,
        parce que la rotation depend du prix et que la casse depend de la
        rotation."""
        rapide = compute_price_floor(cost, 0.95).total
        nominal = compute_price_floor(cost, 0.82).total
        lente = compute_price_floor(cost, 0.65).total
        assert rapide < nominal < lente
        assert lente / rapide > 1.3  # l'effet est massif, pas marginal

    def test_ecoulement_parfait_supprime_la_perte_sur_invendus(self, cost):
        floor = compute_price_floor(cost, 1.0)
        assert floor.waste == pytest.approx(0.0)
        assert floor.total == pytest.approx(cost.acquisition_cost + cost.capital_cost)


class TestContribution:
    def test_marge_nulle_au_plancher(self, cost):
        floor = compute_price_floor(cost).total
        assert margin_per_unit_sold(floor, floor) == pytest.approx(0.0)

    def test_contribution_nulle_au_plancher_du_taux_correspondant(self, cost):
        """Coherence du modele : au plancher calcule pour un taux donne, la
        contribution par kilo presente est nulle a ce taux."""
        for rate in (0.60, 0.82, 0.95):
            floor = compute_price_floor(cost, rate).total
            assert contribution_per_unit_presented(rate, floor, floor) == pytest.approx(0.0)

    def test_forme_lineaire_en_ecoulement(self, cost):
        """C = s x V + K, avec V la valeur d'une vente et K la perte seche d'un
        invendu. La linearite en s est ce qui donne la variance en forme fermee."""
        floor = compute_price_floor(cost).total
        prix = 2.95
        v = prix - cost.salvage_value - cost.capital_cost
        k = cost.salvage_value - cost.acquisition_cost
        for rate in (0.5, 0.7, 0.9):
            direct = contribution_per_unit_presented(rate, prix, compute_price_floor(cost, rate).total)
            assert direct == pytest.approx(rate * v + k, abs=1e-9)

    def test_contribution_croit_avec_le_prix_en_demande_inelastique(self, cost):
        """A ecoulement peu sensible, monter le prix augmente la contribution :
        c'est le cas qui rend un test tarifaire interessant."""
        faible = contribution_per_unit_presented(0.86, 2.75, compute_price_floor(cost, 0.86).total)
        eleve = contribution_per_unit_presented(0.75, 3.35, compute_price_floor(cost, 0.75).total)
        assert eleve > faible


class TestRendement:
    def test_rendement_au_plancher_vaut_un(self, cost):
        """Propriete structurante : au plancher, le capital immobilise est
        rembourse sans remuneration."""
        floor = compute_price_floor(cost).total
        assert return_on_working_capital(floor, cost) == pytest.approx(1.0, abs=1e-9)

    def test_rendement_croit_avec_le_prix(self, cost):
        assert return_on_working_capital(3.35, cost) > return_on_working_capital(2.95, cost)


class TestLerner:
    def test_pas_d_optimum_en_demande_inelastique(self):
        """|e| <= 1 : la recette croit indefiniment avec le prix, l'optimum
        interieur n'existe pas. Retourner une valeur serait un faux."""
        assert lerner_optimal_price(-0.8, 2.39) is None
        assert lerner_optimal_price(-1.0, 2.39) is None

    def test_taux_de_marge_optimal_vaut_moins_un_sur_e(self):
        cout = 2.39
        for elasticite in (-1.5, -2.0, -4.0, -8.0):
            optimal = lerner_optimal_price(elasticite, cout)
            assert (optimal - cout) / optimal == pytest.approx(-1.0 / elasticite)

    def test_l_optimum_se_rapproche_du_cout_quand_la_demande_s_elastifie(self):
        assert lerner_optimal_price(-20.0, 2.39) < lerner_optimal_price(-2.0, 2.39)
