"""Piste d'audit chaînee par empreinte.

Chaque entree scelle la precedente :

    h_n = SHA-256( h_(n-1) || horodatage || acteur || evenement || sujet || payload )

Modifier ou supprimer une entree ancienne invalide toutes les suivantes, et la
verification le signale en nommant le premier rang rompu. Ce n'est pas une
blockchain et cela ne pretend pas l'etre : il n'y a ni consensus, ni preuve de
travail, ni horodatage tiers. C'est un journal **infalsifiable en silence**,
ce qui est la propriete reellement utile pour un controle interne - un
administrateur de base peut toujours reecrire la table, mais plus sans que la
verification le dise.

Ce que GAAP journalise, et ce qu'il ne journalise pas :

- **journalise** : creation et modification d'un plan, validation par un second
  intervenant, activation, blocage par garde-fou, arret, decision rendue ;
- **non journalise** : les affectations individuelles. Elles sont une fonction
  pure du sel et de l'identifiant du sujet (voir `domain.allocation`), donc
  entierement rejouables. Journaliser des centaines de millions de lignes
  redondantes n'ajouterait aucune garantie et creerait une seconde verite
  susceptible de diverger de la premiere.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass

from ..domain.models import canonical_json, utcnow

__all__ = ["AuditEntry", "ChainVerification", "GENESIS_HASH", "entry_hash", "append", "entries",
           "verify_chain", "count"]

#: Empreinte d'ancrage de la chaîne. Constante, documentee, verifiable.
GENESIS_HASH = "0" * 64


@dataclass(frozen=True)
class AuditEntry:
    seq: int
    recorded_at: str
    actor: str
    event: str
    subject: str
    payload: dict
    prev_hash: str
    entry_hash: str

    @property
    def short_hash(self) -> str:
        return self.entry_hash[:12]

    @property
    def short_prev(self) -> str:
        return self.prev_hash[:12]


def entry_hash(prev_hash: str, recorded_at: str, actor: str, event: str,
               subject: str, payload: dict) -> str:
    """Empreinte d'une entree. La serialisation du payload est canonique."""
    material = "|".join([prev_hash, recorded_at, actor, event, subject, canonical_json(payload)])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _last_hash(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT entry_hash FROM audit_ledger ORDER BY seq DESC LIMIT 1").fetchone()
    return row[0] if row else GENESIS_HASH


def append(conn: sqlite3.Connection, actor: str, event: str, subject: str,
           payload: dict | None = None) -> AuditEntry:
    """Ajoute une entree scellee. Aucune mise a jour n'est possible par la suite."""
    payload = payload or {}
    recorded_at = utcnow()
    prev = _last_hash(conn)
    digest = entry_hash(prev, recorded_at, actor, event, subject, payload)
    cursor = conn.execute(
        "INSERT INTO audit_ledger (recorded_at, actor, event, subject, payload, prev_hash, entry_hash)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (recorded_at, actor, event, subject, canonical_json(payload), prev, digest),
    )
    conn.commit()
    return AuditEntry(cursor.lastrowid, recorded_at, actor, event, subject, payload, prev, digest)


def entries(conn: sqlite3.Connection, subject: str | None = None,
            limit: int = 200) -> list[AuditEntry]:
    """Entrees les plus recentes, filtrees sur un sujet si demande."""
    sql = "SELECT seq, recorded_at, actor, event, subject, payload, prev_hash, entry_hash FROM audit_ledger"
    params: tuple = ()
    if subject:
        sql += " WHERE subject = ?"
        params = (subject,)
    sql += " ORDER BY seq DESC LIMIT ?"
    rows = conn.execute(sql, params + (limit,)).fetchall()
    return [
        AuditEntry(r[0], r[1], r[2], r[3], r[4], json.loads(r[5]), r[6], r[7])
        for r in rows
    ]


def count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM audit_ledger").fetchone()[0]


@dataclass(frozen=True)
class ChainVerification:
    """Resultat de la verification integrale de la chaîne."""

    checked: int
    intact: bool
    broken_at: int | None = None
    reason: str = ""

    @property
    def summary(self) -> str:
        if self.intact:
            return f"Chaîne verifiee : {self.checked} entrees, aucune rupture."
        return f"Rupture detectee au rang {self.broken_at} : {self.reason}"


def verify_chain(conn: sqlite3.Connection) -> ChainVerification:
    """Recalcule toute la chaîne depuis l'ancrage.

    Deux ruptures possibles et distinguees : un chaînage incoherent (une entree
    a ete supprimee ou reordonnee) et une empreinte incoherente (le contenu
    d'une entree a ete modifie). Le message les nomme separement parce que les
    causes et les suites a donner different.
    """
    rows = conn.execute(
        "SELECT seq, recorded_at, actor, event, subject, payload, prev_hash, entry_hash"
        " FROM audit_ledger ORDER BY seq ASC"
    ).fetchall()
    expected_prev = GENESIS_HASH
    for row in rows:
        seq, recorded_at, actor, event, subject, payload, prev_hash, stored_hash = row
        if prev_hash != expected_prev:
            return ChainVerification(
                len(rows), False, seq,
                "chaînage rompu (une entree anterieure a ete supprimee ou reordonnee).",
            )
        recomputed = entry_hash(prev_hash, recorded_at, actor, event, subject, json.loads(payload))
        if recomputed != stored_hash:
            return ChainVerification(
                len(rows), False, seq,
                "empreinte incoherente (le contenu de l'entree a ete modifie apres coup).",
            )
        expected_prev = stored_hash
    return ChainVerification(len(rows), True)
