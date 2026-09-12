"""Proprietes du moteur d'affectation.

Ces tests ne verifient pas un comportement, ils verifient des *proprietes* : la
stabilite, l'uniformite et l'independance sont des garanties qui doivent tenir
pour tout sujet, pas pour trois exemples choisis.
"""

import statistics

import pytest

from gaap.domain.allocation import AllocationOutcome, allocation_profile, assign, uniform_bucket
from gaap.domain.models import ExperimentStatus
from gaap.domain.stats import chi_square_goodness_of_fit


class TestDeterminisme:
    def test_meme_sujet_meme_cellule(self, plan):
        """Un client qui revient doit revoir le meme prix - exigence commerciale
        autant que reglementaire sur l'information precontractuelle."""
        for i in range(200):
            sujet = f"CLI-{i:06d}"
            assert assign(plan, sujet).cell_key == assign(plan, sujet).cell_key

    def test_le_sel_re_randomise(self, plan):
        """Deux experiences differentes ne doivent pas reutiliser la meme partition."""
        autre = plan.with_status(plan.status, salt="autre-sel")
        differences = sum(
            1 for i in range(2_000)
            if assign(plan, f"S{i}").cell_key != assign(autre, f"S{i}").cell_key
        )
        assert differences > 800  # environ 1 - 1/4 des sujets changent de cellule

    def test_ordre_de_declaration_sans_effet(self, plan):
        """Reordonner les cellules dans le plan ne doit pas deplacer un seul sujet."""
        inverse = plan.with_status(plan.status, cells=tuple(reversed(plan.cells)))
        for i in range(500):
            assert assign(plan, f"S{i}").cell_key == assign(inverse, f"S{i}").cell_key


class TestUniformite:
    def test_repartition_conforme_aux_poids(self, plan):
        profil = allocation_profile(plan, 40_000)
        observes = [profil[cell.key] for cell in plan.cells]
        _, _, p_value = chi_square_goodness_of_fit(observes, [c.weight for c in plan.cells])
        assert p_value > 0.01  # aucune derive systematique de l'allocation

    def test_part_du_temoin_respectee(self, plan):
        profil = allocation_profile(plan, 40_000)
        assert profil["_holdout"] / 40_000 == pytest.approx(plan.holdout_share, abs=0.005)

    def test_tirage_uniforme_sur_zero_un(self, plan):
        tirages = [uniform_bucket(plan.salt, "cell", f"S{i}") for i in range(20_000)]
        assert statistics.mean(tirages) == pytest.approx(0.5, abs=0.01)
        assert statistics.pstdev(tirages) == pytest.approx(1 / 12 ** 0.5, abs=0.01)
        assert min(tirages) < 0.001 and max(tirages) > 0.999


class TestIndependance:
    def test_temoin_et_cellule_sont_decorreles(self, plan):
        """Si les deux tirages partageaient un flux, le temoin serait correle au
        prix - biais invisible dans les totaux et fatal a l'interpretation."""
        paires = [
            (uniform_bucket(plan.salt, "holdout", f"S{i}"),
             uniform_bucket(plan.salt, "cell", f"S{i}"))
            for i in range(20_000)
        ]
        xs, ys = zip(*paires)
        mx, my = statistics.mean(xs), statistics.mean(ys)
        covariance = sum((x - mx) * (y - my) for x, y in paires) / len(paires)
        correlation = covariance / (statistics.pstdev(xs) * statistics.pstdev(ys))
        assert abs(correlation) < 0.03


class TestExclusions:
    def test_segment_exclu_recoit_le_prix_de_reference(self, plan):
        protege = plan.with_status(plan.status, excluded_segments=("surendettement",))
        result = assign(protege, "CLI-000001", segment="surendettement")
        assert result.outcome is AllocationOutcome.EXCLUDED
        assert result.rate == plan.control.rate
        assert not result.in_analysis

    def test_exclusion_prime_sur_le_tirage(self, plan):
        """L'ordre des controles garantit qu'un segment protege ne peut jamais
        etre expose, meme si les poids sont mal configures."""
        protege = plan.with_status(plan.status, excluded_segments=("fragile",))
        for i in range(500):
            assert assign(protege, f"S{i}", segment="fragile").cell_key == plan.control.key

    def test_hors_perimetre_quand_un_ciblage_existe(self, plan):
        cible = plan.with_status(plan.status, targeting=("canal_direct",))
        assert assign(cible, "S1", segment="courtier").outcome is AllocationOutcome.NOT_TARGETED
        assert assign(cible, "S1", segment="canal_direct").outcome is AllocationOutcome.ASSIGNED

    def test_experience_inactive_sert_le_prix_courant(self, plan):
        brouillon = plan.with_status(ExperimentStatus.DRAFT)
        result = assign(brouillon, "S1")
        assert result.outcome is AllocationOutcome.NOT_LIVE
        assert result.rate == plan.control.rate

    def test_temoin_est_hors_analyse(self, plan):
        temoins = [
            assign(plan, f"S{i}") for i in range(3_000)
            if assign(plan, f"S{i}").outcome is AllocationOutcome.HOLDOUT
        ]
        assert temoins
        assert all(not t.in_analysis and t.rate == plan.control.rate for t in temoins)


def test_stabilite_inter_versions(plan):
    """Empreinte figee de l'affectation.

    Ce test echoue si une modification du hachage deplace des sujets. C'est
    volontaire : changer la fonction d'affectation invalide silencieusement
    toute experience en cours, et doit donc etre un acte delibere.
    """
    assert [assign(plan, f"ancre-{i}").cell_key for i in range(8)] == [
        "ctl", "m45", "m45", "m45", "ctl", "p45", "ctl", "ctl",
    ]
