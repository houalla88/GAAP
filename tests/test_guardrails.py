"""Garde-fous : ce que le moteur doit refuser."""

import pytest

from gaap.domain import guardrails
from gaap.domain.analysis import CellAggregate, analyse
from gaap.domain.guardrails import Severity
from gaap.domain.models import PriceCell


def _check(report, code):
    return next(c for c in report.checks if c.code == code)


class TestAvantLancement:
    def test_un_plan_sain_est_admissible(self, plan):
        assert guardrails.pre_launch(plan).cleared

    def test_cellule_sous_le_plancher_bloque(self, plan):
        casse = plan.with_status(plan.status, cells=(
            plan.control, PriceCell("appel", "Prix d'appel", 2.10, 0.30),
        ))
        report = guardrails.pre_launch(casse)
        assert not report.cleared
        assert not _check(report, "ECO_FLOOR").passed
        assert _check(report, "ECO_FLOOR").severity is Severity.BLOCKING

    def test_la_remise_sur_lot_compte_dans_le_prix_effectif(self, plan):
        """Le prix est la somme des leviers : une remise de conditionnement peut
        faire passer sous le plancher une cellule dont le prix affiche est
        admissible. Les traiter separement laisserait passer le plan."""
        floor = plan.price_floor.total
        piege = plan.with_status(plan.status, cells=(
            plan.control,
            PriceCell("lot", "Remise lot", floor + 0.05, 0.30, pack_discount=0.30),
        ))
        assert not _check(guardrails.pre_launch(piege), "ECO_FLOOR").passed

    def test_amplitude_hors_bande_bloque(self, plan):
        serre = plan.with_status(plan.status, max_delta_cents=15.0)
        assert not _check(guardrails.pre_launch(serre), "ECO_BAND").passed

    def test_exposition_plafonnee(self, plan):
        serre = plan.with_status(plan.status, max_exposure=0.20)
        assert not _check(guardrails.pre_launch(serre), "RISK_EXPOSURE").passed

    @pytest.mark.parametrize("regle", [
        "clientele_age_senior", "quartiers_origine_immigree", "magasins_revenu_sexe_feminin",
        "zones_religion_majoritaire",
    ])
    def test_ciblage_sur_critere_protege_bloque(self, plan, regle):
        """Differencier le prix selon la composition sociale d'un quartier
        tombe sous le coup du droit anti-discrimination, meme sans intention."""
        cible = plan.with_status(plan.status, targeting=(regle,))
        check = _check(guardrails.pre_launch(cible), "COMP_PROTECTED")
        assert not check.passed and check.severity is Severity.BLOCKING

    def test_ciblage_metier_legitime_passe(self, plan):
        cible = plan.with_status(plan.status, targeting=("hypermarche", "region_flandre"))
        assert _check(guardrails.pre_launch(cible), "COMP_PROTECTED").passed

    def test_auto_validation_refusee(self, plan):
        seul = plan.with_status(plan.status, created_by="analyste", approved_by="analyste")
        assert not _check(guardrails.pre_launch(seul), "GOV_FOUR_EYES").passed

    def test_absence_de_validation_refusee(self, plan):
        brut = plan.with_status(plan.status, approved_by="")
        assert not _check(guardrails.pre_launch(brut), "GOV_FOUR_EYES").passed

    def test_plan_tres_sous_dimensionne_est_bloquant(self, plan):
        # Sous la moitie du volume requis, le plan ne peut rien mesurer.
        maigre = plan.with_status(plan.status, planned_volume=3_000)
        check = _check(guardrails.pre_launch(maigre), "STAT_POWER")
        assert not check.passed and check.severity is Severity.BLOCKING

    def test_plan_legerement_sous_dimensionne_est_un_avertissement(self, plan):
        """Nuance deliberee : un pilote volontairement court reste lançable, mais
        il doit etre assume explicitement."""
        requis = _check(guardrails.pre_launch(plan), "STAT_POWER")
        assert requis.passed
        limite = plan.with_status(plan.status, planned_volume=5_000)
        check = _check(guardrails.pre_launch(limite), "STAT_POWER")
        assert not check.passed and check.severity is Severity.WARNING
        assert guardrails.pre_launch(limite).cleared

    def test_absence_de_temoin_avertit_sans_bloquer(self, plan):
        sans = plan.with_status(plan.status, holdout_share=0.0)
        assert not _check(guardrails.pre_launch(sans), "STAT_HOLDOUT").passed
        assert guardrails.pre_launch(sans).cleared


class TestEnProduction:
    def _analysis(self, plan, taux, volume=12_000):
        aggregats = [
            CellAggregate(c.key, n := volume * (2 if c.is_control else 1),
                          int(round(n * taux[c.key])), 0.0, 0.0, 0.0, 0.0)
            for c in plan.cells
        ]
        return analyse(plan, aggregats)

    def _isoelastique(self, plan, e, base=0.82):
        ref = plan.control.effective_price
        return {c.key: min(0.99, base * (c.effective_price / ref) ** e) for c in plan.cells}

    def test_situation_nominale(self, plan):
        assert guardrails.runtime(self._analysis(plan, self._isoelastique(plan, -0.7))).cleared

    def test_arret_de_protection_sur_perte_avertie(self, plan):
        serre = plan.with_status(plan.status, loss_tolerance_per_unit=0.01)
        analysis = self._analysis(serre, self._isoelastique(serre, -2.5))
        report = guardrails.runtime(analysis)
        assert not report.cleared
        assert not _check(report, "ECO_STOPLOSS").passed

    def test_la_tolerance_est_lue_dans_le_plan(self, plan):
        """La tolerance est une decision de comite prise avant de voir les
        resultats : elle vit dans le plan, pas dans un argument d'appel."""
        analysis = self._analysis(plan, self._isoelastique(plan, -0.7))
        assert guardrails.runtime(analysis).cleared                 # tolerance du plan : 0,12 EUR
        assert not guardrails.runtime(analysis, 0.01).cleared       # politique alternative

    def test_cellule_passee_sous_son_plancher_faute_de_rotation(self, plan):
        """Le plancher monte quand la rotation ralentit : une cellule peut le
        franchir sans qu'aucun prix n'ait bouge."""
        taux = {c.key: 0.82 for c in plan.cells}
        taux["p40"] = 0.22
        report = guardrails.runtime(self._analysis(plan, taux))
        assert not _check(report, "ECO_FLOOR_LIVE").passed

    def test_srm_bloque_la_lecture(self, plan):
        aggregats = [
            CellAggregate(c.key,
                          24_000 if c.is_control else (6_000 if c.key == "p20" else 12_000),
                          5_000, 0.0, 0.0, 0.0, 0.0)
            for c in plan.cells
        ]
        report = guardrails.runtime(analyse(plan, aggregats))
        assert not _check(report, "STAT_SRM").passed
