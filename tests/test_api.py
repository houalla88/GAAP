"""API et interface : contrats de sortie et en-tetes de securite."""

import pytest

from gaap.domain.models import ExperimentStatus
from gaap.services.experiments import ExperimentService


@pytest.fixture
def live_plan(app, plan):
    """Un plan actif, valide et journalise, pret a servir des prix."""
    with app.app_context():
        from gaap.infrastructure.db import get_db
        service = ExperimentService(get_db())
        service.create(plan, "analyste")
        service.submit_for_review(plan.key, "analyste")
        service.approve(plan.key, "direction.commerciale")
        service.activate(plan.key, "analyste")
    return plan


class TestSecurite:
    def test_en_tetes_poses_par_l_application(self, client):
        """Poses au niveau applicatif et non delegues au reverse proxy : une
        application qui depend d'un proxy pour etre sure ne l'est pas quand on
        la deplace."""
        headers = client.get("/api/v1/health").headers
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"
        assert headers["Referrer-Policy"] == "same-origin"

    def test_csp_stricte_sans_exception_en_ligne(self, client):
        csp = client.get("/").headers["Content-Security-Policy"]
        assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp

    def test_aucun_script_ni_style_en_ligne_dans_les_pages(self, client, live_plan):
        """La CSP ci-dessus n'est tenable que si les gabarits s'en tiennent a des
        ressources externes. Ce test empeche une regression silencieuse."""
        for url in ("/", f"/experiences/{live_plan.key}", "/experiences/nouvelle",
                    "/laboratoire", "/piste-audit", "/methode"):
            page = client.get(url).get_data(as_text=True)
            assert "<script>" not in page
            assert 'style="' not in page


class TestAffectation:
    def test_prix_servi_et_reproductible(self, client, live_plan):
        premiere = client.post("/api/v1/assign",
                               json={"experiment": live_plan.key, "unit_id": "LOT-42"})
        seconde = client.post("/api/v1/assign",
                              json={"experiment": live_plan.key, "unit_id": "LOT-42"})
        assert premiere.status_code == 200
        assert premiere.get_json()["cell"] == seconde.get_json()["cell"]
        assert premiere.get_json()["price"] > 0

    def test_experience_inconnue_retourne_404(self, client):
        reponse = client.post("/api/v1/assign",
                              json={"experiment": "absente", "unit_id": "x"})
        assert reponse.status_code == 404
        assert reponse.get_json()["error"] == "experiment_not_found"

    def test_parametres_manquants_retournent_400(self, client):
        assert client.post("/api/v1/assign", json={}).status_code == 400

    def test_segment_exclu_recoit_le_prix_de_reference(self, app, client, plan):
        with app.app_context():
            from gaap.infrastructure.db import get_db
            protege = plan.with_status(plan.status, key="exclu",
                                       excluded_segments=("magasins_pilotes",))
            service = ExperimentService(get_db())
            service.create(protege, "analyste")
            service.submit_for_review("exclu", "analyste")
            service.approve("exclu", "direction.commerciale")
            service.activate("exclu", "analyste")
        reponse = client.post("/api/v1/assign", json={
            "experiment": "exclu", "unit_id": "LOT-7", "segment": "magasins_pilotes",
        }).get_json()
        assert reponse["outcome"] == "excluded"
        assert reponse["price"] == pytest.approx(plan.control.price)
        assert reponse["in_analysis"] is False


class TestObservations:
    def test_enregistrement_puis_lecture_du_rapport(self, client, live_plan):
        for i in range(40):
            assignation = client.post("/api/v1/assign", json={
                "experiment": live_plan.key, "unit_id": f"K{i}",
            }).get_json()
            client.post("/api/v1/observations", json={
                "experiment": live_plan.key, "unit_id": f"K{i}",
                "cell": assignation["cell"], "sold": i % 5 != 0,
                "quality_index": 0.70,
            })
        rapport = client.get(f"/api/v1/experiments/{live_plan.key}/report").get_json()
        assert sum(c["presented"] for c in rapport["cells"]) > 0
        assert rapport["floor_planned"] == pytest.approx(live_plan.price_floor.total)

    def test_doublon_ignore(self, client, live_plan):
        payload = {"experiment": live_plan.key, "unit_id": "K1", "cell": "ctl",
                   "sold": True, "quality_index": 0.70}
        assert client.post("/api/v1/observations", json=payload).get_json()["recorded"] == 1
        assert client.post("/api/v1/observations", json=payload).get_json()["recorded"] == 0

    def test_champs_manquants_refuses(self, client):
        reponse = client.post("/api/v1/observations", json={"experiment": "x"})
        assert reponse.status_code == 400
        assert "unit_id" in reponse.get_json()["fields"]


class TestDimensionnement:
    def test_correction_de_bonferroni_appliquee(self, client):
        resultat = client.post("/api/v1/design/power", json={
            "baseline_sell_through": 0.82, "target_mde": 0.05, "cells": 4,
            "planned_volume": 72_000,
        }).get_json()
        assert resultat["comparisons"] == 3
        assert resultat["alpha_adjusted"] == pytest.approx(0.05 / 3, abs=1e-4)

    def test_volume_insuffisant_signale(self, client):
        resultat = client.post("/api/v1/design/power", json={
            "baseline_sell_through": 0.82, "target_mde": 0.01, "cells": 2,
            "planned_volume": 2_000,
        }).get_json()
        assert resultat["sufficient"] is False

    def test_parametre_hors_domaine_refuse(self, client):
        assert client.post("/api/v1/design/power",
                           json={"baseline_sell_through": 1.4}).status_code == 400


class TestInterface:
    def test_les_pages_repondent(self, client, live_plan):
        for url in ("/", f"/experiences/{live_plan.key}", "/experiences/nouvelle",
                    "/laboratoire", "/piste-audit", "/methode"):
            assert client.get(url).status_code == 200

    def test_experience_inconnue_rend_une_page_404(self, client):
        assert client.get("/experiences/absente").status_code == 404

    def test_transition_depuis_l_interface_est_journalisee(self, client, app, plan):
        with app.app_context():
            from gaap.infrastructure.db import get_db
            ExperimentService(get_db()).create(plan, "analyste")
        client.post(f"/experiences/{plan.key}/transition", data={"action": "submit"})
        with app.app_context():
            from gaap.infrastructure.db import get_db
            from gaap.infrastructure import ledger
            evenements = [e.event for e in ledger.entries(get_db(), subject=plan.key)]
        assert "experiment.submitted" in evenements

    def test_verification_de_chaine_exposee(self, client, live_plan):
        resultat = client.get("/api/v1/ledger/verify").get_json()
        assert resultat["intact"] is True and resultat["checked"] > 0


def test_interface_et_api_lisent_la_meme_source(client, live_plan):
    """Le tableau de bord ne doit rien recalculer : ce qui est affiche doit etre
    exportable a l'identique."""
    rapport = client.get(f"/api/v1/experiments/{live_plan.key}/report").get_json()
    page = client.get(f"/experiences/{live_plan.key}").get_data(as_text=True)
    assert f"{rapport['floor_planned']:.2f}".replace(".", ",") in page
