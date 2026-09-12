<div align="center">

# GAAP

**G**ouvernance · **A**rbitrage · **A**udit · **P**rix

*Dans votre historique, le prix n'a jamais été fixé au hasard. C'est tout le problème.*

[![Tests](https://img.shields.io/badge/tests-172%20passants-09806c)](tests/)
[![Python](https://img.shields.io/badge/python-3.11%2B-09806c)](pyproject.toml)
[![Dépendances](https://img.shields.io/badge/moteur-stdlib%20uniquement-5439b4)](gaap/domain/)
[![Licence](https://img.shields.io/badge/licence-MIT-525a6b)](LICENSE)

<sub>[English](README.md) · **Français**</sub>

</div>

---

## Ce que fait l'outil

**GAAP teste des prix en rayon, sur les fruits et légumes.** Plusieurs prix servis en parallèle à
des volumes comparables, affectés aléatoirement, avec la règle de décision écrite avant que la
première étiquette ne soit imprimée. Le verdict est exprimé en euros de marge par kilo mis en rayon.

## Pourquoi tester plutôt que modéliser

L'historique répond rarement à la question à lui seul.

Dans votre historique de rayon, le prix n'a pas été fixé au hasard. Il a bougé avec le cours du
cadran, la concurrence, le calendrier promotionnel et l'état du stock, soit les forces qui ont
également fait bouger la demande. Une régression de l'écoulement sur les prix passés mélange donc
l'effet du prix et l'effet de ce qui a fait changer le prix. C'est le problème d'identification de
l'estimation de la demande, posé par Working (1927) et inchangé depuis. Ajouter des variables de
contrôle ne le règle pas : les facteurs confondants qui comptent sont ceux que personne n'a
enregistrés.

L'identification observationnelle reste possible et mérite d'être tentée quand les conditions sont
réunies : un instrument adossé à un choc de cours amont, une régression sur discontinuité à un seuil
de calibre, une différence de différences autour d'un déploiement échelonné par magasin, ou une
expérience naturelle telle qu'une rupture d'approvisionnement. Chacune repose sur une condition que
les données ne permettent pas de vérifier. Une restriction d'exclusion est une hypothèse, pas un
résultat, et un instrument faible ramène l'estimation vers les moindres carrés qu'il devait corriger
(Bound, Jaeger & Baker, 1995). Une discontinuité n'identifie l'effet qu'au voisinage du seuil. Et
tous estiment l'élasticité d'un assortiment passé dans des conditions passées.

La randomisation fabrique la variation exogène au lieu d'espérer la trouver : sur la gamme courante,
aux paliers de prix que vous choisissez, avec un effet causal par construction.

## Pourquoi la vitesse est l'enjeu

Chaque semaine au mauvais prix est de la marge que personne ne récupère, et en produits frais c'est
aussi du stock qui part à la benne. La boucle doit donc se fermer dès que les données le permettent :
frontière d'arrêt séquentielle fixée avant le lancement, lecture bayésienne en euros par kilo, et un
laboratoire qui dit, avant la première palette engagée, si le plan est seulement capable de conclure
et ce que l'apprentissage coûtera au 95e centile.

Aller vite n'est défendable que si la perte est bornée. C'est le rôle des garde-fous : aucune cellule
sous le plancher de rentabilité, un plafond sur le volume exposé, une tolérance de perte par kilo
fixée avant tout résultat, et une piste d'audit qui rend rejouable, à partir du seul sel, le prix
affiché sur un lot donné.

**Tester, conclure, repositionner le prix, et savoir justifier la décision après coup.**

![Cockpit GAAP](docs/assets/01-cockpit.png)

<div align="center"><sub>Le cockpit : le portefeuille d'expériences, trié par ce qui appelle une décision.</sub></div>

---

### Le résultat qui résume tout

Tomates grappe, quatre paliers de prix, 68 000 kilos mis en rayon :

| Prix | Écoulement | Casse | Plancher à la rotation observée | **Marge par kilo présenté** |
|---|---|---|---|---|
| 2,75 € | **85,5 %** | **14,5 %** | 2,296 € | 0,388 € |
| 2,95 € (contrôle) | 82,1 % | 17,9 % | 2,388 € | 0,461 € |
| **3,15 €** | 78,2 % | 21,8 % | 2,502 € | **0,507 €** |
| 3,35 € | 72,0 % | 28,0 % | 2,708 € | 0,462 € |

La cellule la moins chère écoule le mieux, **et** casse le moins, **et** rapporte le moins. Un
objectif d'écoulement la désignerait. Un objectif de réduction du gaspillage la désignerait aussi.
Les deux se tromperaient de 12 % de marge.

Et la meilleure cellule n'est pas non plus la plus chère : à 3,35 € la rotation s'effondre, le
plancher grimpe à 2,708 €, et la marge gagnée part à la benne. La courbe de contribution a un maximum
intérieur, et le moteur le trouve.

### Le nom

Chaque lettre porte un pilier : la **gouvernance** refuse par défaut ce qui n'est pas admissible,
l'**arbitrage** tranche le compromis volume contre marge, l'**audit** rend chaque décision et chaque
affectation rejouables, le tout appliqué au **prix**. L'acronyme est aussi un clin d'œil aux
*Generally Accepted Accounting Principles*, et il dit la même intention : des règles fixées **avant**
les faits, une piste d'audit, et une opinion motivée plutôt qu'un chiffre nu.

---

## Pourquoi un test de prix n'est pas un test de bouton

| | Test visuel | Test de prix sur du périssable |
|---|---|---|
| **Réversibilité** | Un retour arrière annule tout. | La palette qui ne s'est pas vendue est à la benne. |
| **Coût pendant le test** | Marginal. | Chaque cellule qui tourne mal brûle du stock en temps réel. |
| **Métrique** | Le taux de conversion suffit. | Le prix qui écoule le mieux est le plus bas admissible. Il détruit souvent de la marge. |
| **Structure de coût** | Fixe. | **Le plancher dépend du prix**, parce que la rotation en dépend et que la casse suit la rotation. |
| **Population** | Stable. | Le prix **sélectionne** : plus cher, le client devient exigeant et le stock résiduel se dégrade. |

---

## Les cinq situations du jeu de démonstration

1. **Une bascule prouvée contre l'écoulement et contre la casse.** Le tableau ci-dessus.
2. **Un test encore trop jeune pour être lu.** Fraises avec remise sur lot, à 40 % de l'information
   prévue. L'effet paraît énorme, et la règle séquentielle interdit toujours de conclure.
3. **Un test sans effet économique.** Carottes, cinq centimes de plus : intervalle sur la
   contribution [−0,003 ; +0,013] € par kilo, compatible avec l'absence totale d'effet.
4. **Un plan refusé avant lancement** par cinq garde-fous bloquants, dont une cellule sous le
   plancher et un ciblage adossé à un critère protégé.
5. **Un test invalidé.** Tomates cerises, SRM à p = 4 × 10⁻⁴⁰ après une rupture de réassort sur une
   partie des magasins d'une cellule. Les chiffres semblent lisibles. Ils ne le sont pas.

---

## Les cinq piliers

### 1. L'affectation est calculée, jamais stockée

```
u = uint64( SHA-256( sel ‖ espace ‖ identifiant )[0:8] ) / 2⁶⁴
```

Une fonction pure du sel de l'expérience et de l'identifiant de l'unité. Un même lot relève toujours
de la même cellule, donc un magasin n'affiche jamais deux prix pour le même produit au même moment.
Toute affectation passée est rejouable à partir du sel, donc aucune table d'affectation n'existe pour
diverger du journal. Et le sel étant propre à chaque expérience, une unité est re-randomisée d'un
test à l'autre.

```bash
flask replay tomate-grappe-2026s37 LOT-0042117
# Experience   : tomate-grappe-2026s37 (Tomates grappe - echelle de prix)
# Sel          : tomate-grappe-2026s37-0f4c9a
# Unite        : LOT-0042117
# Tirage       : 0.467401937101
# Cellule      : m20 - Affecte
# Prix affiche : 2.75 EUR/kg
```

### 2. Un plancher de rentabilité qui bouge avec le prix

```
p_plancher = a / s − v × (1 − s) / s + c
```

Coût d'acquisition par kilo vendable, casse attendue, valeur de sauvetage, immobilisation du stock.
Le quatrième terme est le jumeau structurel d'une perte de crédit attendue : une probabilité d'échec,
`(1 − s)`, multipliée par la perte encourue, `a − v`.

**Et le plancher dépend du prix**, parce que la rotation en dépend et que la casse suit la rotation.
Sur les données de démonstration il passe de 2,08 €/kg à 95 % d'écoulement à 2,99 €/kg à 65 %. GAAP
le recalcule donc à la rotation **observée** de chaque cellule. Comparer une cellule chère, qui tourne
lentement et casse davantage, à un plancher construit sur la rotation du contrôle la flatterait
mécaniquement.

![Fiche d'expérience](docs/assets/02-experience-verdict.png)

### 3. La décision porte sur la contribution

```
C = écoulement × (prix effectif − plancher)
```

Des euros par kilo **mis en rayon**, et non par kilo vendu : c'est le kilo présenté qui est engagé,
donc c'est lui qui doit porter le rendement. De façon équivalente, `C = s × V + K`, où `V` est ce que
rapporte de vendre un kilo plutôt que de le jeter et `K` la perte sèche d'un invendu. La variance vaut
alors exactement `s(1−s)V²`, donc les intervalles se calculent sans jamais relire une observation.

### 4. Les garde-fous refusent par défaut

Huit contrôles avant lancement, cinq en production, chacun portant un code stable repris dans la
piste d'audit.

![Plan refusé par les garde-fous](docs/assets/03-garde-fous-refus.png)

| Code | Contrôle | Sévérité |
|---|---|---|
| `ECO_FLOOR` | Aucune cellule sous le plancher de rentabilité | Bloquant |
| `ECO_BAND` | Amplitude tarifaire dans la bande autorisée | Bloquant |
| `RISK_EXPOSURE` | Part du volume exposée plafonnée | Bloquant |
| `COMP_PROTECTED` | Aucun ciblage adossé à un critère de discrimination prohibé | Bloquant |
| `GOV_FOUR_EYES` | Le concepteur du plan ne le valide pas lui-même | Bloquant |
| `STAT_POWER` | Volume suffisant pour détecter l'effet déclaré | Bloquant sous 50 % du requis |
| `STAT_HOLDOUT` | Groupe témoin préservé | Avertissement |
| `PLAN_DURATION` | Durée bornée | Avertissement |

En production s'ajoutent le contrôle SRM, la tolérance de perte par kilo fixée **avant** tout
résultat, la détection de sélection par la qualité, et `ECO_FLOOR_LIVE`, qui attrape une cellule
passée sous son plancher sans qu'aucun prix n'ait bougé, simplement parce qu'elle a cessé de tourner.

Un plan en production est **figé** : cellules, poids et sel ne sont plus modifiables.

### 5. Tout est scellé

![Piste d'audit](docs/assets/05-piste-audit.png)

```
h_n = SHA-256( h_{n−1} ‖ horodatage ‖ acteur ‖ événement ‖ sujet ‖ contenu canonique )
```

Journal en ajout seul. Modifier ou supprimer une entrée ancienne invalide toutes les suivantes, et la
vérification nomme le premier rang rompu ainsi que la nature de la rupture : chaînage, une entrée a
disparu, ou empreinte, un contenu a été réécrit.

Les affectations individuelles ne sont pas journalisées. Elles sont rejouables, et les journaliser
créerait une seconde vérité.

---

## Le laboratoire : payer l'information ou ne pas la payer

![Laboratoire GAAP](docs/assets/04-laboratoire.png)

Le laboratoire rejoue le plan quelques centaines de fois sous une élasticité supposée et répond à
trois questions : le plan est-il seulement capable de conclure, que coûte l'apprentissage au 95e
centile plutôt qu'en moyenne, et avec quelle précision l'élasticité sera-t-elle mesurée. Une
couverture d'intervalle à 80 % au lieu de 95 % signale des intervalles qui mentent, défaut plus grave
qu'un manque de puissance.

La capture ci-dessus est le cas qui mérite d'être montré. Sous une élasticité supposée de
-1,0, ce plan aboutit à une décision dans toutes les réplications et désigne la cellule qui
maximise la contribution dans 5 % d'entre elles. L'écart entre cellules est trop faible pour
être lu à 72 000 kilos, si bien que le moteur conserve le prix courant 91 % du temps. C'est la
bonne réponse compte tenu des données, et une bonne raison de ne pas lancer ce plan tel quel.

Graine fixée : deux exécutions sur les mêmes hypothèses donnent le même résultat.

---

## Concevoir un plan

![Nouveau plan](docs/assets/06-nouveau-plan.png)

Le dimensionnement se recalcule pendant la saisie.

> Détecter **5 % relatif** sur un écoulement de 82 % avec quatre cellules demande environ **1 700
> kilos par cellule**. Bien plus facile que le crédit, où un take-up de 6 % exigeait des dizaines de
> milliers de leads par bras. Un taux de succès élevé se mesure à bon marché.

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

```bash
gunicorn "gaap:create_app('production')" --bind 0.0.0.0:8000 --workers 4
```

Sans `GAAP_SECRET_KEY`, l'application démarre avec une clé éphémère et le signale dans ses journaux.

### Ligne de commande

```bash
flask report tomate-grappe-2026s37              # lecture complète en console
flask replay tomate-grappe-2026s37 LOT-0042117  # quel prix ce lot portait, et pourquoi
flask verify-ledger                             # recalcule la chaîne d'empreintes
```

---

## API

| Route | Usage |
|---|---|
| `POST /api/v1/assign` | Affecte une unité et retourne le prix à afficher. |
| `POST /api/v1/observations` | Enregistre l'issue d'un kilo mis en rayon : vendu ou cassé. |
| `GET /api/v1/experiments/<clé>/report` | Rapport complet : cellules, tests, élasticité, garde-fous, recommandation. |
| `POST /api/v1/design/power` | Dimensionnement : taille requise et effet détectable. |
| `GET /api/v1/ledger/verify` | Vérification de la chaîne d'empreintes. |

`/assign` **retourne toujours un prix.** Expérience inactive, unité hors périmètre, segment exclu :
c'est le prix de référence qui est renvoyé, avec le motif.

---

## Architecture

```
gaap/
├── domain/              Python pur, aucune dépendance à Flask ni à la base
│   ├── stats.py         lois, intervalles, tests, dimensionnement, séquentiel, bayésien
│   ├── pricing.py       plancher ajusté de la casse, contribution, règle de Lerner
│   ├── allocation.py    affectation déterministe par hachage
│   ├── analysis.py      SRM → écoulement → contribution → élasticité
│   ├── guardrails.py    ce que le moteur refuse, avant et pendant
│   ├── decision.py      politique de décision, séparée de la mesure à dessein
│   └── models.py        entités immuables
├── infrastructure/      SQLite, dépôts, piste d'audit chaînée
├── services/            cycle de vie gouverné, analyse, laboratoire, affectation
├── api/                 blueprint REST
└── web/                 vues, gabarits, graphiques SVG générés côté serveur
```

**Le moteur n'utilise que la bibliothèque standard.** Ni numpy, ni scipy. Les lois du χ², de Student
et la normale inverse y sont implémentées et vérifiées contre des valeurs publiées, pour qu'un
contrôle interne puisse relire la formule appliquée sans traverser une pile numérique compilée.

**Les graphiques sont des SVG générés côté serveur.** Aucun CDN, aucun script en ligne, ce qui rend
tenable une politique de sécurité de contenu stricte, vérifiée par un test qui échoue si un gabarit
réintroduit un style en ligne.

**Mesure et décision sont séparées.** `analysis.analyse()` mesure, `decision.recommend()` tranche.

---

## Méthode statistique

| Question | Méthode | Pourquoi celle-là |
|---|---|---|
| Intervalle sur un écoulement | Score de Wilson (1927) | Conserve sa couverture aux taux extrêmes |
| Écart entre deux taux | Newcombe (1998), méthode 10 | Couverture correcte quand un bras est peu exposé |
| Écart de contribution | Test *t* de Welch | La variance dépend de `V²`, donc l'homoscédasticité est fausse |
| Comparaisons multiples | Bonferroni | Sans correction, le risque familial atteint 14 % |
| Intégrité de l'allocation | χ², seuil p < 0,001 | Un échec invalide tout |
| Arrêt anticipé | O'Brien-Fleming (Lan-DeMets) | Règle écrite avant le test, opposable |
| Lecture bayésienne | Posteriors Beta sur la **contribution** | Répond à « quelle probabilité de me tromper ? » |
| Élasticité | Régression log-log pondérée | Poids = inverse de la variance de `ln s` |

**La frontière séquentielle porte sur la contribution, pas sur l'écoulement.**

**Le prix optimal théorique est borné à l'enveloppe des prix testés.** La règle de Lerner traite en
outre le coût comme une constante, ce qu'il n'est pas ici : GAAP le donne comme une direction, jamais
comme une valeur à appliquer.

Note de méthode complète dans l'application (`/methode`) et dans
[`docs/METHODOLOGIE.md`](docs/METHODOLOGIE.md).

---

## Ce que GAAP ne mesure pas

- **L'effet de gamme.** Une baisse sur les tomates grappe déplace la demande des tomates cerises. Le
  test mesure un produit, pas un rayon.
- L'effet du prix sur la fréquentation et le panier moyen.
- La saisonnalité et les effets de nouveauté au-delà de la fenêtre du test.
- **Le couplage prix / quantité commandée.** La quantité mise en rayon est traitée comme donnée.
  L'optimiser conjointement au prix relève du problème du vendeur de journaux à prix endogène
  (Petruzzi & Dada, 1999). C'est la limite la plus sérieuse du modèle.
- Le comportement des magasins exclus par garde-fou, non observés par construction.
- La démarque réellement constatée : seule la casse attendue entre dans le calcul.

Une limite mérite sa propre ligne, parce qu'elle découle d'un choix de conception : **les kilos d'un
même lot ne sont pas indépendants.** Ils partagent une implantation, une fraîcheur de départ et un
flux client. Les intervalles calculés sous hypothèse binomiale sont donc optimistes, et un correctif
d'effet de grappe s'appliquerait en production. Chaque recommandation du moteur porte cette réserve.

---

## Tests

```bash
pip install -r requirements-dev.txt
pytest                    # 172 tests, ~9 s
```

La suite vérifie des **propriétés**, pas des comportements : stabilité de l'affectation, uniformité du
hachage, indépendance des flux aléatoires, cohérence du plancher, détection de falsification du
journal, refus des transitions de cycle de vie illégales. Les valeurs statistiques de référence
proviennent de tables publiées, pas d'une exécution antérieure du code.

---

## Données de démonstration

**Tous les chiffres sont synthétiques.** Aucun fournisseur, aucun magasin, aucun volume réel. Les
ordres de grandeur sont choisis pour être plausibles chez un distributeur alimentaire européen ; ils
ne constituent ni une référence de marché, ni une recommandation tarifaire.

---

## Références

- Working (1927), *QJE* 41(2) : le problème d'identification de la demande
- Berry, Levinsohn & Pakes (1995), *Econometrica* 63(4) ; Bound, Jaeger & Baker (1995), *JASA* 90(430)
- Angrist & Pischke (2009), *Mostly Harmless Econometrics*
- Kohavi, Tang & Xu (2020), *Trustworthy Online Controlled Experiments*
- Wilson (1927), *JASA* 22(158) ; Newcombe (1998), *Statistics in Medicine* 17(8)
- O'Brien & Fleming (1979), *Biometrics* 35(3) ; Lan & DeMets (1983), *Biometrika* 70(3)
- Fleiss, Levin & Paik (2003), *Statistical Methods for Rates and Proportions*
- Lerner (1934), *Review of Economic Studies* 1(3)
- Petruzzi & Dada (1999), *Operations Research* 47(2) : tarification et problème du vendeur de journaux

---

<div align="center">

**[DataOptimization.be](https://www.dataoptimization.be)**

<sub>Conseil en data science appliquée au pricing, à la sensibilité au prix,<br>
au comportement client et à l'architecture analytique.</sub>

</div>
