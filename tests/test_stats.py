"""Verification des primitives statistiques contre des valeurs de reference.

Les valeurs attendues proviennent de tables publiees ou de logiciels de
reference (R, scipy), pas d'une execution anterieure de ce code : un test qui
compare le code a lui-meme ne verifie rien.
"""

import math

import pytest

from gaap.domain import stats


class TestDistributions:
    @pytest.mark.parametrize("p, expected", [
        (0.975, 1.959964), (0.95, 1.644854), (0.99, 2.326348), (0.5, 0.0), (0.025, -1.959964),
    ])
    def test_quantile_normal(self, p, expected):
        assert stats.norm_ppf(p) == pytest.approx(expected, abs=1e-5)

    def test_cdf_et_quantile_sont_reciproques(self):
        for value in (-3.1, -0.4, 0.0, 1.2, 2.8):
            assert stats.norm_ppf(stats.norm_cdf(value)) == pytest.approx(value, abs=1e-9)

    @pytest.mark.parametrize("x, df, expected", [
        (3.841459, 1, 0.05), (5.991465, 2, 0.05), (7.814728, 3, 0.05), (11.070498, 5, 0.05),
    ])
    def test_survie_chi2(self, x, df, expected):
        assert stats.chi2_sf(x, df) == pytest.approx(expected, abs=1e-5)

    @pytest.mark.parametrize("t, df, expected", [
        (2.228139, 10, 0.05), (2.086, 20, 0.05), (1.959964, 100000, 0.05),
    ])
    def test_survie_student(self, t, df, expected):
        assert 2 * stats.student_t_sf(t, df) == pytest.approx(expected, abs=1e-4)

    def test_student_converge_vers_la_normale(self):
        assert stats.student_t_sf(1.96, 1e7) == pytest.approx(1 - stats.norm_cdf(1.96), abs=1e-5)


class TestIntervalles:
    def test_wilson_reste_dans_zero_un(self):
        low, high = stats.wilson_interval(0, 50)
        assert low == 0.0 and 0.0 < high < 1.0

    def test_wilson_valeur_de_reference(self):
        # Agresti & Coull (1998), exemple classique : 10 succes sur 100.
        low, high = stats.wilson_interval(10, 100, 0.05)
        assert low == pytest.approx(0.0554, abs=5e-4)
        assert high == pytest.approx(0.1744, abs=5e-4)

    def test_wilson_se_resserre_avec_la_taille(self):
        petit = stats.wilson_interval(50, 500)
        grand = stats.wilson_interval(500, 5000)
        assert (grand[1] - grand[0]) < (petit[1] - petit[0])

    def test_newcombe_encadre_la_difference_observee(self):
        low, high = stats.newcombe_difference_interval(480, 10_000, 540, 10_000)
        difference = 540 / 10_000 - 480 / 10_000
        assert low < difference < high

    def test_newcombe_exclut_zero_sur_un_ecart_massif(self):
        low, high = stats.newcombe_difference_interval(400, 10_000, 900, 10_000)
        assert low > 0


class TestTests:
    def test_proportions_identiques_ne_sont_pas_significatives(self):
        result = stats.two_proportion_ztest(500, 10_000, 500, 10_000)
        assert result.z == pytest.approx(0.0, abs=1e-9)
        assert result.p_value == pytest.approx(1.0, abs=1e-9)
        assert not result.significant

    def test_ecart_franc_est_detecte(self):
        result = stats.two_proportion_ztest(600, 10_000, 300, 10_000)
        assert result.significant
        assert result.relative_lift == pytest.approx(-0.5, abs=1e-9)
        assert result.ci_high < 0

    def test_welch_supporte_des_variances_inegales(self):
        result = stats.welch_ttest(10.0, 4.0, 500, 12.0, 36.0, 500)
        assert result.difference == pytest.approx(2.0)
        assert result.df < 998  # correction de Welch-Satterthwaite appliquee
        assert result.significant

    def test_srm_conforme_sur_une_allocation_exacte(self):
        stat, df, p = stats.chi_square_goodness_of_fit([2500] * 4, [0.25] * 4)
        assert stat == pytest.approx(0.0) and df == 3 and p == pytest.approx(1.0)

    def test_srm_detecte_une_fuite_de_trafic(self):
        stat, df, p = stats.chi_square_goodness_of_fit([5000, 4000], [0.5, 0.5])
        assert p < 1e-20 and stat > 100


