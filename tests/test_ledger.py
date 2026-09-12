"""Piste d'audit : la chaîne doit dire la verite, y compris quand on la falsifie."""

import json

import pytest

from gaap.infrastructure import ledger


class TestChainage:
    def test_premiere_entree_ancree_sur_le_genesis(self, conn):
        entree = ledger.append(conn, "analyste", "experiment.created", "exp-1", {"a": 1})
        assert entree.prev_hash == ledger.GENESIS_HASH
        assert len(entree.entry_hash) == 64

    def test_chaque_entree_scelle_la_precedente(self, conn):
        premiere = ledger.append(conn, "a", "e1", "exp-1", {})
        seconde = ledger.append(conn, "b", "e2", "exp-1", {})
        assert seconde.prev_hash == premiere.entry_hash

    def test_chaine_vide_est_intacte(self, conn):
        resultat = ledger.verify_chain(conn)
        assert resultat.intact and resultat.checked == 0

    def test_chaine_saine_est_verifiee(self, conn):
        for i in range(12):
            ledger.append(conn, f"acteur{i}", "experiment.updated", "exp-1", {"i": i})
        resultat = ledger.verify_chain(conn)
        assert resultat.intact and resultat.checked == 12

    def test_serialisation_canonique_stabilise_l_empreinte(self):
        """Deux ordres d'ecriture du meme contenu doivent donner la meme empreinte,
        sinon la verification casserait pour une raison purement cosmetique."""
        a = ledger.entry_hash("0" * 64, "2026-01-01T00:00:00+00:00", "x", "e", "s",
                              {"b": 2, "a": 1})
        b = ledger.entry_hash("0" * 64, "2026-01-01T00:00:00+00:00", "x", "e", "s",
                              {"a": 1, "b": 2})
        assert a == b


class TestFalsification:
    def test_modification_de_contenu_detectee(self, conn):
        for i in range(6):
            ledger.append(conn, "a", "experiment.updated", "exp-1", {"montant": i})
        conn.execute("UPDATE audit_ledger SET payload = ? WHERE seq = 3",
                     (json.dumps({"montant": 999}),))
        conn.commit()
        resultat = ledger.verify_chain(conn)
        assert not resultat.intact
        assert resultat.broken_at == 3
        assert "empreinte" in resultat.reason

    def test_suppression_d_entree_detectee(self, conn):
        for i in range(6):
            ledger.append(conn, "a", "experiment.updated", "exp-1", {"i": i})
        conn.execute("DELETE FROM audit_ledger WHERE seq = 3")
        conn.commit()
        resultat = ledger.verify_chain(conn)
        assert not resultat.intact
        assert resultat.broken_at == 4
        assert "chaînage" in resultat.reason

    def test_changement_d_acteur_detecte(self, conn):
        """Reecrire qui a valide un test est precisement ce qu'une piste d'audit
        doit rendre impossible en silence."""
        ledger.append(conn, "analyste", "experiment.created", "exp-1", {})
        ledger.append(conn, "direction.risques", "experiment.approved", "exp-1", {})
        conn.execute("UPDATE audit_ledger SET actor = 'analyste' WHERE seq = 2")
        conn.commit()
        assert not ledger.verify_chain(conn).intact


class TestLecture:
    def test_filtrage_par_sujet(self, conn):
        ledger.append(conn, "a", "e", "exp-1", {})
        ledger.append(conn, "a", "e", "exp-2", {})
        ledger.append(conn, "a", "e", "exp-1", {})
        assert len(ledger.entries(conn, subject="exp-1")) == 2
        assert ledger.count(conn) == 3

    def test_ordre_antichronologique(self, conn):
        for i in range(5):
            ledger.append(conn, "a", f"event-{i}", "exp-1", {})
        entrees = ledger.entries(conn)
        assert [e.seq for e in entrees] == [5, 4, 3, 2, 1]

    def test_payload_restitue_tel_quel(self, conn):
        payload = {"cells": [{"key": "ctl", "rate": 0.069}], "note": "accents : é à ç"}
        ledger.append(conn, "a", "e", "exp-1", payload)
        assert ledger.entries(conn)[0].payload == payload
