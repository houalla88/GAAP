"""Portefeuille de demonstration.

**Toutes les donnees produites par ce module sont synthetiques.** Aucun
fournisseur, aucun magasin, aucun volume reel n'y figure. Les ordres de grandeur
(prix d'achat au cadran, freinte, taux d'ecoulement, elasticite) sont choisis
pour etre plausibles sur un rayon fruits et legumes de grande distribution
europeenne ; ils ne constituent ni une reference de marche, ni une
recommandation tarifaire.

Le portefeuille est construit pour exposer les cinq situations qu'un moteur
d'experimentation tarifaire doit savoir traiter, et que la plupart des outils
d'A/B testing traitent mal :

1. un test concluant **contre** le taux d'ecoulement et **contre** l'objectif de
   reduction du gaspillage, les deux pointant vers le prix le moins rentable ;
2. un test encore sous-dimensionne, ou la discipline sequentielle interdit de
   conclure ;
3. un test sans effet economique malgre un ecart d'ecoulement significatif ;
4. un plan **refuse avant lancement** par les garde-fous ;
5. un test **invalide** par rupture d'allocation (SRM).

Le generateur de donnees est explicite et parametre : demande a elasticite
constante, plus un terme de selection par la qualite qui fait dependre
l'ecoulement d'un kilo de sa fraîcheur lorsque le prix s'ecarte de la reference.
"""

from __future__ import annotations

import hashlib
import math
import random
from datetime import datetime, timedelta, timezone

from .domain.allocation import AllocationOutcome, assign
from .domain.models import Experiment, ExperimentStatus, PriceCell
from .domain.pricing import CostStack

__all__ = ["build_portfolio", "generate_observations", "DEMO_SEED"]

DEMO_SEED = 20260912

#: Tomates grappe, categorie de base a rotation rapide et demande peu elastique.
_TOMATO_COST = CostStack(
    purchase_cost=1.45,        # prix au cadran, EUR/kg livre
    logistics_cost=0.18,       # transport et chaîne du froid
    handling_cost=0.22,        # reception, parage, mise en rayon
    known_shrink=0.06,         # freinte connue : parage et deshydratation
    salvage_value=0.10,        # don defiscalise
    expected_sell_through=0.82,
    capital_cost=0.012,
)

#: Fraises, produit d'impulsion tres perissable et tres elastique.
_STRAWBERRY_COST = CostStack(
    purchase_cost=3.60, logistics_cost=0.34, handling_cost=0.28,
    known_shrink=0.11, salvage_value=0.0, expected_sell_through=0.74,
    capital_cost=0.021,
)

#: Carottes vrac, produit de fond de rayon a longue conservation.
_CARROT_COST = CostStack(
    purchase_cost=0.52, logistics_cost=0.09, handling_cost=0.14,
    known_shrink=0.04, salvage_value=0.05, expected_sell_through=0.88,
    capital_cost=0.006,
)

#: Tomates cerises, plus cheres a l'achat et plus fragiles que la grappe.
_CHERRY_COST = CostStack(
    purchase_cost=2.20, logistics_cost=0.22, handling_cost=0.26,
    known_shrink=0.08, salvage_value=0.06, expected_sell_through=0.80,
    capital_cost=0.016,
)

#: Avocats, import a forte valeur et maturite difficile a piloter.
_AVOCADO_COST = CostStack(
    purchase_cost=2.20, logistics_cost=0.41, handling_cost=0.19,
    known_shrink=0.09, salvage_value=0.0, expected_sell_through=0.79,
    capital_cost=0.018,
)


def _days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).replace(
        microsecond=0).isoformat()


