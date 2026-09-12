<div align="center">

# GAAP

**G**overned **A**/B **A**ssignment for **P**ricing

*Le prix se teste comme le reste. Il ne se décide pas comme le reste.*

[![Tests](https://img.shields.io/badge/tests-162%20passants-09806c)](tests/)
[![Python](https://img.shields.io/badge/python-3.11%2B-09806c)](pyproject.toml)
[![Dépendances](https://img.shields.io/badge/moteur-stdlib%20uniquement-5439b4)](gaap/domain/)
[![Licence](https://img.shields.io/badge/licence-MIT-525a6b)](LICENSE)

</div>

---

L'acronyme est un clin d'œil assumé aux *Generally Accepted Accounting Principles*. Il dit
l'intention : appliquer au prix la même exigence que la comptabilité applique aux comptes — des
règles fixées **avant** les faits, une piste d'audit, et une opinion motivée plutôt qu'un chiffre nu.

GAAP est un moteur d'expérimentation tarifaire. Il fait pour le prix ce qu'un outil d'A/B testing
fait pour un bouton, à ceci près que les quatre choses qui comptent ne sont pas les mêmes.

## Pourquoi un test de prix n'est pas un test de bouton

| | Test visuel | Test tarifaire |
|---|---|---|
| **Réversibilité** | Un retour arrière annule tout. | Les contrats signés portent le prix testé pendant toute leur durée de vie. |
| **Coût pendant le test** | Marginal. | Chaque cellule sous-tarifée consomme de la marge en temps réel. |
| **Métrique** | Le taux de conversion suffit. | Le prix qui convertit le mieux est le plus bas admissible. Il détruit souvent de la valeur. |
| **Population** | Stable. | Le prix **sélectionne** les demandeurs : baisser attire les bons risques, monter attire les mauvais. |
| **Contrainte** | Esthétique. | Plancher de rentabilité, capital réglementaire, interdiction de segmenter sur un critère protégé. |

C'est cette asymétrie que GAAP encode. Un outil d'A/B testing généraliste branché sur un prix
donnera régulièrement la mauvaise réponse — non par défaut de rigueur statistique, mais parce qu'il
optimise la mauvaise grandeur.

---

## Le cockpit

![Cockpit GAAP](docs/assets/01-cockpit.png)

Le portefeuille d'expériences, trié par ce qui appelle une décision. Cinq situations coexistent
volontairement dans le jeu de démonstration, parce que ce sont les cinq qu'un moteur
d'expérimentation tarifaire doit savoir traiter et que la plupart des outils d'A/B testing traitent
mal :

1. **Une bascule prouvée contre le taux de conversion** — la cellule qui convertit le moins est
   celle qui rapporte le plus.
2. **Un arrêt de protection déclenché avant terme** — à 39 % d'information seulement, une cellule
   dépasse la tolérance de perte fixée avant le lancement. GAAP coupe la cellule, pas l'expérience.
3. **Un test sans effet économique malgré un écart de conversion significatif** (z = −3,92) —
   conclure sur la conversion aurait conduit à une décision que la contribution ne justifie pas.
4. **Un plan refusé avant lancement** par six garde-fous bloquants.
5. **Un test invalidé** par rupture d'allocation : les chiffres sont flatteurs, ils ne sont pas
   lisibles.

---

## Les cinq piliers

### 1. L'affectation est calculée, jamais stockée

```
u = uint64( SHA-256( sel ‖ espace ‖ identifiant )[0:8] ) / 2⁶⁴
```

Une fonction pure du sel de l'expérience et de l'identifiant du sujet. Trois conséquences directes :

- **Le client revoit le même prix.** Pas de consultation de base, pas de dérive entre deux visites.
- **Toute affectation passée est rejouable.** Reconstituer l'offre faite à un client il y a dix-huit
  mois ne demande que le sel et la version du plan, tous deux ancrés dans la piste d'audit. Aucune
  table de plusieurs centaines de millions de lignes à conserver — donc aucune seconde vérité
  susceptible de diverger de la première.
- **Les expériences sont indépendantes.** Le sel étant propre à chaque test, un sujet est
  re-randomisé de l'un à l'autre.

```bash
flask replay pp-taeg-2026q3 CLI-8842910
# Expérience : pp-taeg-2026q3 (Prêt personnel 12 500 EUR - échelle de TAEG)
# Sel        : pp-taeg-2026q3-0f4c9a
# Tirage     : 0.467401937101
# Cellule    : m45 - Affecté
# Prix servi : 6,45 %
```

Deux flux aléatoires indépendants (`holdout` et `cell`) : mélanger les deux corrélerait le groupe
témoin au prix — un biais qui n'apparaît dans aucun total.

### 2. Le plancher de rentabilité, avant tout le reste

```
r_plancher = f + o + PD × LGD + k × (h − f),    k = RW × ratio CET1
```

Refinancement, coûts opérationnels, perte attendue (Bâle / IFRS 9) et charge en capital. Une cellule
positionnée sous ce seuil détruit de la valeur actionnariale même si elle est comptablement
profitable — et GAAP **refuse de la lancer**, plutôt que de le constater après coup.

La propriété qui rend le modèle cohérent : **au prix plancher, le RAROC vaut exactement le coût des
fonds propres.** Elle est vérifiée par la suite de tests, et c'est elle qui a révélé qu'une première
version facturait à tort le refinancement sur la part d'encours financée par fonds propres.

![Fiche d'expérience](docs/assets/02-experience-verdict.png)

### 3. La décision porte sur la contribution, pas sur la conversion

```
RAC = take-up × (r_effectif − r_plancher) × K × D
```

Contribution ajustée du risque par lead exposé. C'est la **seule** métrique sur laquelle GAAP
autorise une bascule. Sur la capture ci-dessus, la cellule à −45 bps convertit à 7,87 % contre
4,04 % pour la cellule à +90 bps — et rapporte 10,25 € contre 21,65 € par lead. GAAP tranche sur la
seconde grandeur, et l'écrit dans sa motivation.

Les frais de dossier sont convertis en équivalent-taux (`frais / (K × D)`) : les deux leviers de
prix vivent sur la même échelle, parce qu'ils touchent la même poche du client.

### 4. Les garde-fous refusent par défaut

Une expérience est **refusée jusqu'à preuve du contraire**. Huit contrôles avant lancement, cinq en
production, chacun portant un code stable repris dans la piste d'audit.

![Plan refusé par les garde-fous](docs/assets/03-garde-fous-refus.png)

| Code | Contrôle | Sévérité |
|---|---|---|
| `ECO_FLOOR` | Aucune cellule sous le plancher de rentabilité | Bloquant |
| `ECO_BAND` | Amplitude tarifaire dans la bande autorisée | Bloquant |
| `RISK_EXPOSURE` | Part du trafic exposée plafonnée | Bloquant |
| `COMP_PROTECTED` | Aucun ciblage adossé à un critère de discrimination prohibé | Bloquant |
| `GOV_FOUR_EYES` | Le concepteur du plan ne le valide pas lui-même | Bloquant |
| `STAT_POWER` | Volume suffisant pour détecter l'effet déclaré | Bloquant sous 50 % du requis, avertissement au-delà |
| `STAT_HOLDOUT` | Groupe témoin préservé | Avertissement |
| `PLAN_DURATION` | Durée bornée | Avertissement |

En production s'ajoutent le contrôle SRM, la tolérance de perte par lead — un *stop-loss* tarifaire
fixé **avant** de voir les résultats — et la détection d'anti-sélection.

Un plan en production est **figé** : ni les cellules, ni les poids, ni le sel ne sont modifiables.
Modifier un plan en cours mélange deux expériences dans un même jeu de données.

### 5. Tout est scellé

![Piste d'audit](docs/assets/05-piste-audit.png)

```
h_n = SHA-256( h_{n−1} ‖ horodatage ‖ acteur ‖ événement ‖ sujet ‖ contenu canonique )
```

Journal en ajout seul. Modifier ou supprimer une entrée ancienne invalide toutes les suivantes, et
la vérification nomme le premier rang rompu **et** la nature de la rupture — chaînage (une entrée a
disparu) ou empreinte (un contenu a été réécrit).

Ce n'est pas une blockchain et ne prétend pas l'être : ni consensus, ni horodatage tiers. C'est un
journal **infalsifiable en silence**, ce qui est la propriété réellement utile pour un contrôle
interne.

Ce qui est journalisé : conception, modification, validation, activation, refus par garde-fou,
suspension, décision rendue, conclusion. Ce qui ne l'est pas : les affectations individuelles —
elles sont rejouables, les journaliser créerait une seconde vérité.

---

## Le laboratoire : payer l'information ou ne pas la payer

![Laboratoire GAAP](docs/assets/04-laboratoire.png)

Un test tarifaire consomme de la marge pendant qu'il tourne. Le lancer sans savoir s'il peut
conclure revient à payer une information qu'on n'obtiendra pas.

Le laboratoire rejoue le plan quelques centaines de fois sous une élasticité supposée et répond à
trois questions :

- **Ce plan peut-il conclure ?** Sur la capture : 67 % de chances de basculer sur la bonne cellule,
  et 25 % de basculer sur une cellule sous-optimale. Ce second chiffre est le plus intéressant — il
  ne figure sur aucun plan d'expérience classique.
- **Combien coûte l'apprentissage ?** La distribution, pas seulement la moyenne. C'est le P95 qui se
  défend en comité.
- **Avec quelle précision mesurera-t-on l'élasticité ?** Une couverture d'intervalle à 80 % au lieu
  de 95 % signale des intervalles qui mentent — défaut plus grave qu'un manque de puissance.

Graine fixée : deux exécutions sur les mêmes hypothèses donnent le même résultat.

---

## Concevoir un plan

![Nouveau plan](docs/assets/06-nouveau-plan.png)

Le dimensionnement se recalcule pendant la saisie. Un plan sous-dimensionné découvert trois semaines
après le lancement est un plan perdu.

> Enseignement du jeu de démonstration, et il est instructif : détecter **8 % relatif** sur un
> take-up de 6 % avec quatre cellules demande **52 000 leads par cellule**. Les volumes réalistes du
> portefeuille ne permettent de déclarer qu'un MDE de 15 à 18 %. GAAP force à l'écrire dans le plan
> plutôt qu'à le découvrir dans les résultats.

---

## Démarrage

```bash
pip install -r requirements.txt

export FLASK_APP=gaap
export GAAP_DATABASE=instance/gaap.sqlite

flask init-db
flask seed --reset        # portefeuille de démonstration, données 100 % synthétiques
python run.py             # http://127.0.0.1:5000
```

En production, servir par un serveur WSGI et définir `GAAP_SECRET_KEY` :

```bash
gunicorn "gaap:create_app('production')" --bind 0.0.0.0:8000 --workers 4
```

Sans `GAAP_SECRET_KEY`, l'application démarre avec une clé éphémère **et le signale dans ses
journaux** — défaut bruyant, donc visible.

### Ligne de commande

```bash
flask report pp-taeg-2026q3           # lecture complète d'une expérience en console
flask replay pp-taeg-2026q3 CLI-4821  # quel prix a été servi à ce client, et pourquoi
flask verify-ledger                   # recalcule la chaîne d'empreintes (code de sortie 1 si rompue)
```

Le même moteur est accessible par l'interface, l'API et la ligne de commande : un contrôleur peut
vérifier la piste d'audit sans dépendre du bon fonctionnement de l'application web.

---

## API

L'interface web ne consomme rien d'autre que ces routes. Ce qui est affiché est exportable, et
aucune divergence n'est possible entre ce que voit un analyste et ce qu'extrait un contrôleur.

| Route | Usage |
|---|---|
| `POST /api/v1/assign` | **Chemin critique.** Affecte un sujet et retourne le prix à servir. |
| `POST /api/v1/observations` | Enregistre l'issue commerciale d'un lead exposé. |
| `GET /api/v1/experiments/<clé>/report` | Rapport complet : cellules, tests, élasticité, garde-fous, recommandation. |
| `POST /api/v1/design/power` | Dimensionnement : taille requise et effet détectable. |
| `GET /api/v1/ledger/verify` | Vérification de la chaîne d'empreintes. |

```bash
curl -s -X POST localhost:5000/api/v1/assign \
     -H 'Content-Type: application/json' \
     -d '{"experiment":"pp-taeg-2026q3","subject_id":"CLI-8842910"}'
```
```json
{"cell": "m45", "rate": 0.0645, "fee": 0.0, "outcome": "assigned",
 "bucket": 0.467401937101, "in_analysis": true, "reason": ""}
```

`/assign` **retourne toujours un prix.** Expérience inactive, sujet hors périmètre, segment exclu :
c'est le prix de référence qui est servi, avec le motif. Un moteur de tarification ne doit jamais
avoir à gérer une absence de réponse de GAAP.

---

## Architecture

```
gaap/
├── domain/              Python pur — aucune dépendance à Flask ni à la base
│   ├── stats.py         lois, intervalles, tests, dimensionnement, séquentiel, bayésien
│   ├── pricing.py       plancher ajusté du risque, contribution, RAROC, règle de Lerner
│   ├── allocation.py    affectation déterministe par hachage
│   ├── analysis.py      lecture d'une expérience : SRM → take-up → contribution → élasticité
│   ├── guardrails.py    ce que le moteur refuse, avant et pendant
│   ├── decision.py      politique de décision (séparée de la mesure, à dessein)
│   └── models.py        entités immuables
├── infrastructure/      SQLite, dépôts, piste d'audit chaînée
├── services/            cycle de vie gouverné, analyse, laboratoire, affectation
├── api/                 blueprint REST
└── web/                 vues, gabarits, graphiques SVG générés côté serveur
```

Deux décisions structurantes méritent d'être défendues :

**Le moteur n'utilise que la bibliothèque standard.** Ni numpy, ni scipy, ni pandas. Un contrôle
interne doit pouvoir relire la formule appliquée sans traverser une pile numérique compilée, et un
résultat de tarification ne doit pas dépendre d'une version de BLAS. Les lois du χ², de Student et
la normale inverse sont implémentées et vérifiées contre des valeurs de référence publiées.

**Les graphiques sont des SVG générés côté serveur.** Aucun CDN, aucun script en ligne. C'est ce qui
rend tenable une politique de sécurité de contenu stricte — `default-src 'self'`, sans
`unsafe-inline` ni exception — vérifiée par un test qui échoue si un gabarit réintroduit un style en
ligne.

**Mesure et décision sont séparées.** `analysis.analyse()` mesure, `decision.recommend()` tranche.
C'est ce qui permet de rejouer une politique de décision différente sur des mesures inchangées : la
seule manière honnête de comparer deux règles d'arrêt.

---

## Méthode statistique

| Question | Méthode | Pourquoi celle-là |
|---|---|---|
| Intervalle sur un take-up | Score de Wilson (1927) | Conserve sa couverture aux faibles taux — le régime d'un take-up de crédit |
| Écart entre deux take-up | Newcombe (1998), méthode 10 | Couverture correcte quand un bras est volontairement peu exposé |
| Écart de contribution | Test *t* de Welch | La variance dépend du prix de la cellule : l'homoscédasticité est fausse par construction |
| Comparaisons multiples | Bonferroni | Sans correction, le risque familial atteint 14 % pour trois variantes |
| Intégrité de l'allocation | χ² d'adéquation, seuil p < 0,001 | Un échec invalide tout, quelle que soit l'apparence des chiffres |
| Arrêt anticipé | O'Brien-Fleming (Lan-DeMets) | Règle écrite avant le test, opposable, qui protège du *peeking* |
| Lecture bayésienne | Posteriors Beta sur la **contribution** | Répond à « quelle probabilité de me tromper en basculant ? » |
| Élasticité | Régression log-log pondérée | Poids = inverse de la variance de `ln p` par la méthode delta |

Deux points méritent d'être soulignés parce qu'ils sont souvent mal faits :

**La frontière séquentielle porte sur la contribution, pas sur la conversion.** Protéger du peeking
la statistique sur laquelle on ne décide pas n'a aucun sens. Le jeu de démonstration contient le cas
qui le démontre : un écart de take-up statistiquement significatif (z = −3,92) mais économiquement
neutre — intervalle sur la contribution [−1,76 ; +4,19] € par lead — où conclure sur la conversion
aurait conduit à une décision que la contribution ne justifie pas.

**Le prix optimal théorique est borné à l'enveloppe des prix testés.** La règle de Lerner
`(p* − c)/p* = −1/e` extrapole une élasticité estimée sur quelques paliers à toute la courbe. GAAP
calcule cette valeur, la signale comme extrapolation quand elle sort de l'enveloppe, et refuse de
s'en servir seule. Sortir de l'enveloppe, c'est remplacer une mesure par une hypothèse de forme
fonctionnelle.

La note de méthode complète est accessible **dans l'application** (`/methode`) — une méthode qu'il
faut aller chercher ailleurs n'est pas opposable.

---

## Ce que GAAP ne mesure pas

Cette section est aussi importante que les précédentes, et chaque recommandation la rappelle :

- La **réaction de la concurrence** à un changement de prix généralisé.
- L'effet du prix sur la **valeur client à long terme** — multi-détention, attrition, refinancement.
- La **saisonnalité** et les effets de nouveauté au-delà de la fenêtre du test.
- Le comportement des clients **exclus par garde-fou**, par construction non observés.
- La **perte réellement constatée** : seule la perte attendue à l'octroi entre dans le calcul. Toute
  conclusion sur le mélange de risque doit être confirmée sur les cohortes à douze mois.

L'anti-sélection est *détectée* — comparaison de la PD moyenne des dossiers acceptés entre
cellules — mais la PD utilisée est celle du modèle de score au moment de l'offre. Elle anticipe la
perte, elle ne la constate pas.

---

## Tests

```bash
pip install -r requirements-dev.txt
pytest                    # 162 tests, ~10 s
```

La suite ne vérifie pas des comportements mais des **propriétés** : stabilité de l'affectation,
uniformité du hachage, indépendance des flux aléatoires, cohérence du plancher et du RAROC,
détection de falsification de la piste d'audit, refus des transitions de cycle de vie illégales.

Les valeurs statistiques de référence proviennent de tables publiées, pas d'une exécution antérieure
du code : un test qui compare le code à lui-même ne vérifie rien.

Un test épingle l'empreinte d'affectation de huit sujets. Il échoue si une modification du hachage
déplace un sujet — c'est volontaire : changer la fonction d'affectation invalide silencieusement
toute expérience en cours, et doit donc être un acte délibéré.

Les captures d'écran de ce document sont régénérées par `python3 scripts/capture_screens.py` : une
capture faite à la main devient fausse dès la première évolution de l'interface, et personne ne s'en
aperçoit.

---

## Données de démonstration

**Toutes les données du portefeuille sont synthétiques.** Aucun client, aucun contrat, aucun encours
réel. Les ordres de grandeur — taux de refinancement, PD, LGD, pondération de risque, take-up — sont
choisis pour être plausibles sur un marché de crédit à la consommation européen ; ils ne constituent
ni une référence de marché, ni une recommandation tarifaire.

Le générateur est explicite et paramétré : demande à élasticité constante, plus un terme
d'anti-sélection qui fait dépendre l'acceptation du risque du demandeur lorsque le prix s'écarte de
la référence (`gaap/demo.py`).

---

## Références

- Kohavi, Tang & Xu (2020), *Trustworthy Online Controlled Experiments*, Cambridge University Press
- Wilson (1927), *JASA* 22(158) — intervalle de score
- Newcombe (1998), *Statistics in Medicine* 17(8) — différence de proportions
- O'Brien & Fleming (1979), *Biometrics* 35(3) ; Lan & DeMets (1983), *Biometrika* 70(3)
- Fleiss, Levin & Paik (2003), *Statistical Methods for Rates and Proportions*
- Lerner (1934), *Review of Economic Studies* 1(3)
- Comité de Bâle (2017), *Bâle III : finalisation des réformes* ; IFRS 9, *Instruments financiers*

---

<div align="center">
<sub><strong>DataOptimization.be</strong> — qualité des données, robustesse méthodologique, auditabilité.</sub>
</div>
