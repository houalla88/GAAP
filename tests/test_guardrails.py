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
            plan.control, PriceCell("bas", "Taux d'appel", 0.045, 0.30),
        ))
        report = guardrails.pre_launch(casse)
        assert not report.cleared
        assert not _check(report, "ECO_FLOOR").passed
        assert _check(report, "ECO_FLOOR").severity is Severity.BLOCKING

    def test_frais_compensent_partiellement_un_taux_sous_le_plancher(self, plan):
        """Le prix est la somme des leviers : un taux legerement bas peut rester
        admissible si des frais de dossier le compensent. Les traiter separement
        conduirait a refuser un plan sain ou a accepter un plan destructeur."""
        floor = plan.price_floor.total
        equivalent = 200.0 / (plan.principal * plan.duration_factor)
        limite = plan.with_status(plan.status, cells=(
            plan.control,
            PriceCell("mix", "Taux bas + frais", floor - equivalent + 0.0005, 0.30, fee=200.0),
        ))
        assert _check(guardrails.pre_launch(limite), "ECO_FLOOR").passed

    def test_amplitude_hors_bande_bloque(self, plan):
        large = plan.with_status(plan.status, max_delta_bp=50.0)
        assert not _check(guardrails.pre_launch(large), "ECO_BAND").passed

    def test_exposition_plafonnee(self, plan):
        serre = plan.with_status(plan.status, max_exposure=0.20)
        assert not _check(guardrails.pre_launch(serre), "RISK_EXPOSURE").passed

    @pytest.mark.parametrize("regle", [
        "age_moins_de_30", "clients_femmes", "segment_nationalite_ue", "etat_de_sante",
    ])
    def test_ciblage_sur_critere_protege_bloque(self, plan, regle):
        """Une differenciation tarifaire sur un critere protege est prohibee ;
        la detecter apres coup, c'est la detecter en contentieux."""
        cible = plan.with_status(plan.status, targeting=(regle,))
        check = _check(guardrails.pre_launch(cible), "COMP_PROTECTED")
        assert not check.passed and check.severity is Severity.BLOCKING

    def test_ciblage_metier_legitime_passe(self, plan):
        cible = plan.with_status(plan.status, targeting=("canal_direct", "primo_accedant"))
        assert _check(guardrails.pre_launch(cible), "COMP_PROTECTED").passed

    def test_auto_validation_refusee(self, plan):
        seul = plan.with_status(plan.status, created_by="analyste", approved_by="analyste")
        assert not _check(guardrails.pre_launch(seul), "GOV_FOUR_EYES").passed

    def test_absence_de_validation_refusee(self, plan):
        brut = plan.with_status(plan.status, approved_by="")
        assert not _check(guardrails.pre_launch(brut), "GOV_FOUR_EYES").passed

    def test_plan_tres_sous_dimensionne_est_bloquant(self, plan):
        maigre = plan.with_status(plan.status, planned_volume=2_000)
        check = _check(guardrails.pre_launch(maigre), "STAT_POWER")
        assert not check.passed and check.severity is Severity.BLOCKING

    def test_plan_legerement_sous_dimensionne_est_un_avertissement(self, plan):
        """Nuance deliberee : un pilote volontairement court reste lançable, mais
        il doit etre assume explicitement."""
        limite = plan.with_status(plan.status, planned_volume=36_000)
        check = _check(guardrails.pre_launch(limite), "STAT_POWER")
        assert not check.passed and check.severity is Severity.WARNING
        assert guardrails.pre_launch(limite).cleared  # non bloquant

    def test_absence_de_temoin_avertit_sans_bloquer(self, plan):
        sans = plan.with_status(plan.status, holdout_share=0.0)
        assert not _check(guardrails.pre_launch(sans), "STAT_HOLDOUT").passed
        assert guardrails.pre_launch(sans).cleared


class TestEnProduction:
    def _analysis(self, plan, take_ups, volume=8_000):
        aggregats = [
            CellAggregate(c.key, volume * (2 if c.is_control else 1),
                          int(round(volume * (2 if c.is_control else 1) * take_ups[c.key])),
                          0.0, 0.0, 0.0, 0.0)
            for c in plan.cells
        ]
        return analyse(plan, aggregats)

    def test_situation_nominale(self, plan):
        analysis = self._analysis(plan, {"ctl": 0.061, "m45": 0.084, "p45": 0.047, "p90": 0.037})
        assert guardrails.runtime(analysis).cleared

    def test_arret_de_protection_sur_perte_avertie(self, plan):
        serre = plan.with_status(plan.status, loss_tolerance_per_lead=1.0)
        analysis = self._analysis(serre, {"ctl": 0.061, "m45": 0.075, "p45": 0.047, "p90": 0.037})
        report = guardrails.runtime(analysis)
        assert not report.cleared
        assert not _check(report, "ECO_STOPLOSS").passed

    def test_la_tolerance_est_lue_dans_le_plan(self, plan):
        """La tolerance est une decision de comite prise avant de voir les
        resultats : elle vit dans le plan, pas dans un argument d'appel."""
        analysis = self._analysis(plan, {"ctl": 0.061, "m45": 0.075, "p45": 0.047, "p90": 0.037})
        assert guardrails.runtime(analysis).cleared                     # tolerance du plan : 8 EUR
        assert not guardrails.runtime(analysis, 1.0).cleared            # politique alternative

    def test_srm_bloque_la_lecture(self, plan):
        aggregats = [
            CellAggregate(c.key, 16_000 if c.is_control else (4_000 if c.key == "p45" else 8_000),
                          500, 0.0, 0.0, 0.0, 0.0)
            for c in plan.cells
        ]
        report = guardrails.runtime(analyse(plan, aggregats))
        assert not _check(report, "STAT_SRM").passed
