"""Portefeuille de demonstration.

**Toutes les donnees produites par ce module sont synthetiques.** Aucun client,
aucun contrat, aucun encours reel n'y figure. Les ordres de grandeur (taux de
refinancement, PD, LGD, ponderation de risque, take-up) sont choisis pour etre
plausibles sur un marche de credit a la consommation europeen ; ils ne
constituent ni une reference de marche, ni une recommandation tarifaire.

Le portefeuille est construit pour exposer les cinq situations qu'un moteur
d'experimentation tarifaire doit savoir traiter, et que la plupart des outils
d'A/B testing traitent mal :

1. un test concluant **contre** le taux de conversion (le prix qui convertit le
   mieux n'est pas celui qui rapporte le plus) ;
2. un test encore sous-dimensionne, ou la discipline sequentielle interdit de
   conclure ;
3. un test sans effet, dont le resultat utile est le cout d'apprentissage et la
   borne obtenue sur l'elasticite ;
4. un plan **refuse avant lancement** par les garde-fous ;
5. un test **invalide** par rupture d'allocation (SRM).

Le generateur de donnees est explicite et parametre : demande a elasticite
constante, plus un terme d'anti-selection qui fait dependre l'acceptation du
risque du demandeur lorsque le prix s'ecarte de la reference.
"""

from __future__ import annotations

import hashlib
import math
import random
from datetime import datetime, timedelta, timezone

from .domain.allocation import AllocationOutcome, assign
from .domain.models import Experiment, ExperimentStatus, PriceCell
from .domain.pricing import CostOfRisk

__all__ = ["build_portfolio", "generate_observations", "DEMO_SEED"]

DEMO_SEED = 20260912

#: Cout du risque du segment "pret personnel standard". Sortie ALM + modele de
#: score dans un dispositif reel ; valeurs plausibles ici.
_CONSUMER_COST = CostOfRisk(
    funding_rate=0.0285,      # taux de cession interne 5 ans
    operating_cost_rate=0.0110,
    pd=0.0210,                # PD 12 mois du segment
    lgd=0.62,
    risk_weight=0.75,         # exposition retail, approche standard
    capital_ratio=0.125,      # CET1 cible + coussins
    hurdle_rate=0.110,        # cout des fonds propres
)

_AUTO_COST = CostOfRisk(
    funding_rate=0.0225, operating_cost_rate=0.0080, pd=0.0110, lgd=0.45,
    risk_weight=0.75, capital_ratio=0.125, hurdle_rate=0.110,
)

_GREEN_COST = CostOfRisk(
    funding_rate=0.0290, operating_cost_rate=0.0125, pd=0.0165, lgd=0.55,
    risk_weight=0.75, capital_ratio=0.125, hurdle_rate=0.110,
)


def _days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).replace(
        microsecond=0).isoformat()


