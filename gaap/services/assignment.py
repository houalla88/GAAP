"""Service d'affectation : le point d'entree du moteur de tarification.

C'est la seule partie de GAAP qui se trouve sur le chemin critique d'une
demande client. Elle est donc reduite au minimum : une lecture de plan, un
calcul de hachage, aucune ecriture obligatoire.

L'enregistrement de l'observation est deliberement decouple de l'affectation.
Un incident sur la collecte analytique ne doit jamais empecher de servir un
prix : en cas d'indisponibilite, le service retourne le prix de reference et
l'indique explicitement plutot que d'echouer.
"""

from __future__ import annotations

import sqlite3

from ..domain.allocation import Assignment, assign
from ..domain.models import utcnow
from ..infrastructure.repositories import ExperimentRepository, ObservationRepository

__all__ = ["AssignmentService"]


class AssignmentService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._experiments = ExperimentRepository(conn)
        self._observations = ObservationRepository(conn)

    def price_for(self, experiment_key: str, subject_id: str,
                  segment: str = "") -> Assignment | None:
        experiment = self._experiments.get(experiment_key)
        if experiment is None:
            return None
        return assign(experiment, subject_id, segment)

    def record(self, experiment_key: str, subject_id: str, cell_key: str,
               converted: bool, pd: float, principal: float, segment: str = "") -> int:
        """Enregistre l'issue commerciale d'un lead deja affecte."""
        return self._observations.record_many([(
            experiment_key, subject_id, cell_key, 1 if converted else 0,
            float(pd), float(principal), segment, utcnow(),
        )])
