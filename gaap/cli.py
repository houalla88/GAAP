"""Commandes en ligne de commande.

Le meme moteur est accessible par l'interface, par l'API et par la ligne de
commande. C'est ce qui permet a un controleur de rejouer une affectation ou de
verifier la piste d'audit sans passer par l'application web - donc sans
dependre de son bon fonctionnement.
"""

from __future__ import annotations

import click
from flask import Flask
from flask.cli import with_appcontext

from .demo import build_portfolio, generate_observations
from .domain.allocation import assign
from .infrastructure import ledger
from .infrastructure.db import get_db, init_db
from .infrastructure.repositories import ExperimentRepository, ObservationRepository
from .services.analysis import AnalysisService
from .services.experiments import ExperimentService, LifecycleError

__all__ = ["register_cli"]


@click.command("seed")
@click.option("--reset", is_flag=True, help="Vide la base avant de la reconstruire.")
@with_appcontext
def seed_command(reset: bool) -> None:
    """Charge le portefeuille de demonstration (donnees entierement synthetiques)."""
    conn = get_db()
    init_db()
    if reset:
        conn.executescript(
            "DELETE FROM observations; DELETE FROM experiments; DELETE FROM audit_ledger;"
        )
        conn.commit()
        click.echo("Base videe.")

    service = ExperimentService(conn)
    repo = ExperimentRepository(conn)
    observations = ObservationRepository(conn)

    for experiment, params in build_portfolio():
        target_status = experiment.status
        creator = experiment.created_by or "demo"
        approver = experiment.approved_by or "direction.risques"

        try:
            service.create(experiment, creator)
            service.submit_for_review(experiment.key, creator)
            if experiment.approved_by:
                service.approve(experiment.key, approver)
            # Un plan laisse en validation est tout de meme soumis a
            # l'activation : c'est le refus des garde-fous qui doit apparaître
            # dans la piste d'audit, pas son absence.
            service.activate(experiment.key, creator)
        except LifecycleError as error:
            click.echo(f"  [bloque] {experiment.key} : {error}")

        # Restauration des horodatages de la demonstration : le service pose
        # necessairement des dates courantes, or le portefeuille doit presenter
        # des experiences d'anciennetes differentes.
        stored = repo.get(experiment.key)
        if stored is not None:
            repo.save(experiment)

        rows = generate_observations(experiment, params)
        if rows:
            observations.record_many(rows)

        if target_status.value == "concluded":
            report = AnalysisService(conn).report(experiment.key)
            if report:
                service.record_decision(experiment.key, approver,
                                        report.recommendation.to_dict())
            try:
                service.conclude(experiment.key, approver,
                                 report.recommendation.to_dict() if report else None)
            except LifecycleError:
                pass
            repo.save(experiment)

        click.echo(f"  {experiment.key:24} {target_status.value:10} {len(rows):>7} observations")

    click.echo(f"\nPiste d'audit : {ledger.count(conn)} entrees. "
               f"{ledger.verify_chain(conn).summary}")


@click.command("verify-ledger")
@with_appcontext
def verify_ledger_command() -> None:
    """Recalcule la chaîne d'empreintes de la piste d'audit."""
    result = ledger.verify_chain(get_db())
    click.echo(result.summary)
    raise SystemExit(0 if result.intact else 1)


@click.command("replay")
@click.argument("experiment_key")
@click.argument("unit_id")
@with_appcontext
def replay_command(experiment_key: str, unit_id: str) -> None:
    """Rejoue l'affectation d'une unite : quel prix a ete affiche, et pourquoi.

    C'est la reponse operationnelle a une reclamation ou a une demande de
    controle. Elle ne depend d'aucune table d'affectation : le sel et le plan
    suffisent.
    """
    experiment = ExperimentRepository(get_db()).get(experiment_key)
    if experiment is None:
        raise click.ClickException(f"Experience '{experiment_key}' introuvable.")
    result = assign(experiment, unit_id, enforce_status=False)
    click.echo(f"Experience   : {experiment.key} ({experiment.name})")
    click.echo(f"Sel          : {experiment.salt}")
    click.echo(f"Unite        : {unit_id}")
    click.echo(f"Tirage       : {result.bucket:.12f}")
    click.echo(f"Cellule      : {result.cell_key} - {result.outcome.label}")
    click.echo(f"Prix affiche : {result.price:.2f} EUR/kg"
               + (f", remise lot {result.pack_discount:.2f} EUR"
                  if result.pack_discount else ""))


@click.command("report")
@click.argument("experiment_key")
@with_appcontext
def report_command(experiment_key: str) -> None:
    """Affiche la lecture complete d'une experience en console."""
    report = AnalysisService(get_db()).report(experiment_key)
    if report is None:
        raise click.ClickException(f"Experience '{experiment_key}' introuvable.")

    analysis = report.analysis
    click.echo(f"\n{report.experiment.name}  [{report.experiment.status.label}]")
    click.echo(f"Plancher du plan : {analysis.floor_planned:.3f} EUR/kg")
    p_srm = (f"{analysis.srm.p_value:.1e}" if analysis.srm.p_value < 1e-4
             else f"{analysis.srm.p_value:.4f}")
    click.echo(f"SRM : p = {p_srm} "
               f"({'conforme' if analysis.srm.passed else 'ECHEC'})")
    click.echo(f"Information : {analysis.information_fraction * 100:.0f} %  "
               f"frontiere |t| >= {analysis.boundary:.2f}\n")
    click.echo(f"{'Cellule':<24}{'kg':>8}{'ecoul.':>9}{'casse':>8}"
               f"{'planch.':>9}{'EUR/kg':>9}{'t':>8}")
    for result in analysis.results:
        t_value = f"{result.contribution_test.t:.2f}" if result.contribution_test else "-"
        floor = (f"{result.floor_observed:.3f}" if result.presented else "-")
        click.echo(f"{result.cell.label:<24}{result.presented:>8}"
                   f"{result.sell_through * 100:>8.1f}%{result.waste_rate * 100:>7.1f}%"
                   f"{floor:>9}{result.contribution_per_unit:>9.3f}{t_value:>8}")
    if analysis.elasticity:
        elasticity = analysis.elasticity
        click.echo(f"\nElasticite : {elasticity.value:.2f} "
                   f"[{elasticity.ci_low:.2f} ; {elasticity.ci_high:.2f}]  "
                   f"R2 = {elasticity.r_squared:.2f}  ({elasticity.method})")
    click.echo(f"\n>> {report.recommendation.verdict.label} : {report.recommendation.headline}")
    for line in report.recommendation.rationale:
        click.echo(f"   - {line}")
    for note in report.recommendation.caveats:
        click.echo(f"   ! {note}")


def register_cli(app: Flask) -> None:
    app.cli.add_command(seed_command)
    app.cli.add_command(verify_ledger_command)
    app.cli.add_command(replay_command)
    app.cli.add_command(report_command)
