"""Interface web.

Le tableau de bord ne recalcule rien : il consomme `AnalysisService`, comme
l'API. Toute valeur affichee ici est donc recuperable en JSON, et aucune
divergence n'est possible entre ce que voit un analyste et ce qu'exporte un
controleur.

Les vues restent minces. Toute logique qui merite d'etre testee vit dans le
domaine ou dans les services ; ce qui reste ici est de la mise en forme.
"""

from __future__ import annotations

import hashlib

from flask import (Blueprint, abort, current_app, flash, redirect, render_template,
                   request, url_for)

from ..domain import stats
from ..domain.analysis import sequential_series
from ..domain.models import Experiment, ExperimentStatus, PriceCell
from ..domain.pricing import CostOfRisk
from ..infrastructure import ledger
from ..infrastructure.db import get_db
from ..infrastructure.repositories import ObservationRepository
from ..services.analysis import AnalysisService
from ..services.experiments import ExperimentService, LifecycleError
from ..domain.decision import Verdict
from ..services.simulation import SimulationInput, simulate
from . import charts

web = Blueprint("web", __name__)

#: Libelles des verdicts, pour ne jamais exposer une valeur technique a l'ecran.
VERDICT_LABELS = {v.value: (v.label, v.tone) for v in Verdict}


@web.app_context_processor
def _navigation():
    """Liste des experiences injectee dans toutes les vues pour la navigation.

    Requete unique et legere : seuls les plans sont lus, jamais les observations.
    """
    try:
        experiments = ExperimentService(get_db()).list()
    except Exception:  # pragma: no cover - la navigation ne doit jamais casser une page
        experiments = []
    return {"nav_experiments": experiments}


def _actor() -> str:
    return current_app.config["DEFAULT_ACTOR"]


@web.get("/")
def cockpit():
    """Cockpit : etat du portefeuille de tests tarifaires.

    Organise autour d'une question unique - *ou faut-il intervenir aujourd'hui ?*
    Les experiences qui demandent une decision remontent en tete, celles qui
    tournent normalement restent lisibles mais discretes.
    """
    reports = AnalysisService(get_db()).portfolio()
    observations = ObservationRepository(get_db())

    rows = []
    for report in reports:
        daily = observations.daily(report.experiment.key)
        cumulative, exposed, conversions = [], 0, 0
        for day in sorted({point.day for point in daily}):
            for point in (p for p in daily if p.day == day):
                exposed += point.exposed
                conversions += point.conversions
            if exposed:
                cumulative.append(conversions / exposed)
        rows.append({
            "report": report,
            "spark": charts.sparkline(cumulative[-30:]) if len(cumulative) > 2 else None,
        })

    order = {"invalid": 0, "protect": 1, "switch": 2, "continue": 3,
             "insufficient": 4, "keep": 5}
    rows.sort(key=lambda row: (
        order.get(row["report"].recommendation.verdict.value, 9),
        -row["report"].analysis.total_exposed,
    ))

    live = [r for r in reports if r.experiment.status is ExperimentStatus.LIVE]
    blocked = [r for r in reports if not r.pre_launch.cleared
               and r.experiment.status in (ExperimentStatus.DRAFT, ExperimentStatus.REVIEW)]
    return render_template(
        "cockpit.html",
        rows=rows,
        total_exposed=sum(r.analysis.total_exposed for r in reports),
        live_count=len(live),
        blocked_count=len(blocked),
        at_risk=[r for r in reports if not r.runtime.cleared],
        learning_cost=sum(r.analysis.learning_cost for r in reports),
        actionable=[r for r in reports
                    if r.recommendation.verdict.value in ("switch", "protect", "invalid")],
    )


@web.get("/experiences/<key>")
def experiment_detail(key: str):
    report = AnalysisService(get_db()).report(key)
    if report is None:
        abort(404)

    analysis = report.analysis
    challengers = [r for r in analysis.results if not r.is_control and r.rac_test]
    focus = max(challengers, key=lambda r: abs(r.rac_test.t)) if challengers else None

    daily = ObservationRepository(get_db()).daily(key)
    series = sequential_series(report.experiment, daily, focus.cell.key) if focus else []

    return render_template(
        "experiment.html",
        report=report,
        analysis=analysis,
        focus=focus,
        ladder=charts.price_ladder(analysis.results, report.experiment.price_floor),
        takeup=charts.takeup_chart(analysis.results, analysis.alpha_adjusted),
        elasticity_chart=charts.elasticity_chart(analysis.results, analysis.elasticity),
        contribution=charts.contribution_chart(analysis.results),
        sequential=charts.sequential_chart(
            series,
            lambda t: stats.obrien_fleming_bound(t, analysis.alpha_adjusted),
            f"Cellule suivie : {focus.cell.label}" if focus else "Aucune donnee",
        ),
        donut=charts.floor_donut(report.experiment.price_floor),
        history=ledger.entries(get_db(), subject=key, limit=40),
        config_hash=ExperimentService(get_db()).config_hash(key),
    )


