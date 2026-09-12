# Architecture

## Couches

```
        ┌─────────────────────────────────────────────────────────┐
   web  │  vues Flask · gabarits Jinja · graphiques SVG serveur    │
   api  │  blueprint REST                                          │
        ├─────────────────────────────────────────────────────────┤
services│  cycle de vie gouverné · analyse · laboratoire · prix     │
        ├─────────────────────────────────────────────────────────┤
 domain │  Python pur : statistiques, économie, allocation,       │
        │  garde-fous, décision, entités                           │
        ├─────────────────────────────────────────────────────────┤
 infra  │  SQLite · dépôts · piste d'audit chaînée                 │
        └─────────────────────────────────────────────────────────┘
```

Les dépendances ne vont que vers le bas. Le domaine n'importe ni Flask, ni `sqlite3` : il
s'instancie dans un notebook, dans un test unitaire ou dans le moteur de tarification de production
sans traîner d'infrastructure.

## Décisions structurantes

### Le moteur n'utilise que la bibliothèque standard

Ni numpy, ni scipy, ni pandas. Les lois du χ², de Student, la normale inverse, les fonctions gamma
et bêta incomplètes sont implémentées dans `domain/stats.py` et vérifiées contre des valeurs de
référence publiées.

Trois raisons, dans cet ordre : **auditabilité** (un contrôle interne relit la formule sans
traverser une pile compilée), **reproductibilité** (aucune divergence entre recette et production
due à une version de BLAS), **portabilité** (le moteur tourne dans un conteneur minimal, au plus
près du service de tarification).

### L'affectation n'est pas stockée

Elle est une fonction pure `(sel, identifiant) → cellule`. Il n'existe donc pas de table
d'affectation susceptible de diverger du journal. Reconstituer une offre passée ne demande que le
sel et l'empreinte de configuration, tous deux ancrés dans la piste d'audit.

Corollaire : changer la fonction de hachage invalide silencieusement toute expérience en cours. Un
test épingle l'empreinte d'affectation de huit sujets pour que ce changement soit toujours délibéré.

### L'analyse travaille sur des agrégats

`analysis.analyse()` reçoit un `CellAggregate` par cellule, jamais une liste d'observations. Les
sommes de carrés des PD permettent de reconstituer les variances sans second passage. Le volume de
données traversant la couche applicative est donc constant, quel que soit le nombre de leads
exposés.

Ces agrégats sont exactement ce qu'un contrôle peut recalculer depuis le datawarehouse, ce qui rend
le résultat opposable.

### La configuration est un document immuable et empreinté

Le schéma relationnel ne normalise pas les cellules de prix. Ce qui doit être opposable n'est pas
« une ligne par cellule », c'est **la version exacte du plan en vigueur au moment où une offre a été
servie**. Un blob JSON canonique accompagné de son SHA-256 est la représentation honnête de cet
objet.

### Mesure et décision sont séparées

`analysis.analyse()` mesure, `decision.recommend()` tranche. La politique de décision est une
décision de l'établissement, pas une propriété des données. Les dissocier permet de rejouer une
règle d'arrêt différente sur des mesures inchangées, la seule manière honnête de comparer deux
politiques sans réécrire l'histoire.

### Les graphiques sont générés côté serveur

Aucune bibliothèque de visualisation, aucun CDN, aucun script en ligne. C'est ce qui rend tenable
une politique de sécurité de contenu stricte (`default-src 'self'`, sans `unsafe-inline`), vérifiée
par un test qui échoue si un gabarit réintroduit un style en ligne.

Effet de bord utile : le graphique fait partie de la réponse serveur, donc identique dans le
navigateur, dans un export PDF et dans un test.

## Modèle de données

```sql
experiments (key, name, product, status, owner, config, config_hash, created_at, updated_at)
observations (id, experiment_key, subject_id, cell_key, converted, pd, principal, segment, observed_at)
              UNIQUE (experiment_key, subject_id)
audit_ledger (seq, recorded_at, actor, event, subject, payload, prev_hash, entry_hash)
```

La contrainte d'unicité `(experiment_key, subject_id)` matérialise l'unicité de l'affectation : un
même client ne peut pas être compté deux fois dans un même test, première source de gonflement
artificiel d'un résultat d'expérimentation.

`audit_ledger` est en ajout seul : l'application n'émet ni `UPDATE` ni `DELETE` dessus.

## Passage à l'échelle

SQLite est un choix assumé pour ce moteur : quelques milliers de lignes agrégées par expérience,
écriture rare, lecture agrégée. Une base embarquée supprime une dépendance d'exploitation entière
sans rien coûter en capacité.

Le passage à PostgreSQL se limite à réécrire `infrastructure/db.py` et les requêtes de
`infrastructure/repositories.py`. Le domaine et les services n'en savent rien.

Le point chaud réel n'est pas la base mais `/api/v1/assign`, sur le chemin critique d'une demande de
crédit. Il ne fait qu'une lecture de plan et un calcul de hachage, sans écriture obligatoire :
l'enregistrement de l'observation est découplé, de sorte qu'un incident sur la collecte analytique
n'empêche jamais de servir un prix.

## Intégration

```
  moteur de tarification ──POST /api/v1/assign──▶ GAAP ──▶ prix + cellule
                         ◀──────────────────────
  chaîne commerciale ────POST /api/v1/observations──▶ GAAP
  comité de tarification ──GET /experiences/<clé>──▶ interface
  contrôle interne ──────flask verify-ledger / GET /api/v1/ledger/verify
```

GAAP est conçu pour être placé **derrière** le dispositif d'authentification de l'établissement, pas
pour le remplacer : l'en-tête `X-GAAP-Actor` fait foi pour l'identité de l'appelant. Le point est
explicite dans `api/routes.py` plutôt que sous-entendu : une piste d'audit n'a de valeur que si
l'acteur est nommé.