def build_portfolio() -> list[tuple[Experiment, dict]]:
    """Retourne les plans de demonstration et leurs parametres de generation.

    Le second element de chaque couple decrit le *monde reel simule* : la vraie
    elasticite, le vrai taux d'ecoulement de reference, l'intensite de la
    selection par la qualite. Ces valeurs ne sont evidemment jamais connues du
    moteur, elles servent uniquement a fabriquer des observations.
    """
    portfolio: list[tuple[Experiment, dict]] = []

    # ------------------------------------------------------------------ 1
    # Echelle de prix sur les tomates grappe. Le cas d'ecole : le prix le plus
    # bas ecoule le mieux, casse le moins, et rapporte le moins.
    portfolio.append((
        Experiment(
            key="tomate-grappe-2026s37",
            name="Tomates grappe - echelle de prix",
            product="Tomates grappe",
            hypothesis=(
                "Le prix courant de 2,95 EUR/kg est positionne sous le prix qui maximise la "
                "contribution. La demande est assez peu elastique pour qu'une hausse de 20 a "
                "40 centimes degrade l'ecoulement moins que proportionnellement a la marge gagnee."
            ),
            owner="Categorie fruits et legumes",
            salt="tomate-grappe-2026s37-0f4c9a",
            cells=(
                PriceCell("ctl", "Controle 2,95 EUR", 2.95, 0.40, is_control=True),
                PriceCell("m20", "-20 c (2,75 EUR)", 2.75, 0.20),
                PriceCell("p20", "+20 c (3,15 EUR)", 3.15, 0.20),
                PriceCell("p40", "+40 c (3,35 EUR)", 3.35, 0.20),
            ),
            cost=_TOMATO_COST,
            status=ExperimentStatus.LIVE,
            holdout_share=0.05,
            max_exposure=0.65,
            max_delta_cents=50.0,
            max_duration_days=28,
            min_sample_per_cell=11_000,
            loss_tolerance_per_unit=0.12,
            alpha=0.05, power=0.80, target_mde=0.05,
            baseline_sell_through=0.82, planned_volume=72_000,
            created_at=_days_ago(34), created_by="h.oualla",
            approved_by="direction.commerciale", approved_at=_days_ago(31),
            activated_at=_days_ago(28),
        ),
        {"elasticity": -0.7, "baseline": 0.82, "volume": 72_000,
         "selection": 0.55, "days": 27, "quality_mean": 0.70, "quality_sd": 0.14},
    ))

    # ------------------------------------------------------------------ 2
    # Barquette de fraises : remise sur conditionnement multiple. Test jeune,
    # la frontiere sequentielle interdit de conclure, et c'est le comportement
    # attendu.
    portfolio.append((
        Experiment(
            key="fraise-lot-2026s37",
            name="Fraises 500 g - remise sur lot",
            product="Fraises barquette",
            hypothesis=(
                "Une remise de 60 centimes par kilo sur l'achat de deux barquettes accelere "
                "assez la rotation pour que la casse evitee compense la marge cedee."
            ),
            owner="Categorie fruits et legumes",
            salt="fraise-lot-2026s37-77b1e2",
            cells=(
                PriceCell("ctl", "Sans remise", 7.90, 0.50, is_control=True),
                PriceCell("lot2", "Remise lot de 2", 7.90, 0.50, pack_discount=0.60),
            ),
            cost=_STRAWBERRY_COST,
            status=ExperimentStatus.LIVE,
            holdout_share=0.05,
            max_exposure=0.55,
            max_delta_cents=90.0,
            max_duration_days=21,
            min_sample_per_cell=9_000,
            loss_tolerance_per_unit=0.40,
            alpha=0.05, power=0.80, target_mde=0.06,
            baseline_sell_through=0.74, planned_volume=26_000,
            created_at=_days_ago(11), created_by="s.leroy",
            approved_by="h.oualla", approved_at=_days_ago(9),
            activated_at=_days_ago(8),
        ),
        {"elasticity": -2.4, "baseline": 0.74, "volume": 7_600,
         "selection": 0.10, "days": 8, "quality_mean": 0.62, "quality_sd": 0.16},
    ))

    # ------------------------------------------------------------------ 3
    # Test conclu sans effet economique. Le resultat utile n'est pas "rien" :
    # c'est une borne superieure sur l'elasticite, et son cout.
    portfolio.append((
        Experiment(
            key="carotte-2026s28",
            name="Carottes vrac - palier 5 centimes",
            product="Carottes vrac",
            hypothesis=(
                "Un palier de 5 centimes est invisible sur un produit de fond de rayon dont "
                "le prix de reference n'est pas memorise par le client."
            ),
            owner="Categorie fruits et legumes",
            salt="carotte-2026s28-3ac118",
            cells=(
                PriceCell("ctl", "Controle 1,29 EUR", 1.29, 0.50, is_control=True),
                PriceCell("p05", "+5 c (1,34 EUR)", 1.34, 0.50),
            ),
            cost=_CARROT_COST,
            status=ExperimentStatus.CONCLUDED,
            holdout_share=0.05,
            max_exposure=0.60,
            max_delta_cents=20.0,
            max_duration_days=30,
            min_sample_per_cell=15_000,
            loss_tolerance_per_unit=0.06,
            alpha=0.05, power=0.80, target_mde=0.05,
            baseline_sell_through=0.88, planned_volume=42_000,
            created_at=_days_ago(96), created_by="h.oualla",
            approved_by="direction.commerciale", approved_at=_days_ago(93),
            activated_at=_days_ago(91), concluded_at=_days_ago(58),
        ),
        {"elasticity": -0.9, "baseline": 0.88, "volume": 43_600,
         "selection": 0.04, "days": 33, "quality_mean": 0.82, "quality_sd": 0.09},
    ))

    # ------------------------------------------------------------------ 4
    # Plan refuse : cellule sous le plancher economique ET ciblage adosse a un
    # critere protege. Le refus fait partie de l'historique.
    portfolio.append((
        Experiment(
            key="avocat-conquete-2026s40",
            name="Avocats - prix d'appel 3,45 EUR",
            product="Avocats Hass",
            hypothesis=(
                "Un prix d'appel a 3,45 EUR le kilo doit capter du trafic sur les magasins "
                "de quartier face a l'enseigne concurrente."
            ),
            owner="Direction commerciale",
            salt="avocat-conquete-2026s40-91de0c",
            cells=(
                PriceCell("ctl", "Controle 4,95 EUR", 4.95, 0.60, is_control=True),
                PriceCell("appel", "Prix d'appel 3,45 EUR", 3.45, 0.40),
            ),
            cost=_AVOCADO_COST,
            status=ExperimentStatus.REVIEW,
            holdout_share=0.0,
            max_exposure=0.30,
            max_delta_cents=80.0,
            max_duration_days=14,
            min_sample_per_cell=6_000,
            loss_tolerance_per_unit=0.25,
            alpha=0.05, power=0.80, target_mde=0.04,
            baseline_sell_through=0.79, planned_volume=9_000,
            targeting=("quartiers_revenu_faible", "clientele_age_senior"),
            created_at=_days_ago(5), created_by="d.commerciale",
        ),
        {"skip_observations": True},
    ))

    # ------------------------------------------------------------------ 5
    # Rupture d'allocation. Une cellule a perdu du volume en aval du routage :
    # le resultat, meme flatteur, est irrecevable.
    portfolio.append((
        Experiment(
            key="tomate-cerise-2026s36",
            name="Tomates cerises - affichage au kilo",
            product="Tomates cerises",
            hypothesis=(
                "Afficher le prix au kilo plutot qu'a la barquette reduit la sensibilite au "
                "prix et permet de soutenir un palier de 25 centimes."
            ),
            owner="Categorie fruits et legumes",
            salt="tomate-cerise-2026s36-b2f7a4",
            cells=(
                PriceCell("ctl", "Controle 4,20 EUR", 4.20, 0.50, is_control=True),
                PriceCell("p25", "+25 c (4,45 EUR)", 4.45, 0.50),
            ),
            cost=_CHERRY_COST,
            status=ExperimentStatus.LIVE,
            holdout_share=0.05,
            max_exposure=0.55,
            max_delta_cents=40.0,
            max_duration_days=21,
            min_sample_per_cell=7_000,
            loss_tolerance_per_unit=0.15,
            alpha=0.05, power=0.80, target_mde=0.05,
            baseline_sell_through=0.80, planned_volume=30_000,
            created_at=_days_ago(22), created_by="s.leroy",
            approved_by="h.oualla", approved_at=_days_ago(20),
            activated_at=_days_ago(18),
        ),
        {"elasticity": -1.3, "baseline": 0.80, "volume": 24_000,
         "selection": 0.18, "days": 17, "quality_mean": 0.68, "quality_sd": 0.15,
         "srm_leak": {"cell": "p25", "drop": 0.17}},
    ))

    return portfolio


