"""Entites du domaine GAAP.

Objets immuables et sans dependance a Flask ni a la base : ils peuvent etre
instancies dans un notebook, dans un test unitaire ou dans le moteur de
tarification en production sans traîner d'infrastructure.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum

from .pricing import CostStack, PriceFloor, compute_price_floor

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
    principe des quatre yeux. Un test de prix modifie ce qui est vendu en rayon,
    il ne peut pas etre mis en ligne par la seule personne qui l'a concu.
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
            "live": "En rayon",
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
    equipes commerciales manipulent reellement en produits frais :

    - `price` : le prix affiche au kilo, levier de marge unitaire ;
    - `pack_discount` : la remise consentie sur un conditionnement multiple,
      exprimee en euros par kilo, levier de volume.

    Les tester conjointement ou separement est un choix de plan d'experience ;
    GAAP ne l'impose pas, mais mesure toujours leur effet combine sur la
    contribution.
    """

    key: str
    label: str
    price: float
    weight: float
    pack_discount: float = 0.0
    is_control: bool = False

    @property
    def effective_price(self) -> float:
        """Prix reellement paye par kilo, remise de conditionnement deduite.

        Les deux leviers vivent sur la meme echelle parce qu'ils touchent la
        meme poche du client. Les traiter separement conduirait a comparer des
        cellules qui ne sont pas comparables.
        """
        return self.price - self.pack_discount

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "price": self.price,
            "weight": self.weight,
            "pack_discount": self.pack_discount,
            "is_control": self.is_control,
        }

    @staticmethod
    def from_dict(data: dict) -> "PriceCell":
        return PriceCell(
            key=data["key"],
            label=data["label"],
            price=float(data["price"]),
            weight=float(data["weight"]),
            pack_discount=float(data.get("pack_discount", 0.0)),
            is_control=bool(data.get("is_control", False)),
        )


@dataclass(frozen=True)
class Experiment:
    """Plan d'experience tarifaire complet.

    L'objet porte a la fois le design (cellules, poids, garde-fous) et le
    contexte economique (structure de cout, freinte, valeur de sauvetage). Cette
    reunion est deliberee : un plan de test qui ne connaît pas son plancher de
    rentabilite ne peut pas etre valide, et un plancher qui n'est pas fige au
    moment du lancement ne peut pas etre audite ex post.
    """

    key: str
    name: str
    product: str
    hypothesis: str
    owner: str
    salt: str
    cells: tuple[PriceCell, ...]
    cost: CostStack
    status: ExperimentStatus = ExperimentStatus.DRAFT

    # Garde-fous du plan
    holdout_share: float = 0.05
    max_exposure: float = 0.50
    max_delta_cents: float = 40.0
    max_duration_days: int = 30
    min_sample_per_cell: int = 1_000
    loss_tolerance_per_unit: float = 0.15
    excluded_segments: tuple[str, ...] = ()
    targeting: tuple[str, ...] = ()

    # Parametres statistiques figes avant lancement
    alpha: float = 0.05
    power: float = 0.80
    target_mde: float = 0.05
    baseline_sell_through: float = 0.82
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
    def reference_price(self) -> float:
        """Prix de reference : celui de la cellule de controle."""
        return self.control.price

    @property
    def price_floor(self) -> PriceFloor:
        """Plancher au taux d'ecoulement declare dans le plan."""
        return compute_price_floor(self.cost)

    def floor_at(self, sell_through: float) -> PriceFloor:
        """Plancher recalcule au taux d'ecoulement observe d'une cellule.

        En perissable, le plancher n'est pas une constante : il monte quand la
        rotation ralentit. Comparer une cellule chere a un plancher calcule sur
        la rotation du controle la flatterait.
        """
        return compute_price_floor(self.cost, sell_through)

    @property
    def exposure(self) -> float:
        """Part du volume effectivement servie a un prix different du prix courant."""
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

    def delta_cents(self, cell: PriceCell) -> float:
        """Ecart de prix d'une cellule au controle, en centimes par kilo."""
        return (cell.effective_price - self.control.effective_price) * 100.0

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
                "purchase_cost": self.cost.purchase_cost,
                "logistics_cost": self.cost.logistics_cost,
                "handling_cost": self.cost.handling_cost,
                "known_shrink": self.cost.known_shrink,
                "salvage_value": self.cost.salvage_value,
                "expected_sell_through": self.cost.expected_sell_through,
                "capital_cost": self.cost.capital_cost,
            },
            "holdout_share": self.holdout_share,
            "max_exposure": self.max_exposure,
            "max_delta_cents": self.max_delta_cents,
            "max_duration_days": self.max_duration_days,
            "min_sample_per_cell": self.min_sample_per_cell,
            "loss_tolerance_per_unit": self.loss_tolerance_per_unit,
            "excluded_segments": list(self.excluded_segments),
            "targeting": list(self.targeting),
            "alpha": self.alpha,
            "power": self.power,
            "target_mde": self.target_mde,
            "baseline_sell_through": self.baseline_sell_through,
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
            cost=CostStack(
                purchase_cost=float(cost_data["purchase_cost"]),
                logistics_cost=float(cost_data["logistics_cost"]),
                handling_cost=float(cost_data["handling_cost"]),
                known_shrink=float(cost_data.get("known_shrink", 0.06)),
                salvage_value=float(cost_data.get("salvage_value", 0.0)),
                expected_sell_through=float(cost_data.get("expected_sell_through", 0.82)),
                capital_cost=float(cost_data.get("capital_cost", 0.01)),
            ),
            status=ExperimentStatus(data.get("status", "draft")),
            holdout_share=float(data.get("holdout_share", 0.05)),
            max_exposure=float(data.get("max_exposure", 0.50)),
            max_delta_cents=float(data.get("max_delta_cents", 40.0)),
            max_duration_days=int(data.get("max_duration_days", 30)),
            min_sample_per_cell=int(data.get("min_sample_per_cell", 1_000)),
            loss_tolerance_per_unit=float(data.get("loss_tolerance_per_unit", 0.15)),
            excluded_segments=tuple(data.get("excluded_segments", ())),
            targeting=tuple(data.get("targeting", ())),
            alpha=float(data.get("alpha", 0.05)),
            power=float(data.get("power", 0.80)),
            target_mde=float(data.get("target_mde", 0.05)),
            baseline_sell_through=float(data.get("baseline_sell_through", 0.82)),
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
    """Un kilo mis en rayon, et ce qu'il en est advenu.

    L'unite d'observation est le kilo presente, vendu ou casse. Ce choix preserve
    la structure binomiale de l'analyse : chaque kilo est un succes ou un echec,
    sans etat intermediaire.

    **Limite assumee, et elle est reelle.** Les kilos d'un meme lot ne sont pas
    independants : ils partagent une implantation, une fraîcheur de depart et un
    flux client. Les intervalles de confiance calcules sous hypothese binomiale
    sont donc optimistes, et un correctif d'effet de grappe devrait leur etre
    applique en production. Le point est documente plutot que tu.

    `quality_index` est l'indice de fraîcheur du kilo a la mise en rayon, entre
    0 et 1. Il est conserve pour detecter la selection par la qualite : quand le
    prix monte, le client devient plus exigeant et prend les meilleurs articles,
    ce qui laisse un stock residuel qui se casse plus vite.
    """

    experiment_key: str
    unit_id: str
    cell_key: str
    sold: bool
    quality_index: float
    observed_at: str
    segment: str = ""
