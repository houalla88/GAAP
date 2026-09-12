"""Acces base : SQLite, une connexion par contexte applicatif.

SQLite est un choix assume pour ce moteur. GAAP agrege quelques milliers de
lignes par experience et sert des decisions, pas du trafic transactionnel :
l'ecriture est rare, la lecture est agregee. Une base embarquee supprime une
dependance d'exploitation entiere sans rien couter en capacite.

La couche est isolee derriere `repositories` : le passage a PostgreSQL se
limite a reecrire ce module et les requetes du depot, sans toucher au domaine
ni aux services.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import click
from flask import Flask, current_app, g

__all__ = ["get_db", "close_db", "init_db", "init_app"]

_SCHEMA = Path(__file__).with_name("schema.sql")


def get_db() -> sqlite3.Connection:
    """Connexion du contexte courant, creee a la demande."""
    if "db" not in g:
        g.db = sqlite3.connect(
            current_app.config["DATABASE"],
            detect_types=sqlite3.PARSE_DECLTYPES,
            timeout=15.0,
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(exception: BaseException | None = None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    """Applique le schema. Idempotent : toutes les creations sont IF NOT EXISTS."""
    db_path = Path(current_app.config["DATABASE"])
    db_path.parent.mkdir(parents=True, exist_ok=True)
    get_db().executescript(_SCHEMA.read_text(encoding="utf-8"))


@click.command("init-db")
def init_db_command() -> None:
    """Cree ou met a jour le schema de la base."""
    init_db()
    click.echo(f"Schema applique sur {current_app.config['DATABASE']}")


def init_app(app: Flask) -> None:
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