def _logit(p: float) -> float:
    p = min(1.0 - 1e-9, max(1e-9, p))
    return math.log(p / (1.0 - p))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def generate_observations(experiment: Experiment, params: dict, seed: int = DEMO_SEED) -> list[tuple]:
    """Fabrique des observations synthetiques pour une experience.

    Modele generateur, entierement explicite :

        ecoulement_i = sigmoid( logit( s_ref x (p_i / p_ref)^e )
                                + lambda x z_qualite,i x (p_i - p_ref) / p_ref x 10 )

    Le second terme est le mecanisme de **selection par la qualite** : quand le
    prix monte, le client devient plus exigeant et prend en priorite les plus
    beaux articles. Les kilos de moindre fraîcheur restent donc en rayon et
    finissent a la casse, ce qui degrade le stock residuel au-dela de ce que le
    seul ralentissement de rotation expliquerait. C'est le phenomene qu'une
    mesure du seul taux d'ecoulement ne voit pas.

    `srm_leak` simule une perte de volume sur une cellule apres le routage :
    c'est ainsi qu'un SRM apparaît reellement en exploitation, jamais dans le
    tirage aleatoire lui-meme, toujours dans la chaîne qui le suit. Ici, une
    rupture de reassort sur une partie des magasins de la cellule.
    """
    if params.get("skip_observations"):
        return []

    key_digest = int.from_bytes(
        hashlib.sha256(experiment.key.encode("utf-8")).digest()[:4], "big"
    )
    rng = random.Random(seed + key_digest % 100_000)

    elasticity = params["elasticity"]
    baseline = params["baseline"]
    volume = params["volume"]
    selection = params.get("selection", 0.0)
    days = max(1, params.get("days", 21))
    quality_mean = params.get("quality_mean", 0.70)
    quality_sd = params.get("quality_sd", 0.14)
    leak = params.get("srm_leak")

    reference_price = experiment.control.effective_price
    start = datetime.now(timezone.utc) - timedelta(days=days)

    rows: list[tuple] = []
    for i in range(volume):
        unit_id = f"{experiment.key}:K{i:07d}"
        allocation = assign(experiment, unit_id, enforce_status=False)
        if allocation.outcome is not AllocationOutcome.ASSIGNED:
            continue
        if leak and allocation.cell_key == leak["cell"] and rng.random() < leak["drop"]:
            continue  # rupture de reassort en aval du routage

        cell = experiment.cell(allocation.cell_key)
        price = cell.effective_price

        quality = min(1.0, max(0.02, rng.gauss(quality_mean, quality_sd)))
        z_quality = (quality - quality_mean) / quality_sd if quality_sd > 0 else 0.0
        relative_price = (price - reference_price) / reference_price if reference_price else 0.0

        base = baseline * (price / reference_price) ** elasticity if reference_price else baseline
        probability = _sigmoid(_logit(base) + selection * z_quality * relative_price * 10.0)
        sold = 1 if rng.random() < probability else 0

        offset = timedelta(
            days=rng.randrange(days), hours=rng.randrange(24), minutes=rng.randrange(60)
        )
        rows.append((
            experiment.key, unit_id, cell.key, sold, round(quality, 6), "",
            (start + offset).replace(microsecond=0).isoformat(),
        ))
    return rows
