"""Depots : traduction entre les entites du domaine et le stockage.

Le domaine ne connaît pas SQL et le SQL ne connaît pas les regles metier.
Toute l'agregation qui peut etre faite par la base l'est - notamment les sommes
de carres des PD, qui permettent a la couche d'analyse de reconstituer les
variances sans jamais charger une observation unitaire en memoire.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass

from ..domain.analysis import CellAggregate
from ..domain.models import Experiment, ExperimentStatus, canonical_json, utcnow

__all__ = ["ExperimentRepository", "ObservationRepository", "DailyPoint"]


def config_hash(experiment: Experiment) -> str:
    """Empreinte du plan. Deux plans identiques ont la meme empreinte, quel que
    soit l'ordre d'ecriture des champs."""
    return hashlib.sha256(canonical_json(experiment.to_dict()).encode("utf-8")).hexdigest()


class ExperimentRepository:
    """Persistance des plans d'experience."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, experiment: Experiment) -> str:
        """Cree ou remplace un plan. Retourne l'empreinte de configuration.

        L'empreinte est retournee pour etre journalisee : c'est elle qui permet,
        des mois plus tard, de prouver quelle version du plan etait en vigueur.
        """
        payload = canonical_json(experiment.to_dict())
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        now = utcnow()
        self._conn.execute(
            """
            INSERT INTO experiments (key, name, product, status, owner, config, config_hash,
                                     created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                name = excluded.name, product = excluded.product, status = excluded.status,
                owner = excluded.owner, config = excluded.config,
                config_hash = excluded.config_hash, updated_at = excluded.updated_at
            """,
            (experiment.key, experiment.name, experiment.product, experiment.status.value,
             experiment.owner, payload, digest, experiment.created_at, now),
        )
        self._conn.commit()
        return digest

    def get(self, key: str) -> Experiment | None:
        row = self._conn.execute(
            "SELECT config FROM experiments WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        import json
        return Experiment.from_dict(json.loads(row["config"]))

    def hash_of(self, key: str) -> str:
        row = self._conn.execute(
            "SELECT config_hash FROM experiments WHERE key = ?", (key,)
        ).fetchone()
        return row["config_hash"] if row else ""

    def list(self, status: ExperimentStatus | None = None) -> list[Experiment]:
        import json
        sql = "SELECT config FROM experiments"
        params: tuple = ()
        if status is not None:
            sql += " WHERE status = ?"
            params = (status.value,)
        sql += " ORDER BY updated_at DESC"
        return [Experiment.from_dict(json.loads(r["config"]))
                for r in self._conn.execute(sql, params).fetchall()]

    def delete(self, key: str) -> None:
        self._conn.execute("DELETE FROM experiments WHERE key = ?", (key,))
        self._conn.commit()


@dataclass(frozen=True)
class DailyPoint:
    """Point d'une serie journaliere, par cellule."""

    day: str
    cell_key: str
    exposed: int
    conversions: int

    @property
    def take_up(self) -> float:
        return self.conversions / self.exposed if self.exposed else 0.0


class ObservationRepository:
    """Persistance et agregation des leads exposes."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def record_many(self, rows: list[tuple]) -> int:
        """Insere en lot. Les doublons (experience, sujet) sont ignores.

        `INSERT OR IGNORE` plutot qu'une verification prealable : l'unicite est
        garantie par la contrainte de schema, pas par une lecture applicative
        qui serait sujette a une course entre deux workers.
        """
        cursor = self._conn.executemany(
            """
            INSERT OR IGNORE INTO observations
                (experiment_key, subject_id, cell_key, converted, pd, principal, segment, observed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self._conn.commit()
        return cursor.rowcount

    def aggregates(self, experiment_key: str) -> list[CellAggregate]:
        """Agregats par cellule, calcules integralement par la base.

        Les sommes de carres conditionnelles evitent un second passage sur les
        donnees pour obtenir les variances de PD.
        """
        rows = self._conn.execute(
            """
            SELECT cell_key,
                   COUNT(*)                                   AS exposed,
                   SUM(converted)                             AS conversions,
                   SUM(pd)                                    AS pd_sum,
                   SUM(pd * pd)                               AS pd_sq_sum,
                   SUM(CASE WHEN converted = 1 THEN pd ELSE 0 END)      AS pd_sum_conv,
                   SUM(CASE WHEN converted = 1 THEN pd * pd ELSE 0 END) AS pd_sq_sum_conv
            FROM observations
            WHERE experiment_key = ?
            GROUP BY cell_key
            """,
            (experiment_key,),
        ).fetchall()
        return [
            CellAggregate(
                cell_key=r["cell_key"],
                exposed=r["exposed"],
                conversions=r["conversions"] or 0,
                pd_sum_exposed=r["pd_sum"] or 0.0,
                pd_sq_sum_exposed=r["pd_sq_sum"] or 0.0,
                pd_sum_converted=r["pd_sum_conv"] or 0.0,
                pd_sq_sum_converted=r["pd_sq_sum_conv"] or 0.0,
            )
            for r in rows
        ]

    def daily(self, experiment_key: str) -> list[DailyPoint]:
        rows = self._conn.execute(
            """
            SELECT substr(observed_at, 1, 10) AS day, cell_key,
                   COUNT(*) AS exposed, SUM(converted) AS conversions
            FROM observations
            WHERE experiment_key = ?
            GROUP BY day, cell_key
            ORDER BY day ASC
            """,
            (experiment_key,),
        ).fetchall()
        return [DailyPoint(r["day"], r["cell_key"], r["exposed"], r["conversions"] or 0)
                for r in rows]

    def total_exposed(self, experiment_key: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM observations WHERE experiment_key = ?", (experiment_key,)
        ).fetchone()
        return row["n"] if row else 0

    def purge(self, experiment_key: str) -> None:
        self._conn.execute("DELETE FROM observations WHERE experiment_key = ?", (experiment_key,))
        self._conn.commit()
