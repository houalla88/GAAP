"""Allocation deterministe des sujets aux cellules de prix.

Point central de l'architecture : **l'affectation n'est pas stockee, elle est
calculee**. C'est une fonction pure de (sel de l'experience, identifiant du
sujet, poids des cellules).

Trois proprietes en decoulent, et elles ne sont pas des details techniques :

1. **Persistance de l'offre.** Un client qui revient voit le meme prix, sans
   consultation de base. Un prix qui change entre deux visites n'est pas une
   erreur d'UX, c'est un probleme commercial et potentiellement de conformite
   sur l'information precontractuelle.
2. **Rejouabilite integrale de l'audit.** Pour reconstituer l'offre faite a un
   client donne il y a dix-huit mois, il suffit du sel et de la version de
   configuration - tous deux ancres dans la piste d'audit. Aucune table
   d'affectation de plusieurs centaines de millions de lignes a conserver, donc
   aucune divergence possible entre le journal et la realite.
3. **Independance entre experiences.** Le sel etant propre a chaque
   experience, un sujet est re-randomise d'un test a l'autre. Sans cela, les
   memes clients se retrouveraient systematiquement dans les memes bras et les
   effets de tests successifs se confondraient.

Le hachage utilise est SHA-256, choisi pour son uniformite et sa stabilite
inter-langages : une reimplementation Java du cote du moteur de tarification
produit exactement les memes affectations.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum

from .models import Experiment, PriceCell

__all__ = ["AllocationOutcome", "Assignment", "uniform_bucket", "assign", "allocation_profile"]

_UINT64 = float(1 << 64)


class AllocationOutcome(str, Enum):
    """Issue de l'affectation d'un sujet."""

    ASSIGNED = "assigned"
    HOLDOUT = "holdout"
    EXCLUDED = "excluded"
    NOT_TARGETED = "not_targeted"
    NOT_LIVE = "not_live"

    @property
    def label(self) -> str:
        return {
            "assigned": "Affecte",
            "holdout": "Temoin preserve",
            "excluded": "Segment exclu",
            "not_targeted": "Hors perimetre",
            "not_live": "Experience inactive",
        }[self.value]


@dataclass(frozen=True)
class Assignment:
    """Decision d'affectation, telle qu'elle doit etre retournee au moteur de prix."""

    experiment_key: str
    subject_id: str
    outcome: AllocationOutcome
    cell_key: str
    rate: float
    fee: float
    bucket: float
    in_analysis: bool
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "experiment": self.experiment_key,
            "subject_id": self.subject_id,
            "outcome": self.outcome.value,
            "cell": self.cell_key,
            "rate": self.rate,
            "fee": self.fee,
            "bucket": round(self.bucket, 12),
            "in_analysis": self.in_analysis,
            "reason": self.reason,
        }


def uniform_bucket(salt: str, namespace: str, subject_id: str) -> float:
    """Tirage uniforme et reproductible dans [0, 1).

    Le `namespace` separe les flux aleatoires d'une meme experience : le tirage
    qui decide du groupe temoin doit etre independant de celui qui decide de la
    cellule, faute de quoi le temoin serait correle au prix - un biais discret
    et redoutable, car il ne se voit pas dans les totaux.
    """
    digest = hashlib.sha256(f"{salt}|{namespace}|{subject_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / _UINT64


def _pick_cell(cells: tuple[PriceCell, ...], bucket: float) -> PriceCell:
    """Selection par poids cumules. Les cellules sont triees par cle pour que
    l'ordre de declaration n'influence pas l'affectation."""
    ordered = sorted(cells, key=lambda c: c.key)
    total = sum(c.weight for c in ordered)
    if total <= 0:
        return ordered[0]
    threshold = bucket * total
    cumulative = 0.0
    for cell in ordered:
        cumulative += cell.weight
        if threshold < cumulative:
            return cell
    return ordered[-1]


def assign(
    experiment: Experiment,
    subject_id: str,
    segment: str = "",
    enforce_status: bool = True,
) -> Assignment:
    """Affecte un sujet et retourne le prix a servir.

    Ordre des controles, du plus contraignant au moins contraignant. Cet ordre
    est significatif : une exclusion de segment prime toujours sur le tirage
    aleatoire, de sorte qu'un segment protege ne peut jamais etre expose a un
    prix de test, meme par accident de configuration des poids.
    """
    control = experiment.control

    def fallback(outcome: AllocationOutcome, reason: str) -> Assignment:
        return Assignment(
            experiment_key=experiment.key,
            subject_id=subject_id,
            outcome=outcome,
            cell_key=control.key,
            rate=control.rate,
            fee=control.fee,
            bucket=0.0,
            in_analysis=False,
            reason=reason,
        )

    if enforce_status and experiment.status.value != "live":
        return fallback(AllocationOutcome.NOT_LIVE, "Experience non active : prix de reference servi.")

    if segment and segment in experiment.excluded_segments:
        return fallback(AllocationOutcome.EXCLUDED, f"Segment '{segment}' exclu du test par garde-fou.")

    if experiment.targeting and segment not in experiment.targeting:
        return fallback(AllocationOutcome.NOT_TARGETED, "Sujet hors du perimetre cible.")

    if experiment.holdout_share > 0:
        holdout_bucket = uniform_bucket(experiment.salt, "holdout", subject_id)
        if holdout_bucket < experiment.holdout_share:
            return Assignment(
                experiment_key=experiment.key,
                subject_id=subject_id,
                outcome=AllocationOutcome.HOLDOUT,
                cell_key=control.key,
                rate=control.rate,
                fee=control.fee,
                bucket=holdout_bucket,
                in_analysis=False,
                reason="Temoin preserve : sert de reference longue, hors analyse courante.",
            )

    bucket = uniform_bucket(experiment.salt, "cell", subject_id)
    cell = _pick_cell(experiment.cells, bucket)
    return Assignment(
        experiment_key=experiment.key,
        subject_id=subject_id,
        outcome=AllocationOutcome.ASSIGNED,
        cell_key=cell.key,
        rate=cell.rate,
        fee=cell.fee,
        bucket=bucket,
        in_analysis=True,
    )


def allocation_profile(experiment: Experiment, sample_size: int = 20_000) -> dict[str, int]:
    """Profil d'allocation simule sur des identifiants synthetiques.

    Sert au controle avant lancement : si la repartition simulee s'ecarte des
    poids demandes, le probleme est dans le plan, pas dans le trafic. Verifier
    l'allocation avant de l'accuser est la premiere regle du diagnostic SRM.
    """
    counts = {cell.key: 0 for cell in experiment.cells}
    counts["_holdout"] = 0
    for i in range(sample_size):
        result = assign(experiment, f"probe-{i}", enforce_status=False)
        if result.outcome is AllocationOutcome.HOLDOUT:
            counts["_holdout"] += 1
        else:
            counts[result.cell_key] += 1
    return counts