def build_portfolio() -> list[tuple[Experiment, dict]]:
    """Retourne les plans de demonstration et leurs parametres de generation.

    Le second element de chaque couple decrit le *monde reel simule* : la vraie
    elasticite, le vrai take-up de reference, l'intensite d'anti-selection.
    Ces valeurs ne sont evidemment jamais connues du moteur - elles servent
    uniquement a fabriquer des observations.
    """
    portfolio: list[tuple[Experiment, dict]] = []

    # ------------------------------------------------------------------ 1
    # Echelle de TAEG sur le pret personnel. Le cas d'ecole : le prix le plus
    # bas convertit le mieux et rapporte le moins.
    portfolio.append((
        Experiment(
            key="pp-taeg-2026q3",
            name="Pret personnel 12 500 EUR : echelle de TAEG",
            product="Pret personnel",
            hypothesis=(
                "Le TAEG courant de 6,90 % est positionne sous le prix qui maximise la "
                "contribution ajustee du risque. Une hausse de 45 a 90 bps doit degrader "
                "le take-up moins que proportionnellement a la marge gagnee."
            ),
            owner="Pricing & Analytics",
            salt="pp-taeg-2026q3-0f4c9a",
            cells=(
                PriceCell("ctl", "Controle 6,90 %", 0.0690, 0.40, is_control=True),
                PriceCell("m45", "-45 bps (6,45 %)", 0.0645, 0.20),
                PriceCell("p45", "+45 bps (7,35 %)", 0.0735, 0.20),
                PriceCell("p90", "+90 bps (7,80 %)", 0.0780, 0.20),
            ),
            cost=_CONSUMER_COST,
            principal=12_500.0,
            duration_factor=2.4,            # 60 mois amortissables
            status=ExperimentStatus.LIVE,
            holdout_share=0.05,
            max_exposure=0.65,
            max_delta_bp=120.0,
            max_duration_days=45,
            min_sample_per_cell=7_000,
            loss_tolerance_per_lead=8.00,
            alpha=0.05, power=0.80, target_mde=0.18,
            baseline_rate=0.061, planned_volume=46_000,
            created_at=_days_ago(52), created_by="h.oualla",
            approved_by="direction.risques", approved_at=_days_ago(48),
            activated_at=_days_ago(46),
        ),
        {"elasticity": -4.0, "baseline": 0.061, "volume": 46_000,
         "adverse": 0.30, "days": 44, "pd_mean": 0.021, "pd_sd": 0.011},
    ))

    # ------------------------------------------------------------------ 2
    # Frais de dossier sur le credit renovation. Test jeune : la frontiere
    # sequentielle interdit de conclure, et c'est le comportement attendu.
    portfolio.append((
        Experiment(
            key="reno-frais-2026q3",
            name="Credit renovation : frais de dossier",
            product="Credit renovation energetique",
            hypothesis=(
                "La suppression des frais de dossier (125 EUR) ameliore le take-up "
                "suffisamment pour compenser la marge immediate perdue."
            ),
            owner="Marketing produit",
            salt="reno-frais-2026q3-77b1e2",
            cells=(
                PriceCell("ctl", "Frais 125 EUR", 0.0645, 0.50, fee=125.0, is_control=True),
                PriceCell("free", "Sans frais", 0.0645, 0.50, fee=0.0),
            ),
            cost=_GREEN_COST,
            principal=18_000.0,
            duration_factor=3.6,            # 96 mois amortissables
            status=ExperimentStatus.LIVE,
            holdout_share=0.05,
            max_exposure=0.55,
            max_delta_bp=60.0,
            max_duration_days=60,
            min_sample_per_cell=9_000,
            loss_tolerance_per_lead=3.00,
            alpha=0.05, power=0.80, target_mde=0.18,
            baseline_rate=0.048, planned_volume=22_000,
            created_at=_days_ago(16), created_by="s.leroy",
            approved_by="h.oualla", approved_at=_days_ago(14),
            activated_at=_days_ago(12),
        ),
        {"elasticity": -3.1, "baseline": 0.048, "volume": 7_400,
         "adverse": 0.15, "days": 12, "pd_mean": 0.0165, "pd_sd": 0.008},
    ))

    # ------------------------------------------------------------------ 3
    # Test conclu sans effet. Le resultat utile n'est pas "rien" : c'est une
    # borne superieure sur l'elasticite, et son cout.
    portfolio.append((
        Experiment(
            key="auto-taeg-2026q2",
            name="Credit auto : palier 25 bps",
            product="Credit auto",
            hypothesis=(
                "Un palier de 25 bps est invisible pour le client sur un marche ou la "
                "comparaison se fait sur la mensualite affichee, pas sur le TAEG."
            ),
            owner="Pricing & Analytics",
            salt="auto-taeg-2026q2-3ac118",
            cells=(
                PriceCell("ctl", "Controle 5,45 %", 0.0545, 0.50, is_control=True),
                PriceCell("p25", "+25 bps (5,70 %)", 0.0570, 0.50),
            ),
            cost=_AUTO_COST,
            principal=21_000.0,
            duration_factor=2.1,
            status=ExperimentStatus.CONCLUDED,
            holdout_share=0.05,
            max_exposure=0.60,
            max_delta_bp=80.0,
            max_duration_days=50,
            min_sample_per_cell=12_000,
            loss_tolerance_per_lead=4.00,
            alpha=0.05, power=0.80, target_mde=0.12,
            baseline_rate=0.072, planned_volume=30_000,
            created_at=_days_ago(120), created_by="h.oualla",
            approved_by="direction.risques", approved_at=_days_ago(117),
            activated_at=_days_ago(115), concluded_at=_days_ago(70),
        ),
        {"elasticity": -4.6, "baseline": 0.072, "volume": 31_400,
         "adverse": 0.05, "days": 45, "pd_mean": 0.0110, "pd_sd": 0.006},
    ))

    # ------------------------------------------------------------------ 4
    # Plan refuse : cellule sous le plancher economique ET ciblage adosse a un
    # critere protege. Le refus fait partie de l'historique.
    portfolio.append((
        Experiment(
            key="auto-offensive-2026q4",
            name="Credit auto : offre de conquete 3,90 %",
            product="Credit auto",
            hypothesis=(
                "Un taux d'appel a 3,90 % sur les primo-accedants doit capter des parts "
                "de marche sur le canal concessionnaire."
            ),
            owner="Direction commerciale",
            salt="auto-offensive-2026q4-91de0c",
            cells=(
                PriceCell("ctl", "Controle 5,45 %", 0.0545, 0.60, is_control=True),
                PriceCell("conq", "Taux d'appel 3,90 %", 0.0390, 0.40),
            ),
            cost=_AUTO_COST,
            principal=21_000.0,
            duration_factor=2.1,
            status=ExperimentStatus.REVIEW,
            holdout_share=0.0,
            max_exposure=0.30,
            max_delta_bp=120.0,
            max_duration_days=30,
            min_sample_per_cell=5_000,
            loss_tolerance_per_lead=4.00,
            alpha=0.05, power=0.80, target_mde=0.05,
            baseline_rate=0.072, planned_volume=9_000,
            targeting=("primo_accedant", "age_moins_de_30"),
            created_at=_days_ago(6), created_by="d.commerciale",
        ),
        {"skip_observations": True},
    ))

    # ------------------------------------------------------------------ 5
    # Rupture d'allocation. Une cellule a perdu du trafic en aval du routage :
    # le resultat, meme flatteur, est irrecevable.
    portfolio.append((
        Experiment(
            key="pp-mensualite-2026q3",
            name="Pret personnel : affichage mensualite",
            product="Pret personnel",
            hypothesis=(
                "Presenter la mensualite avant le TAEG reduit la sensibilite au prix "
                "et permet de soutenir un palier de 30 bps."
            ),
            owner="Pricing & Analytics",
            salt="pp-mensualite-2026q3-b2f7a4",
            cells=(
                PriceCell("ctl", "Controle 6,90 %", 0.0690, 0.50, is_control=True),
                PriceCell("p30", "+30 bps (7,20 %)", 0.0720, 0.50),
            ),
            cost=_CONSUMER_COST,
            principal=12_500.0,
            duration_factor=2.4,
            status=ExperimentStatus.LIVE,
            holdout_share=0.05,
            max_exposure=0.55,
            max_delta_bp=60.0,
            max_duration_days=40,
            min_sample_per_cell=4_000,
            loss_tolerance_per_lead=6.00,
            alpha=0.05, power=0.80, target_mde=0.15,
            baseline_rate=0.061, planned_volume=20_000,
            created_at=_days_ago(30), created_by="s.leroy",
            approved_by="h.oualla", approved_at=_days_ago(28),
            activated_at=_days_ago(26),
        ),
        {"elasticity": -2.2, "baseline": 0.061, "volume": 14_800,
         "adverse": 0.20, "days": 25, "pd_mean": 0.021, "pd_sd": 0.011,
         "srm_leak": {"cell": "p30", "drop": 0.18}},
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

        take-up_i = sigmoid( logit( q_ref x (p_i / p_ref)^e )
                             + lambda x z_pd,i x (p_i - p_ref) / p_ref x 10 )

    Le second terme est le mecanisme d'anti-selection : quand le prix monte,
    ce sont relativement plus les demandeurs a PD elevee - ceux qui ont le
    moins d'alternatives - qui acceptent. C'est le phenomene que la mesure du
    seul taux de conversion ne voit pas et qui fait qu'une hausse de prix
    rapporte moins qu'annonce.

    `srm_leak` simule une perte de trafic sur une cellule apres le routage :
    c'est ainsi qu'un SRM apparaît reellement en production - jamais dans le
    tirage aleatoire lui-meme, toujours dans la chaîne qui le suit.
    """
    if params.get("skip_observations"):
        return []

    # `hash()` sur une chaîne est salé par processus : l'utiliser ici rendrait
    # le jeu de démonstration different a chaque execution, ce qui contredirait
    # tout ce que GAAP affirme sur la reproductibilite. Une empreinte stable
    # est donc derivee explicitement de la cle.
    key_digest = int.from_bytes(
        hashlib.sha256(experiment.key.encode("utf-8")).digest()[:4], "big"
    )
    rng = random.Random(seed + key_digest % 100_000)
    elasticity = params["elasticity"]
    baseline = params["baseline"]
    volume = params["volume"]
    adverse = params.get("adverse", 0.0)
    days = max(1, params.get("days", 30))
    pd_mean = params.get("pd_mean", 0.021)
    pd_sd = params.get("pd_sd", 0.010)
    leak = params.get("srm_leak")

    denominator = experiment.principal * experiment.duration_factor
    control = experiment.control
    ref_rate = control.rate + (control.fee / denominator if denominator else 0.0)
    start = datetime.now(timezone.utc) - timedelta(days=days)

    rows: list[tuple] = []
    for i in range(volume):
        subject_id = f"{experiment.key}:S{i:07d}"
        allocation = assign(experiment, subject_id, enforce_status=False)
        if allocation.outcome is not AllocationOutcome.ASSIGNED:
            continue
        if leak and allocation.cell_key == leak["cell"] and rng.random() < leak["drop"]:
            continue  # trafic perdu en aval du routage

        cell = experiment.cell(allocation.cell_key)
        eff_rate = cell.rate + (cell.fee / denominator if denominator else 0.0)

        pd = max(0.0015, rng.gauss(pd_mean, pd_sd))
        z_pd = (pd - pd_mean) / pd_sd if pd_sd > 0 else 0.0
        relative_price = (eff_rate - ref_rate) / ref_rate if ref_rate else 0.0

        base = baseline * (eff_rate / ref_rate) ** elasticity if ref_rate else baseline
        probability = _sigmoid(_logit(base) + adverse * z_pd * relative_price * 10.0)
        converted = 1 if rng.random() < probability else 0

        offset = timedelta(
            days=rng.randrange(days), hours=rng.randrange(24), minutes=rng.randrange(60)
        )
        rows.append((
            experiment.key, subject_id, cell.key, converted, round(pd, 6),
            experiment.principal, "", (start + offset).replace(microsecond=0).isoformat(),
        ))
    return rows
