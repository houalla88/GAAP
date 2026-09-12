"""Fixtures de test.

Chaque test recoit une base neuve sur disque plutot qu'en memoire : le moteur
ouvre une connexion par contexte applicatif, et une base ':memory:' donnerait
une base differente a chaque requete. Ce detail est la premiere cause de tests
Flask + SQLite qui passent isolement et echouent en suite.
"""

from __future__ import annotations

import pytest

from gaap import create_app
from gaap.domain.models import Experiment, ExperimentStatus, PriceCell
from gaap.domain.pricing import CostOfRisk
from gaap.infrastructure.db import get_db, init_db


@pytest.fixture
def app(tmp_path):
    application = create_app("testing", DATABASE=str(tmp_path / "gaap-test.sqlite"))
    with application.app_context():
        init_db()
    return application


@pytest.fixture
def conn(app):
    with app.app_context():
        yield get_db()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def cost():
    return CostOfRisk(
        funding_rate=0.0285, operating_cost_rate=0.0110, pd=0.0210, lgd=0.62,
        risk_weight=0.75, capital_ratio=0.125, hurdle_rate=0.110,
    )


@pytest.fixture
def plan(cost):
    """Plan de reference : quatre paliers de prix, garde-fous levables."""
    return Experiment(
        key="test-taeg",
        name="Plan de test",
        product="Pret personnel",
        hypothesis="Le prix courant est sous l'optimum de contribution.",
        owner="Pricing",
        salt="test-taeg-salt",
        cells=(
            PriceCell("ctl", "Controle 6,90 %", 0.0690, 0.40, is_control=True),
            PriceCell("m45", "-45 bps", 0.0645, 0.20),
            PriceCell("p45", "+45 bps", 0.0735, 0.20),
            PriceCell("p90", "+90 bps", 0.0780, 0.20),
        ),
        cost=cost,
        principal=12_500.0,
        duration_factor=2.4,
        status=ExperimentStatus.LIVE,
        holdout_share=0.05,
        max_exposure=0.65,
        max_delta_bp=120.0,
        min_sample_per_cell=4_000,
        loss_tolerance_per_lead=8.0,
        alpha=0.05, power=0.80, target_mde=0.18,
        baseline_rate=0.061, planned_volume=46_000,
        created_by="analyste", approved_by="direction.risques",
    )
