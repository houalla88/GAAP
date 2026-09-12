"""API REST de GAAP.

Deux publics distincts, deliberement servis par le meme socle :

- le **moteur de tarification**, qui appelle `/assign` sur le chemin critique
  d'une demande de credit et attend une reponse simple et rapide ;
- les **equipes analytiques**, qui recuperent le rapport complet d'une
  experience pour le rejouer dans leurs propres outils.

L'interface web consomme exactement ces routes : ce qui est affiche est ce qui
est exposable, il ne peut pas y avoir de calcul present dans le tableau de bord
et absent de l'API.
"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from .. import __version__
from ..domain import stats
from ..infrastructure import ledger
from ..infrastructure.db import get_db
from ..services.analysis import AnalysisService
from ..services.assignment import AssignmentService
from ..services.experiments import ExperimentService

api = Blueprint("api", __name__, url_prefix="/api/v1")


def _actor() -> str:
    """Identite de l'appelant.

    En l'etat, l'en-tete `X-GAAP-Actor` fait foi : GAAP est concu pour etre
    place derriere le dispositif d'authentification de l'etablissement, pas
    pour le remplacer. Le point est explicite ici plutot que sous-entendu.
    """
    return request.headers.get("X-GAAP-Actor") or current_app.config["DEFAULT_ACTOR"]


@api.get("/health")
def health():
    return jsonify({"status": "ok", "service": "gaap", "version": __version__})


@api.get("/experiments")
def list_experiments():
    service = ExperimentService(get_db())
    return jsonify({
        "experiments": [
            {
                "key": e.key, "name": e.name, "product": e.product,
                "status": e.status.value, "owner": e.owner,
                "cells": len(e.cells), "exposure": round(e.exposure, 4),
                "floor_rate": round(e.price_floor.total, 6),
            }
            for e in service.list()
        ]
    })


@api.get("/experiments/<key>")
def get_experiment(key: str):
    experiment = ExperimentService(get_db()).get(key)
    if experiment is None:
        return jsonify({"error": "experiment_not_found", "key": key}), 404
    return jsonify(experiment.to_dict())


@api.get("/experiments/<key>/report")
def get_report(key: str):
    report = AnalysisService(get_db()).report(key)
    if report is None:
        return jsonify({"error": "experiment_not_found", "key": key}), 404
    return jsonify(report.to_dict())


@api.post("/assign")
def post_assign():
    """Affecte un sujet et retourne le prix a servir.

    Retourne toujours un prix : si l'experience est inactive, hors perimetre
    ou inconnue du sujet, c'est le prix de reference qui est renvoye, avec le
    motif. Un moteur de tarification ne doit jamais avoir a gerer une absence
    de reponse de GAAP.
    """
    payload = request.get_json(silent=True) or {}
    key = payload.get("experiment")
    subject_id = payload.get("subject_id")
    if not key or not subject_id:
        return jsonify({"error": "missing_parameters",
                        "detail": "'experiment' et 'subject_id' sont requis."}), 400
    assignment = AssignmentService(get_db()).price_for(key, subject_id, payload.get("segment", ""))
    if assignment is None:
        return jsonify({"error": "experiment_not_found", "key": key}), 404
    return jsonify(assignment.to_dict())


@api.post("/observations")
def post_observation():
    """Enregistre l'issue commerciale d'un lead expose."""
    payload = request.get_json(silent=True) or {}
    required = ("experiment", "subject_id", "cell", "converted")
    missing = [field for field in required if field not in payload]
    if missing:
        return jsonify({"error": "missing_parameters", "fields": missing}), 400
    written = AssignmentService(get_db()).record(
        experiment_key=payload["experiment"],
        subject_id=payload["subject_id"],
        cell_key=payload["cell"],
        converted=bool(payload["converted"]),
        pd=float(payload.get("pd", 0.0)),
        principal=float(payload.get("principal", 0.0)),
        segment=payload.get("segment", ""),
    )
    return jsonify({"recorded": written}), 201 if written else 200


@api.post("/design/power")
def post_power():
    """Dimensionnement d'un plan : taille requise et effet detectable.

    Utilisee par le formulaire de creation pour que le concepteur voie, pendant
    qu'il saisit, si son plan est capable de conclure. Un plan sous-dimensionne
    decouvert trois semaines apres le lancement est un plan perdu.
    """
    payload = request.get_json(silent=True) or {}
    try:
        baseline = float(payload.get("baseline_rate", 0.06))
        mde = float(payload.get("target_mde", 0.05))
        alpha = float(payload.get("alpha", 0.05))
        power = float(payload.get("power", 0.80))
        cells = max(2, int(payload.get("cells", 2)))
        volume = int(payload.get("planned_volume", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "invalid_parameters"}), 400

    if not 0.0 < baseline < 1.0:
        return jsonify({"error": "invalid_parameters",
                        "detail": "baseline_rate doit etre dans ]0, 1["}), 400

    alpha_adjusted = stats.bonferroni(alpha, cells - 1)
    required = stats.required_sample_size_per_arm(baseline, mde, alpha_adjusted, power)
    available = volume // cells if volume else 0
    return jsonify({
        "alpha_adjusted": round(alpha_adjusted, 5),
        "comparisons": cells - 1,
        "required_per_cell": required,
        "required_total": required * cells,
        "available_per_cell": available,
        "sufficient": bool(available >= required) if volume else None,
        "detectable_effect": (round(stats.detectable_effect(baseline, available, alpha_adjusted, power), 5)
                              if available > 0 else None),
    })


@api.get("/ledger/verify")
def verify_ledger():
    result = ledger.verify_chain(get_db())
    return jsonify({
        "intact": result.intact,
        "checked": result.checked,
        "broken_at": result.broken_at,
        "summary": result.summary,
    })


@api.errorhandler(404)
def _not_found(_error):
    return jsonify({"error": "not_found"}), 404
