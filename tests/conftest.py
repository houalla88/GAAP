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
from gaap.domain.pricing import CostStack
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
    """Structure de cout de reference : tomates grappe.

    Plancher resultant : 2,390 EUR/kg au taux d'ecoulement declare de 82 %.
    """
    return CostStack(
        purchase_cost=1.45, logistics_cost=0.18, handling_cost=0.22,
        known_shrink=0.06, salvage_value=0.10,
        expected_sell_through=0.82, capital_cost=0.012,
    )


@pytest.fixture
def plan(cost):
    """Plan de reference : quatre paliers de prix, garde-fous levables."""
    return Experiment(
        key="test-tomate",
        name="Plan de test",
        product="Tomates grappe",
        hypothesis="Le prix courant est sous l'optimum de contribution.",
        owner="Categorie",
        salt="test-tomate-salt",
        cells=(
            PriceCell("ctl", "Controle 2,95 EUR", 2.95, 0.40, is_control=True),
            PriceCell("m20", "-20 c", 2.75, 0.20),
            PriceCell("p20", "+20 c", 3.15, 0.20),
            PriceCell("p40", "+40 c", 3.35, 0.20),
        ),
        cost=cost,
        status=ExperimentStatus.LIVE,
        holdout_share=0.05,
        max_exposure=0.65,
        max_delta_cents=50.0,
        min_sample_per_cell=11_000,
        loss_tolerance_per_unit=0.12,
        alpha=0.05, power=0.80, target_mde=0.05,
        baseline_sell_through=0.82, planned_volume=72_000,
        created_by="analyste", approved_by="direction.commerciale",
    )
