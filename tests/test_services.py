"""Regles de gouvernance du cycle de vie."""

import pytest

from gaap.domain.models import ExperimentStatus
from gaap.infrastructure import ledger
from gaap.services.experiments import ExperimentService, LifecycleError


@pytest.fixture
def service(conn):
    return ExperimentService(conn)


class TestCreation:
    def test_creation_en_brouillon_et_journalisee(self, service, plan, conn):
        cree = service.create(plan, "analyste")
        assert cree.status is ExperimentStatus.DRAFT
        assert cree.created_by == "analyste"
        assert ledger.entries(conn, subject=plan.key)[0].event == "experiment.created"

    def test_cle_dupliquee_refusee(self, service, plan):
        service.create(plan, "analyste")
        with pytest.raises(LifecycleError, match="deja la cle"):
            service.create(plan, "analyste")


class TestQuatreYeux:
    def test_auto_validation_refusee(self, service, plan):
        service.create(plan, "analyste")
        service.submit_for_review(plan.key, "analyste")
        with pytest.raises(LifecycleError, match="Segregation des taches"):
            service.approve(plan.key, "analyste")

    def test_validation_par_un_tiers_acceptee(self, service, plan):
        service.create(plan, "analyste")
        service.submit_for_review(plan.key, "analyste")
        valide = service.approve(plan.key, "direction.risques")
        assert valide.approved_by == "direction.risques" and valide.approved_at

    def test_validation_hors_etat_refusee(self, service, plan):
        service.create(plan, "analyste")
        with pytest.raises(LifecycleError, match="en validation"):
            service.approve(plan.key, "direction.risques")


class TestActivation:
    def _valide(self, service, plan):
        service.create(plan, "analyste")
        service.submit_for_review(plan.key, "analyste")
        service.approve(plan.key, "direction.risques")

    def test_activation_d_un_plan_sain(self, service, plan):
        self._valide(service, plan)
        actif = service.activate(plan.key, "analyste")
        assert actif.status is ExperimentStatus.LIVE and actif.activated_at

    def test_garde_fou_bloquant_refuse_l_activation(self, service, plan):
        interdit = plan.with_status(plan.status, targeting=("age_moins_de_30",))
        self._valide(service, interdit)
        with pytest.raises(LifecycleError, match="Garde-fous|garde-fous"):
            service.activate(interdit.key, "analyste")

    def test_le_refus_est_journalise(self, service, plan, conn):
        """Un test refuse fait partie de l'historique de decision de
        l'etablissement au meme titre qu'un test accepte."""
        interdit = plan.with_status(plan.status, targeting=("age_moins_de_30",))
        self._valide(service, interdit)
        with pytest.raises(LifecycleError):
            service.activate(interdit.key, "analyste")
        evenements = [e.event for e in ledger.entries(conn, subject=interdit.key)]
        assert "guardrail.blocked" in evenements

    def test_l_activation_ancre_le_sel_et_l_empreinte(self, service, plan, conn):
        self._valide(service, plan)
        service.activate(plan.key, "analyste")
        entree = next(e for e in ledger.entries(conn, subject=plan.key)
                      if e.event == "experiment.activated")
        assert entree.payload["salt"] == plan.salt
        assert len(entree.payload["config_hash"]) == 64


class TestPlanFige:
    def _active(self, service, plan):
        service.create(plan, "analyste")
        service.submit_for_review(plan.key, "analyste")
        service.approve(plan.key, "direction.risques")
        return service.activate(plan.key, "analyste")

    def test_plan_en_production_non_modifiable(self, service, plan):
        """Modifier un plan en cours melange deux experiences dans un meme jeu de
        donnees - faute difficile a detecter apres coup et fatale a la validite."""
        actif = self._active(service, plan)
        with pytest.raises(LifecycleError, match="fige"):
            service.update_plan(actif.with_status(actif.status, max_delta_cents=300.0), "analyste")

    def test_modification_d_un_brouillon_annule_la_validation(self, service, plan, conn):
        service.create(plan, "analyste")
        service.submit_for_review(plan.key, "analyste")
        service.approve(plan.key, "direction.risques")
        modifie = service.update_plan(service.get(plan.key), "analyste")
        assert modifie.status is ExperimentStatus.DRAFT
        assert modifie.approved_by == ""

    def test_transition_illegale_refusee(self, service, plan):
        service.create(plan, "analyste")
        with pytest.raises(LifecycleError, match="Transition refusee"):
            service.pause(plan.key, "analyste")

    def test_suspension_et_reprise(self, service, plan):
        self._active(service, plan)
        assert service.pause(plan.key, "analyste", "doute sur le routage").status is ExperimentStatus.PAUSED
        assert service.resume(plan.key, "analyste").status is ExperimentStatus.LIVE

    def test_conclusion_est_terminale(self, service, plan):
        self._active(service, plan)
        service.conclude(plan.key, "direction.risques")
        with pytest.raises(LifecycleError, match="Transition refusee"):
            service.resume(plan.key, "analyste")


def test_empreinte_de_configuration_change_avec_le_plan(service, plan):
    service.create(plan, "analyste")
    avant = service.config_hash(plan.key)
    service.update_plan(service.get(plan.key).with_status(ExperimentStatus.DRAFT,
                                                          max_delta_cents=150.0), "analyste")
    assert service.config_hash(plan.key) != avant