class TestDimensionnement:
    def test_bonferroni_divise_le_risque(self):
        assert stats.bonferroni(0.05, 3) == pytest.approx(0.05 / 3)
        assert stats.bonferroni(0.05, 0) == pytest.approx(0.05)

    def test_taille_requise_croit_quand_l_effet_diminue(self):
        grand_effet = stats.required_sample_size_per_arm(0.06, 0.20)
        petit_effet = stats.required_sample_size_per_arm(0.06, 0.05)
        assert petit_effet > grand_effet * 10

    def test_taille_requise_valeur_de_reference(self):
        """Controle contre la formule de Fleiss recalculee independamment.

        p1 = 6 %, p2 = 7,2 % (20 % relatif), alpha = 5 % bilateral, puissance 80 % :

            n = (z_a x sqrt(2 p_bar q_bar) + z_b x sqrt(p1 q1 + p2 q2))^2 / (p1 - p2)^2
        """
        p1, p2 = 0.06, 0.072
        p_bar = (p1 + p2) / 2
        attendu = math.ceil(
            (stats.norm_ppf(0.975) * math.sqrt(2 * p_bar * (1 - p_bar))
             + stats.norm_ppf(0.80) * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2
            / (p2 - p1) ** 2
        )
        assert attendu == 6719  # valeur figee : toute derive doit etre visible
        assert stats.required_sample_size_per_arm(0.06, 0.20, 0.05, 0.80) == attendu

    def test_mde_et_taille_requise_sont_coherents(self):
        n = stats.required_sample_size_per_arm(0.06, 0.15, 0.05, 0.80)
        assert stats.detectable_effect(0.06, n, 0.05, 0.80) == pytest.approx(0.15, rel=0.05)


class TestSequentiel:
    def test_frontiere_est_conservatrice_au_debut(self):
        assert stats.obrien_fleming_bound(0.1) > stats.obrien_fleming_bound(0.5)
        assert stats.obrien_fleming_bound(0.5) > stats.obrien_fleming_bound(1.0)

    def test_frontiere_converge_vers_le_seuil_nominal(self):
        assert stats.obrien_fleming_bound(1.0, 0.05) == pytest.approx(1.959964, abs=1e-5)

    def test_frontiere_suit_la_forme_en_racine(self):
        assert stats.obrien_fleming_bound(0.25, 0.05) == pytest.approx(
            stats.obrien_fleming_bound(1.0, 0.05) * 2.0, rel=1e-9
        )


class TestBayesien:
    def test_egalite_donne_une_chance_sur_deux(self):
        assert stats.prob_b_beats_a(500, 10_000, 500, 10_000) == pytest.approx(0.5, abs=0.02)

    def test_superiorite_franche_est_quasi_certaine(self):
        assert stats.prob_b_beats_a(300, 10_000, 900, 10_000) > 0.999

    def test_bascule_sur_l_approximation_normale_sur_gros_volumes(self):
        # Au-dela de 50 000 succes, la forme fermee cede a l'approximation.
        value = stats.prob_b_beats_a(60_000, 1_000_000, 61_000, 1_000_000)
        assert 0.99 < value <= 1.0

    def test_perte_attendue_est_reproductible(self):
        premiere = stats.expected_loss_choosing_b(480, 10_000, 540, 10_000)
        seconde = stats.expected_loss_choosing_b(480, 10_000, 540, 10_000)
        assert premiere == seconde

    def test_perte_attendue_est_faible_quand_b_domine(self):
        assert stats.expected_loss_choosing_b(300, 10_000, 900, 10_000) < 1e-4

    def test_perte_attendue_est_positive_quand_a_domine(self):
        assert stats.expected_loss_choosing_b(900, 10_000, 300, 10_000) > 0.05


def test_aucune_fonction_ne_renvoie_de_nan():
    """Garde-fou global : une NaN qui remonte jusqu'a un comite est indetectable."""
    valeurs = [
        stats.norm_cdf(0.3), stats.chi2_sf(2.0, 3), stats.student_t_sf(1.0, 7),
        stats.obrien_fleming_bound(0.4), stats.detectable_effect(0.05, 1000),
        stats.prob_b_beats_a(10, 100, 12, 100),
    ]
    assert all(not math.isnan(v) for v in valeurs)