@web.post("/experiences/<key>/transition")
def experiment_transition(key: str):
    """Transition de cycle de vie declenchee depuis l'interface."""
    action = request.form.get("action", "")
    service = ExperimentService(get_db())
    actor = request.form.get("actor") or _actor()
    handlers = {
        "submit": lambda: service.submit_for_review(key, actor),
        "approve": lambda: service.approve(key, actor),
        "activate": lambda: service.activate(key, actor),
        "pause": lambda: service.pause(key, actor, request.form.get("reason", "")),
        "resume": lambda: service.resume(key, actor),
        "conclude": lambda: service.conclude(key, actor),
    }
    if action not in handlers:
        flash("Action inconnue.", "danger")
        return redirect(url_for("web.experiment_detail", key=key))
    try:
        handlers[action]()
        flash(f"Action '{action}' enregistree et journalisee.", "success")
    except LifecycleError as error:
        flash(str(error), "danger")
    return redirect(url_for("web.experiment_detail", key=key))


@web.post("/experiences/<key>/decision")
def record_decision(key: str):
    """Ancre la recommandation courante dans la piste d'audit."""
    report = AnalysisService(get_db()).report(key)
    if report is None:
        abort(404)
    ExperimentService(get_db()).record_decision(
        key, _actor(), report.recommendation.to_dict()
    )
    flash("Decision ancree dans la piste d'audit.", "success")
    return redirect(url_for("web.experiment_detail", key=key))


@web.route("/experiences/nouvelle", methods=["GET", "POST"])
def experiment_new():
    """Formulaire de conception d'un plan.

    Le calcul de puissance est disponible pendant la saisie : un plan
    sous-dimensionne doit se voir avant le lancement, pas trois semaines apres.
    """
    if request.method == "POST":
        try:
            experiment = _experiment_from_form(request.form)
        except (KeyError, ValueError) as error:
            flash(f"Plan invalide : {error}", "danger")
            return redirect(url_for("web.experiment_new"))
        try:
            ExperimentService(get_db()).create(experiment, _actor())
        except LifecycleError as error:
            flash(str(error), "danger")
            return redirect(url_for("web.experiment_new"))
        flash("Plan cree en brouillon. Les garde-fous sont evalues ci-dessous.", "success")
        return redirect(url_for("web.experiment_detail", key=experiment.key))

    return render_template("new.html", defaults={
        "alpha": 0.05, "power": 0.80, "target_mde": 0.15,
        "baseline_rate": 0.06, "holdout_share": 0.05,
    })


def _default_salt(key: str) -> str:
    """Sel par defaut, derive de la cle par une empreinte stable.

    `hash()` sur une chaîne est sale par processus : s'en servir produirait un
    sel different a chaque redemarrage, donc une re-randomisation silencieuse
    des affectations.
    """
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]
    return f"{key}-{digest}"


