-- Schema GAAP. Volontairement reduit : trois tables, un index par acces reel.
--
-- Choix structurant : la configuration d'une experience est stockee comme un
-- document JSON canonique accompagne de son empreinte. Le schema relationnel
-- ne cherche pas a normaliser les cellules de prix, parce que ce qui doit etre
-- opposable ce n'est pas une ligne par cellule, c'est *la version exacte du
-- plan qui etait en vigueur* au moment ou une offre a ete servie. Un blob
-- immuable et empreinte est la representation honnete de cet objet.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS experiments (
    key          TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    product      TEXT NOT NULL,
    status       TEXT NOT NULL,
    owner        TEXT NOT NULL,
    config       TEXT NOT NULL,   -- JSON canonique du plan complet
    config_hash  TEXT NOT NULL,   -- SHA-256 du JSON canonique
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_experiments_status ON experiments(status);

-- Une observation = un kilo mis en rayon et son issue : vendu ou casse.
-- La contrainte d'unicite (experience, unite) materialise l'unicite de
-- l'affectation : un meme kilo ne peut pas etre compte deux fois dans un meme
-- test, ce qui est la premiere source de gonflement artificiel d'un resultat
-- d'experimentation.
CREATE TABLE IF NOT EXISTS observations (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_key TEXT NOT NULL REFERENCES experiments(key) ON DELETE CASCADE,
    unit_id        TEXT NOT NULL,
    cell_key       TEXT NOT NULL,
    sold           INTEGER NOT NULL CHECK (sold IN (0, 1)),
    quality_index  REAL NOT NULL,
    segment        TEXT NOT NULL DEFAULT '',
    observed_at    TEXT NOT NULL,
    UNIQUE (experiment_key, unit_id)
);

CREATE INDEX IF NOT EXISTS idx_observations_cell ON observations(experiment_key, cell_key);
CREATE INDEX IF NOT EXISTS idx_observations_date ON observations(experiment_key, observed_at);

-- Piste d'audit chaînee. Append-only : aucun UPDATE ni DELETE n'est emis par
-- l'application sur cette table.
CREATE TABLE IF NOT EXISTS audit_ledger (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at TEXT NOT NULL,
    actor       TEXT NOT NULL,
    event       TEXT NOT NULL,
    subject     TEXT NOT NULL,
    payload     TEXT NOT NULL,
    prev_hash   TEXT NOT NULL,
    entry_hash  TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_ledger_subject ON audit_ledger(subject);
