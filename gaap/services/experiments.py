"""Cycle de vie d'une experience tarifaire.

Ce service porte les regles de gouvernance. Elles sont peu nombreuses et
volontairement rigides :

1. **Un plan en production est fige.** Ni les cellules, ni les poids, ni le sel
   ne peuvent etre modifies apres activation. Modifier un plan en cours de
   route revient a melanger deux experiences differentes dans un meme jeu de
   donnees - faute classique, difficile a detecter apres coup, et fatale a la
   validite du resultat.
2. **Quatre yeux.** Le concepteur ne valide pas son propre test.
3. **Aucune activation sans levee des garde-fous bloquants.** Le refus est
   journalise au meme titre que l'acceptation : un test bloque fait partie de
   l'historique de decision de l'etablissement.
"""

from __future__ import annotations

import sqlite3

from ..domain import guardrails
from ..domain.models import Experiment, ExperimentStatus, utcnow
from ..infrastructure import ledger
from ..infrastructure.repositories import ExperimentRepository, ObservationRepository

__all__ = ["ExperimentService", "LifecycleError"]


class LifecycleError(RuntimeError):
    """Transition de cycle de vie refusee par une regle de gouvernance."""


#: Transitions autorisees. Toute transition absente de cette table est refusee.
_TRANSITIONS: dict[ExperimentStatus, tuple[ExperimentStatus, ...]] = {
    ExperimentStatus.DRAFT: (ExperimentStatus.REVIEW,),
    ExperimentStatus.REVIEW: (ExperimentStatus.DRAFT, ExperimentStatus.LIVE),
    ExperimentStatus.LIVE: (ExperimentStatus.PAUSED, ExperimentStatus.CONCLUDED),
    ExperimentStatus.PAUSED: (ExperimentStatus.LIVE, ExperimentStatus.CONCLUDED),
    ExperimentStatus.CONCLUDED: (),
}