def _experiment_from_form(form) -> Experiment:
    """Construit un plan a partir du formulaire.

    Les taux sont saisis en pourcentage et convertis ici : l'unite de saisie
    est celle du metier, l'unite de calcul est le decimal. Melanger les deux
    est une source classique d'erreur de tarification a deux ordres de grandeur.
    """
    rates = [float(v.replace(",", ".")) / 100.0 for v in form.getlist("cell_rate") if v.strip()]
    weights = [float(v.replace(",", ".")) for v in form.getlist("cell_weight") if v.strip()]
    fees = [float(v.replace(",", ".") or 0) for v in form.getlist("cell_fee")]
    if len(rates) < 2:
        raise ValueError("au moins deux cellules de prix sont necessaires")
    if len(weights) != len(rates):
        raise ValueError("chaque cellule doit porter un poids d'allocation")

    cells = []
    for index, rate in enumerate(rates):
        cells.append(PriceCell(
            key="ctl" if index == 0 else f"v{index}",
            label=(f"Controle {rate * 100:.2f} %" if index == 0
                   else f"{(rate - rates[0]) * 10000:+.0f} bps ({rate * 100:.2f} %)"),
            rate=rate,
            weight=weights[index],
            fee=fees[index] if index < len(fees) else 0.0,
            is_control=index == 0,
        ))

    def number(name: str, default: float = 0.0) -> float:
        raw = form.get(name, "").replace(",", ".").strip()
        return float(raw) if raw else default

    return Experiment(
        key=form["key"].strip(),
        name=form["name"].strip(),
        product=form.get("product", "").strip(),
        hypothesis=form.get("hypothesis", "").strip(),
        owner=form.get("owner", "").strip(),
        salt=form.get("salt", "").strip() or _default_salt(form["key"].strip()),
        cells=tuple(cells),
        cost=CostOfRisk(
            funding_rate=number("funding_rate") / 100.0,
            operating_cost_rate=number("operating_cost_rate") / 100.0,
            pd=number("pd") / 100.0,
            lgd=number("lgd") / 100.0,
            risk_weight=number("risk_weight", 75.0) / 100.0,
            capital_ratio=number("capital_ratio", 12.5) / 100.0,
            hurdle_rate=number("hurdle_rate", 11.0) / 100.0,
        ),
        principal=number("principal", 10000.0),
        duration_factor=number("duration_factor", 2.4),
        holdout_share=number("holdout_share", 5.0) / 100.0,
        max_exposure=number("max_exposure", 50.0) / 100.0,
        max_delta_bp=number("max_delta_bp", 120.0),
        max_duration_days=int(number("max_duration_days", 45)),
        min_sample_per_cell=int(number("min_sample_per_cell", 5000)),
        loss_tolerance_per_lead=number("loss_tolerance_per_lead", 5.0),
        alpha=number("alpha", 5.0) / 100.0,
        power=number("power", 80.0) / 100.0,
        target_mde=number("target_mde", 15.0) / 100.0,
        baseline_rate=number("baseline_rate", 6.0) / 100.0,
        planned_volume=int(number("planned_volume", 0)),
    )


@web.route("/laboratoire", methods=["GET", "POST"])
@web.route("/laboratoire/<key>", methods=["GET", "POST"])
def lab(key: str | None = None):
    """Pre-mortem : ce plan est-il capable de conclure, et a quel prix ?"""
    service = ExperimentService(get_db())
    experiments = service.list()
    # Le selecteur du formulaire fait foi s'il est envoye : cela permet de
    # changer de plan sans JavaScript, le `select` etant simplement poste avec
    # le reste des hypotheses.
    key = request.values.get("plan") or key
    if key is None and experiments:
        key = experiments[0].key
    experiment = service.get(key) if key else None
    if experiment is None:
        return render_template("lab.html", experiments=experiments, experiment=None, result=None)

    def number(name: str, default: float) -> float:
        raw = (request.form.get(name) or "").replace(",", ".").strip()
        try:
            return float(raw) if raw else default
        except ValueError:
            return default

    params = SimulationInput(
        true_elasticity=number("elasticity", -3.5),
        baseline_take_up=number("baseline", experiment.baseline_rate * 100) / 100.0,
        total_volume=int(number("volume", experiment.planned_volume or 40_000)),
        replications=int(number("replications", 300)),
    )
    result = simulate(experiment, params) if request.method == "POST" else None
    return render_template(
        "lab.html", experiments=experiments, experiment=experiment,
        result=result, params=params, verdict_labels=VERDICT_LABELS,
    )


@web.get("/piste-audit")
def audit_trail():
    """Piste d'audit complete, avec verification de la chaîne a la demande."""
    conn = get_db()
    return render_template(
        "ledger.html",
        entries=ledger.entries(conn, limit=200),
        verification=ledger.verify_chain(conn),
        total=ledger.count(conn),
    )


@web.get("/methode")
def methodology():
    """Note de methode : hypotheses, formules et limites, au meme endroit que l'outil."""
    return render_template("methodology.html")


@web.app_errorhandler(404)
def _not_found(_error):
    return render_template("error.html", code=404,
                           message="Cette page n'existe pas."), 404
