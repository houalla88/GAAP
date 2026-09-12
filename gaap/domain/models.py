"""Entites du domaine GAAP.

Objets immuables et sans dependance a Flask ni a la base : ils peuvent etre
instancies dans un notebook, dans un test unitaire ou dans le service de
tarification en production sans traîner d'infrastructure.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum

from .pricing import CostOfRisk, PriceFloor, compute_price_floor

__all__ = ["ExperimentStatus", "PriceCell", "Experiment", "Observation", "utcnow", "canonical_json"]


def utcnow() -> str:
    """Horodatage ISO-8601 en UTC. Une seule source de temps dans tout GAAP."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def canonical_json(payload: dict) -> str:
    """Serialisation canonique : cles triees, separateurs fixes, UTF-8 conserve.

    Indispensable au chaînage de la piste d'audit : deux representations
    differentes du meme contenu produiraient deux empreintes differentes et
    casseraient la verification de chaîne pour une raison purement cosmetique.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class ExperimentStatus(str, Enum):
    """Cycle de vie d'un test tarifaire.

    Le passage par `REVIEW` n'est pas decoratif : c'est le point de controle du
    principe des quatre yeux. Un test de prix modifie le produit vendu, il ne
    peut pas etre mis en ligne par la seule personne qui l'a concu.
    """

    DRAFT = "draft"
    REVIEW = "review"
    LIVE = "live"
    PAUSED = "paused"
    CONCLUDED = "concluded"

    @property
    def label(self) -> str:
        return {
            "draft": "Brouillon",
            "review": "En validation",
            "live": "En production",
            "paused": "Suspendu",
            "concluded": "Conclu",
        }[self.value]

    @property
    def is_open(self) -> bool:
        return self in (ExperimentStatus.LIVE, ExperimentStatus.PAUSED)


@dataclass(frozen=True)
class PriceCell:
    """Une cellule de prix : le "variant" d'un test tarifaire.

    Le prix est decrit par deux leviers, parce que ce sont les deux que les
    equipes commerciales manipulent reellement en credit a la consommation :

    - `rate` : le taux annuel propose (TAEG), levier de marge d'interet ;
    - `fee` : les frais de dossier en euros, levier de marge immediate.

    Les tester conjointement ou separement est un choix de plan d'experience ;
    GAAP ne l'impose pas, mais mesure toujours leur effet combine sur la
    contribution.
    """

    key: str
    label: str
    rate: float
    weight: float
    fee: float = 0.0
    is_control: bool = False

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "rate": self.rate,
            "weight": self.weight,
            "fee": self.fee,
            "is_control": self.is_control,
        }

    @staticmethod
    def from_dict(data: dict) -> "PriceCell":
        return PriceCell(
            key=data["key"],
            label=data["label"],
            rate=float(data["rate"]),
            weight=float(data["weight"]),
            fee=float(data.get("fee", 0.0)),
            is_control=bool(data.get("is_control", False)),
        )


@dataclass(frozen=True)
class Experiment:
    """Plan d'experience tarifaire complet.

    L'objet porte a la fois le design (cellules, poids, garde-fous) et le
    contexte economique (cout du risque, capital, encours moyen). Cette
    reunion est deliberee : un plan de test qui ne connaît pas son plancher de
    rentabilite ne peut pas etre valide, et un plancher qui n'est pas fige au
    moment du lancement ne peut pas etre auditee ex post.
    """

    key: str
    name: str
    product: str
    hypothesis: str
    owner: str
    salt: str
    cells: tuple[PriceCell, ...]
    cost: CostOfRisk
    principal: float
    duration_factor: float
    status: ExperimentStatus = ExperimentStatus.DRAFT

    # Garde-fous du plan
    holdout_share: float = 0.05
    max_exposure: float = 0.50
    max_delta_bp: float = 120.0
    max_duration_days: int = 60
    min_sample_per_cell: int = 1_000
    loss_tolerance_per_lead: float = 0.75
    excluded_segments: tuple[str, ...] = ()
    targeting: tuple[str, ...] = ()

    # Parametres statistiques figes avant lancement
    alpha: float = 0.05
    power: float = 0.80
    target_mde: float = 0.05
    baseline_rate: float = 0.06
    planned_volume: int = 0

    # Traçabilite
    created_at: str = field(default_factory=utcnow)
    created_by: str = ""
    approved_by: str = ""
    approved_at: str = ""
    activated_at: str = ""
    concluded_at: str = ""

    # ---------------------------------------------------------------- helpers

    @property
    def control(self) -> PriceCell:
        """Cellule de controle. Un test sans controle n'est pas un test."""
        for cell in self.cells:
            if cell.is_control:
                return cell
        return self.cells[0]

    @property
    def variants(self) -> tuple[PriceCell, ...]:
        control_key = self.control.key
        return tuple(c for c in self.cells if c.key != control_key)

    @property
    def reference_rate(self) -> float:
        """Prix de reference : celui de la cellule de controle."""
        return self.control.rate

    @property
    def price_floor(self) -> PriceFloor:
        return compute_price_floor(self.cost)

    @property
    def exposure(self) -> float:
        """Part du trafic effectivement soumise a un prix different du prix courant."""
        total = sum(c.weight for c in self.cells)
        if total <= 0:
            return 0.0
        variant_weight = sum(c.weight for c in self.variants)
        return (variant_weight / total) * (1.0 - self.holdout_share)

    @property
    def comparisons(self) -> int:
        return max(1, len(self.cells) - 1)

    def cell(self, key: str) -> PriceCell | None:
        return next((c for c in self.cells if c.key == key), None)

    def delta_bp(self, cell: PriceCell) -> float:
        """Ecart de prix d'une cellule au controle, en points de base."""
        return (cell.rate - self.reference_rate) * 10_000.0

    def with_status(self, status: ExperimentStatus, **fields) -> "Experiment":
        return replace(self, status=status, **fields)

    # ------------------------------------------------------------ persistance

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "product": self.product,
            "hypothesis": self.hypothesis,
            "owner": self.owner,
            "salt": self.salt,
            "status": self.status.value,
            "cells": [c.to_dict() for c in self.cells],
            "cost": {
                "funding_rate": self.cost.funding_rate,
                "operating_cost_rate": self.cost.operating_cost_rate,
                "pd": self.cost.pd,
                "lgd": self.cost.lgd,
                "risk_weight": self.cost.risk_weight,
                "capital_ratio": self.cost.capital_ratio,
                "hurdle_rate": self.cost.hurdle_rate,
            },
            "principal": self.principal,
            "duration_factor": self.duration_factor,
            "holdout_share": self.holdout_share,
            "max_exposure": self.max_exposure,
            "max_delta_bp": self.max_delta_bp,
            "max_duration_days": self.max_duration_days,
            "min_sample_per_cell": self.min_sample_per_cell,
            "loss_tolerance_per_lead": self.loss_tolerance_per_lead,
            "excluded_segments": list(self.excluded_segments),
            "targeting": list(self.targeting),
            "alpha": self.alpha,
            "power": self.power,
            "target_mde": self.target_mde,
            "baseline_rate": self.baseline_rate,
            "planned_volume": self.planned_volume,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "activated_at": self.activated_at,
            "concluded_at": self.concluded_at,
        }

    @staticmethod
    def from_dict(data: dict) -> "Experiment":
        cost_data = data["cost"]
        return Experiment(
            key=data["key"],
            name=data["name"],
            product=data["product"],
            hypothesis=data.get("hypothesis", ""),
            owner=data.get("owner", ""),
            salt=data["salt"],
            cells=tuple(PriceCell.from_dict(c) for c in data["cells"]),
            cost=CostOfRisk(
                funding_rate=float(cost_data["funding_rate"]),
                operating_cost_rate=float(cost_data["operating_cost_rate"]),
                pd=float(cost_data["pd"]),
                lgd=float(cost_data["lgd"]),
                risk_weight=float(cost_data.get("risk_weight", 0.75)),
                capital_ratio=float(cost_data.get("capital_ratio", 0.125)),
                hurdle_rate=float(cost_data.get("hurdle_rate", 0.10)),
            ),
            principal=float(data["principal"]),
            duration_factor=float(data["duration_factor"]),
            status=ExperimentStatus(data.get("status", "draft")),
            holdout_share=float(data.get("holdout_share", 0.05)),
            max_exposure=float(data.get("max_exposure", 0.50)),
            max_delta_bp=float(data.get("max_delta_bp", 120.0)),
            max_duration_days=int(data.get("max_duration_days", 60)),
            min_sample_per_cell=int(data.get("min_sample_per_cell", 1_000)),
            loss_tolerance_per_lead=float(data.get("loss_tolerance_per_lead", 0.75)),
            excluded_segments=tuple(data.get("excluded_segments", ())),
            targeting=tuple(data.get("targeting", ())),
            alpha=float(data.get("alpha", 0.05)),
            power=float(data.get("power", 0.80)),
            target_mde=float(data.get("target_mde", 0.05)),
            baseline_rate=float(data.get("baseline_rate", 0.06)),
            planned_volume=int(data.get("planned_volume", 0)),
            created_at=data.get("created_at", utcnow()),
            created_by=data.get("created_by", ""),
            approved_by=data.get("approved_by", ""),
            approved_at=data.get("approved_at", ""),
            activated_at=data.get("activated_at", ""),
            concluded_at=data.get("concluded_at", ""),
        )


@dataclass(frozen=True)
class Observation:
    """Un lead expose a une cellule de prix, et ce qu'il en est advenu.

    `pd` est la probabilite de defaut du demandeur telle que produite par le
    moteur de score au moment de l'offre. Elle est conservee pour detecter
    l'anti-selection : c'est la variable qui distingue une hausse de marge
    reelle d'une hausse de marge compensee par une degradation du melange de
    risque.
    """

    experiment_key: str
    subject_id: str
    cell_key: str
    converted: bool
    pd: float
    principal: float
    observed_at: str
    segment: str = ""