class ExperimentService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._repo = ExperimentRepository(conn)
        self._observations = ObservationRepository(conn)

    # ------------------------------------------------------------ lecture

    def get(self, key: str) -> Experiment | None:
        return self._repo.get(key)

    def list(self, status: ExperimentStatus | None = None) -> list[Experiment]:
        return self._repo.list(status)

    def config_hash(self, key: str) -> str:
        return self._repo.hash_of(key)

    # ------------------------------------------------------------ ecriture

    def create(self, experiment: Experiment, actor: str) -> Experiment:
        if self._repo.get(experiment.key) is not None:
            raise LifecycleError(f"Une experience porte deja la cle '{experiment.key}'.")
        experiment = experiment.with_status(
            ExperimentStatus.DRAFT, created_by=actor, created_at=utcnow()
        )
        digest = self._repo.save(experiment)
        ledger.append(self._conn, actor, "experiment.created", experiment.key, {
            "name": experiment.name,
            "product": experiment.product,
            "cells": [c.to_dict() for c in experiment.cells],
            "config_hash": digest,
        })
        return experiment

    def update_plan(self, experiment: Experiment, actor: str) -> Experiment:
        """Modifie un plan. Refuse des lors que le plan a ete active."""
        current = self._require(experiment.key)
        if current.status in (ExperimentStatus.LIVE, ExperimentStatus.PAUSED,
                              ExperimentStatus.CONCLUDED):
            raise LifecycleError(
                "Un plan active est fige : cellules, poids et sel ne sont plus modifiables. "
                "Conclure l'experience et en creer une nouvelle."
            )
        # Toute modification invalide la validation precedente.
        experiment = experiment.with_status(
            ExperimentStatus.DRAFT, created_by=current.created_by,
            created_at=current.created_at, approved_by="", approved_at="",
        )
        digest = self._repo.save(experiment)
        ledger.append(self._conn, actor, "experiment.updated", experiment.key, {
            "config_hash": digest,
            "note": "La validation precedente est annulee par la modification du plan.",
        })
        return experiment

    def submit_for_review(self, key: str, actor: str) -> Experiment:
        experiment = self._transition(self._require(key), ExperimentStatus.REVIEW)
        self._repo.save(experiment)
        ledger.append(self._conn, actor, "experiment.submitted", key, {
            "guardrails": guardrails.pre_launch(experiment).to_dict(),
        })
        return experiment

    def approve(self, key: str, actor: str) -> Experiment:
        """Validation par un second intervenant. Ne met pas en production."""
        experiment = self._require(key)
        if experiment.status is not ExperimentStatus.REVIEW:
            raise LifecycleError("Seul un plan en validation peut etre approuve.")
        if actor == experiment.created_by:
            raise LifecycleError(
                "Segregation des taches : le concepteur du plan ne peut pas le valider."
            )
        experiment = experiment.with_status(
            ExperimentStatus.REVIEW, approved_by=actor, approved_at=utcnow()
        )
        self._repo.save(experiment)
        ledger.append(self._conn, actor, "experiment.approved", key, {
            "approved_by": actor, "created_by": experiment.created_by,
        })
        return experiment

    def activate(self, key: str, actor: str) -> Experiment:
        """Mise en production, sous reserve de levee des garde-fous bloquants."""
        experiment = self._require(key)
        report = guardrails.pre_launch(experiment)
        if not report.cleared:
            ledger.append(self._conn, actor, "guardrail.blocked", key, {
                "blocking": [c.to_dict() for c in report.blocking],
            })
            raise LifecycleError(
                "Activation refusee par les garde-fous : "
                + " ; ".join(c.label for c in report.blocking)
            )
        experiment = self._transition(experiment, ExperimentStatus.LIVE)
        experiment = experiment.with_status(ExperimentStatus.LIVE, activated_at=utcnow())
        digest = self._repo.save(experiment)
        ledger.append(self._conn, actor, "experiment.activated", key, {
            "config_hash": digest,
            "salt": experiment.salt,
            "exposure": round(experiment.exposure, 4),
            "guardrails": report.to_dict(),
            "note": "Le sel et l'empreinte de configuration suffisent a rejouer "
                    "toute affectation servie a partir de cet instant.",
        })
        return experiment

    def pause(self, key: str, actor: str, reason: str = "") -> Experiment:
        experiment = self._transition(self._require(key), ExperimentStatus.PAUSED)
        self._repo.save(experiment)
        ledger.append(self._conn, actor, "experiment.paused", key, {"reason": reason})
        return experiment

    def resume(self, key: str, actor: str) -> Experiment:
        experiment = self._transition(self._require(key), ExperimentStatus.LIVE)
        self._repo.save(experiment)
        ledger.append(self._conn, actor, "experiment.resumed", key, {})
        return experiment

    def conclude(self, key: str, actor: str, recommendation: dict | None = None) -> Experiment:
        experiment = self._transition(self._require(key), ExperimentStatus.CONCLUDED)
        experiment = experiment.with_status(
            ExperimentStatus.CONCLUDED, concluded_at=utcnow()
        )
        self._repo.save(experiment)
        ledger.append(self._conn, actor, "experiment.concluded", key, {
            "presented": self._observations.total_presented(key),
            "recommendation": recommendation or {},
        })
        return experiment

    def record_decision(self, key: str, actor: str, recommendation: dict) -> None:
        """Ancre une decision rendue dans la piste d'audit.

        Journaliser la decision et non seulement le resultat permet de
        distinguer, des mois plus tard, ce qui a ete mesure de ce qui a ete
        decide - deux choses que les comptes rendus de comite confondent
        systematiquement.
        """
        ledger.append(self._conn, actor, "decision.rendered", key, recommendation)

    # ------------------------------------------------------------ interne

    def _require(self, key: str) -> Experiment:
        experiment = self._repo.get(key)
        if experiment is None:
            raise LifecycleError(f"Experience '{key}' introuvable.")
        return experiment

    @staticmethod
    def _transition(experiment: Experiment, target: ExperimentStatus) -> Experiment:
        allowed = _TRANSITIONS[experiment.status]
        if target not in allowed:
            raise LifecycleError(
                f"Transition refusee : {experiment.status.label} -> {target.label}."
            )
        return experiment.with_status(target)
