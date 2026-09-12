# Note de méthode

Document de référence de GAAP : formules appliquées, hypothèses retenues, limites assumées.
Les docstrings du code renvoient à ce fichier. Une version condensée est servie par l'application
elle-même sur `/methode`, parce qu'une méthode qu'il faut aller chercher ailleurs n'est pas
opposable.

---

## 1. Pourquoi randomiser

Le moteur repose sur une affectation aléatoire. Ce choix demande à être justifié, parce que
l'alternative, estimer l'élasticité sur l'historique, est moins coûteuse et souvent déjà disponible.

### 1.1 Le problème d'identification

Dans un historique de rayon, le prix n'est pas une variable exogène. Il a été fixé en réponse au
cours du cadran, à la concurrence, au calendrier promotionnel et à l'état du stock, c'est-à-dire aux
mêmes facteurs qui déterminent la demande. Une régression de l'écoulement sur les prix observés
estime donc un mélange de l'effet causal du prix et de l'effet des variables qui ont fait varier le
prix.

Le résultat est un biais de simultanéité dont le signe n'est pas connu a priori. Il peut faire
apparaître une demande plus inélastique qu'elle ne l'est, si les hausses de prix ont accompagné des
périodes de forte demande, ou l'inverse. Aucune statistique d'ajustement ne le révèle : un R² élevé
est compatible avec une élasticité fausse d'un facteur deux.

Le problème est ancien et bien posé. Working (1927) montre qu'une courbe ajustée sur des couples
prix-quantité observés n'est en général ni une courbe d'offre ni une courbe de demande, mais le lieu
de leurs intersections successives. Ajouter des variables de contrôle ne le résout pas, puisque les
facteurs confondants pertinents sont précisément ceux qui n'ont pas été enregistrés.

### 1.2 Ce que l'observationnel permet malgré tout

L'identification causale à partir de données observationnelles est possible, et doit être tentée
lorsque les conditions sont réunies. Quatre plans sont crédibles en distribution alimentaire :

| Plan | Source de variation exogène | Condition d'identification |
|---|---|---|
| Variables instrumentales | Un choc de cours amont sans effet direct sur la demande locale | Pertinence et restriction d'exclusion |
| Régression sur discontinuité | Un saut mécanique de la grille à un seuil de calibre ou de catégorie | Continuité des autres déterminants au seuil |
| Différence de différences | Un déploiement tarifaire échelonné par magasin ou par région | Tendances parallèles en l'absence de traitement |
| Expérience naturelle | Rupture d'approvisionnement, ouverture d'un concurrent | Exogénéité de l'événement par rapport à la demande |

Chacune de ces conditions est une hypothèse, non un résultat testable sur les données. Trois limites
en découlent :

1. **La restriction d'exclusion ne se teste pas.** Un instrument dont la validité est douteuse
   produit une estimation dont on ne sait pas si elle vaut mieux que les moindres carrés.
2. **Un instrument faible est dangereux.** Lorsque la corrélation entre l'instrument et le prix est
   ténue, l'estimateur à variables instrumentales est biaisé dans la direction des moindres carrés
   qu'il devait corriger, et son intervalle de confiance est trompeur (Bound, Jaeger & Baker, 1995).
3. **La portée est locale.** Une discontinuité identifie l'effet au voisinage du seuil, une
   expérience naturelle sur la seule population et la seule plage de prix touchées par l'événement.

S'y ajoute une limite commune : ces plans estiment l'élasticité d'un assortiment passé, dans des
conditions de marché passées. Ce n'est pas nécessairement celle du rayon à tarifer.

### 1.3 Ce que la randomisation apporte

L'affectation aléatoire fabrique la variation exogène au lieu d'espérer la rencontrer :

- **Validité interne par construction.** L'indépendance entre le prix affiché et les
  caractéristiques du lot est garantie par le plan, pas supposée.
- **Choix du domaine de mesure.** Les paliers de prix sont choisis, donc l'élasticité est estimée là
  où la décision se pose, et non là où l'histoire a laissé de la variation.
- **Séparation du prix et de la sélection.** La qualité du stock résiduel dépend du prix affiché :
  randomiser le prix permet d'observer cette déformation, ce qu'aucun plan observationnel ne fait
  proprement.

**Ce que la randomisation n'apporte pas.** La validité externe n'est pas garantie : l'effet mesuré
vaut pour les magasins exposés, la fenêtre du test et la plage de prix testée. Extrapoler au-delà
reste une hypothèse de modèle, et c'est la raison pour laquelle le prix optimal dérivé de la règle de
Lerner est borné à l'enveloppe des prix effectivement servis (section 5).

---

## 2. Modèle économique

### 2.1 Plancher de rentabilité

```
p_plancher = a / s − v × (1 − s) / s + c
```

| Terme | Signification | Source dans un dispositif réel |
|---|---|---|
| `a` | Coût d'acquisition par kilo **vendable** | `(achat + logistique + manutention) / (1 − freinte)` |
| `s` | Taux d'écoulement | Historique, puis mesuré par le test |
| `v` | Valeur de sauvetage d'un invendu | Don défiscalisé, transformation, alimentation animale |
| `c` | Coût d'immobilisation du stock | Coût du capital circulant appliqué à la rotation |

La freinte connue divise plutôt qu'elle ne soustrait : si 6 % du poids livré part au parage, il faut
acheter `1 / 0,94` kilo pour en présenter un.

La forme additive affichée dans l'interface sépare les cinq postes :

```
p_plancher = achat/(1−f) + logistique/(1−f) + manutention/(1−f) + (1−s)/s × (a − v) + c
```

Le quatrième terme est la **perte attendue sur invendus**. C'est l'analogue structurel exact d'une
perte de crédit : une probabilité d'échec, ici `(1 − s)`, multipliée par la perte encourue en cas
d'échec, ici `a − v`.

### 2.2 Le plancher dépend du prix

C'est la particularité du périssable, et tout l'intérêt du domaine. Baisser le prix accélère la
rotation, donc réduit la casse, donc abaisse le coût complet par kilo vendu. Le relever fait
l'inverse : la marge gagnée est en partie mangée par les invendus.

Sur le jeu de démonstration, l'effet est massif :

| Écoulement observé | Plancher |
|---|---|
| 95 % | 2,08 EUR/kg |
| 82 % | 2,39 EUR/kg |
| 65 % | 2,99 EUR/kg |

GAAP recalcule donc le plancher au taux d'écoulement **observé** de chaque cellule, et non au taux
déclaré dans le plan. Comparer une cellule chère, qui tourne lentement et casse davantage, à un
plancher calculé sur la rotation du contrôle la flatterait mécaniquement.

C'est aussi ce couplage qui crée un **optimum intérieur** : monter le prix augmente la contribution
jusqu'au point où la casse supplémentaire la reprend.

**Simplifications assumées**, avec le sens de leur effet :

| Simplification | Effet sur la conclusion |
|---|---|
| Pas d'effet de gamme | Surestime le gain d'une baisse, qui cannibalise les produits voisins |
| Fidélisation induite par un prix d'appel non valorisée | Sous-estime le gain d'une baisse |
| Freinte connue supposée indépendante du prix | Biais faible, le parage dépendant peu de la rotation |
| Quantité commandée traitée comme donnée | Voir section 8 |

### 2.3 Métrique de décision

```
C = s × (p_effectif − p_plancher(s))
```

Contribution en euros par kilo **mis en rayon**, et non par kilo vendu : c'est le kilo présenté qui
est engagé, donc c'est lui qui doit porter le rendement.

Décomposition équivalente, et c'est elle qui donne la variance en forme fermée :

```
C = s × V + K      avec   V = p − v − c   et   K = v − a
Var(C) = s (1 − s) V²
```

`V` est ce que rapporte de vendre un kilo plutôt que de le casser, `K` la perte sèche d'un invendu.
La linéarité en `s` permet de calculer les intervalles sans jamais relire une observation unitaire.

### 2.4 Mise en équivalence des leviers de prix

```
p_effectif = p_affiché − remise_sur_lot
```

Les remises sur conditionnement multiple sont déduites du prix affiché, afin que les deux leviers
vivent sur la même échelle : ils touchent la même poche du client.

---

## 3. Affectation

```
u = uint64( SHA-256( sel ‖ espace ‖ identifiant )[0:8] ) / 2⁶⁴
```

SHA-256 est retenu pour son uniformité et sa stabilité inter-langages : une réimplémentation Java
côté système d'étiquetage produit exactement les mêmes affectations.

Deux espaces de nommage indépendants, `holdout` et `cell`. Les mélanger corrélerait le groupe témoin
au prix : biais discret, invisible dans les totaux, et fatal à l'interprétation.

Ordre des contrôles, du plus contraignant au moins contraignant :

1. Expérience active ?
2. Segment exclu ?
3. Dans le périmètre ciblé ?
4. Groupe témoin préservé ?
5. Tirage de cellule.

Cet ordre garantit qu'un segment exclu ne peut jamais être exposé, même par accident de
configuration des poids.

### Unité d'observation

L'unité est le **kilo présenté**, vendu ou cassé. Ce choix préserve la structure binomiale de
l'analyse : chaque kilo est un succès ou un échec, exactement comme un lead convertissait ou non.

**Limite assumée, et elle est réelle.** Les kilos d'un même lot ne sont pas indépendants : ils
partagent une implantation, une fraîcheur de départ et un flux client. Les intervalles calculés sous
hypothèse binomiale sont donc **optimistes**, et un correctif d'effet de grappe devrait leur être
appliqué en production. L'ordre de grandeur du correctif dépend de la corrélation intra-lot, qui se
mesure sur les données réelles et qui n'est pas simulable ici.

---

## 4. Inférence

### 4.1 Intervalles

- **Une proportion** : score de Wilson (1927). Reste dans [0, 1] et conserve sa couverture aux taux
  extrêmes, le régime d'un écoulement de produit frais, qui vit entre 60 % et 95 %.
- **Différence de deux proportions** : méthode hybride de Newcombe (1998, méthode 10), construite
  sur les bornes de Wilson de chaque bras.

### 4.2 Métrique continue

Test `t` de Welch. La variance de la contribution dépend du prix de la cellule, via `V²` :
l'homoscédasticité du test de Student classique est fausse par construction dans un test tarifaire.

### 4.3 Comparaisons multiples

Correction de Bonferroni sur le nombre de comparaisons au contrôle. Sans correction, le risque de
première espèce familial dérive vers `1 − (1 − α)^(k−1)`, soit 14 % pour trois variantes à α = 5 %.

### 4.4 Intégrité de l'allocation (SRM)

χ² d'adéquation entre allocation observée et poids déclarés, seuil sévère à **p < 0,001**
(convention Kohavi). Un échec invalide la lecture, quelle que soit l'apparence des chiffres.

Causes réelles en distribution : rupture de réassort sur une partie des magasins d'une cellule,
étiquette non posée, exclusion asymétrique par le système de caisse. Jamais le tirage aléatoire
lui-même, ce qui est vérifiable en simulant l'allocation sur des identifiants synthétiques
(`allocation_profile`).

### 4.5 Arrêt séquentiel

Frontière de type O'Brien-Fleming, approximation de Lan-DeMets :

```
z*(t) = z_{α/2} / √t
```

Très conservatrice au début, elle converge vers le seuil nominal à la fin.

**La frontière porte sur la contribution, pas sur le taux d'écoulement.** Protéger du *peeking* la
statistique sur laquelle on ne décide pas n'aurait aucun sens.

### 4.6 Lecture bayésienne

Posteriors Beta à prior uniforme `Beta(1, 1)`, sur la **contribution** :

```
P( s_B × V_B  >  s_A × V_A )
```

estimée par Monte-Carlo à graine dérivée déterministiquement des comptages. La perte attendue
`E[max(C_A − C_B, 0)]` est exprimée en **euros par kilo présenté**, directement comparable à la
tolérance de perte fixée dans le plan.

### 4.7 Dimensionnement

```
n_par_bras = ( z_{1−α/2} √(2 p̄ q̄) + z_{1−β} √(p₁q₁ + p₂q₂) )² / (p₁ − p₂)²
```

Formule classique à deux proportions (Fleiss, Levin & Paik), sans correction de continuité.

Ordre de grandeur : détecter **5 % relatif** sur un écoulement de 82 %, avec quatre cellules et α
corrigé, demande environ **1 700 kilos par cellule**. Le régime est beaucoup plus favorable qu'en
crédit, où un take-up de 6 % exigeait des dizaines de milliers d'observations par bras : c'est
l'avantage d'un taux de succès élevé.

---

## 5. Élasticité

```
ln s = a + e × ln p          poids  w_i = n_i × s_i / (1 − s_i)
```

Régression log-log pondérée dès trois paliers de prix. Les poids sont l'inverse de la variance de
`ln s` par la méthode delta.

À deux paliers, seule l'élasticité d'arc (point milieu) est calculable, sans incertitude estimable.

### Règle de Lerner

```
(p* − c) / p* = −1 / e        soit        p* = c × e / (1 + e),   valide pour e < −1
```

GAAP calcule cette valeur, **la borne à l'enveloppe des prix testés** et signale toute extrapolation.

**Précaution supplémentaire propre au périssable.** La règle traite le coût `c` comme une constante.
Ici il dépend du taux d'écoulement, donc du prix. L'optimum théorique est calculé au plancher du
plan, ce qui en fait une indication de direction et non une valeur à appliquer. Sur un produit
inélastique (`|e| < 1`), la règle ne retourne rien du tout, et c'est correct : il n'existe pas
d'optimum intérieur dans ce modèle simplifié, l'optimum réel venant du couplage avec la casse.

---

## 6. Sélection par la qualité

À chaque cellule, comparaison par test de Welch de l'indice de fraîcheur moyen des kilos **vendus**
contre celui du contrôle. Une hausse significative lorsque le prix monte signale que le client est
devenu plus sélectif et prend en priorité les plus beaux articles : le stock résiduel se dégrade
alors plus vite que ne l'explique le seul ralentissement de rotation.

C'est l'analogue structurel de l'anti-sélection en crédit, où une hausse de taux n'est acceptée que
par les demandeurs qui ont le moins d'alternatives. Dans les deux cas, la marge supplémentaire est
partiellement compensée par une dégradation de ce qui reste, et dans les deux cas un test qui ne
regarde que le taux de prise ne la voit pas.

**Limite importante.** L'indice de fraîcheur est relevé à la mise en rayon. Il anticipe la casse, il
ne la constate pas. Toute conclusion sur la dégradation du stock résiduel doit être confirmée sur les
relevés de démarque de fin de période.

---

## 7. Règle de décision

Appliquée dans cet ordre, du plus contraignant au moins contraignant :

| Rang | Condition | Verdict |
|---|---|---|
| 1 | SRM en échec | `INVALIDE`, aucune conclusion recevable |
| 2 | Une cellule dépasse la tolérance de perte | `ARRÊT DE PROTECTION` : couper la cellule, pas l'expérience |
| 3 | Volume minimal non atteint | `VOLUME INSUFFISANT` |
| 4 | Frontière franchie **et** IC sur la contribution strictement positif | `BASCULER` |
| 5 | Information épuisée ou plus aucune variante crédible | `CONSERVER` |
| 6 | Sinon | `POURSUIVRE` |

La condition 4 est **double à dessein**. Le franchissement est une preuve statistique ; l'intervalle
sur la contribution est une preuve économique. GAAP exige les deux.

Toute recommandation porte ses réserves, y compris quand tout va bien.

---

## 8. Ce que GAAP ne mesure pas

- La réaction de la concurrence à un changement de prix généralisé.
- **L'effet de gamme** : une baisse sur les tomates grappe déplace une partie de la demande des
  tomates cerises. Le test mesure un produit, pas un rayon.
- L'effet du prix sur la fréquentation et le panier moyen, au-delà du produit testé.
- La saisonnalité et les effets de nouveauté au-delà de la fenêtre du test.
- **Le couplage prix / quantité commandée.** La quantité mise en rayon est traitée comme donnée.
  L'optimiser conjointement au prix relève du problème du vendeur de journaux à prix endogène
  (Petruzzi & Dada, 1999) et n'est pas modélisé ici. C'est la limite la plus sérieuse du modèle :
  en pratique, un changement de prix durable s'accompagne d'un ajustement des commandes, qui
  modifie à son tour le taux d'écoulement.
- Le comportement des magasins exclus par garde-fou, par construction non observés.
- La démarque réellement constatée : seule la casse attendue entre dans le calcul.

---

## 9. Références

- Working E. J. (1927). What do statistical "demand curves" show? *Quarterly Journal of Economics*,
  41(2), 212-235.
- Berry S., Levinsohn J. & Pakes A. (1995). Automobile prices in market equilibrium.
  *Econometrica*, 63(4), 841-890.
- Bound J., Jaeger D. A. & Baker R. M. (1995). Problems with instrumental variables estimation when
  the correlation between the instruments and the endogenous explanatory variable is weak.
  *Journal of the American Statistical Association*, 90(430), 443-450.
- Angrist J. D. & Pischke J.-S. (2009). *Mostly Harmless Econometrics*. Princeton University Press.
- Kohavi R., Tang D. & Xu Y. (2020). *Trustworthy Online Controlled Experiments*. Cambridge
  University Press.
- Wilson E. B. (1927). Probable inference, the law of succession, and statistical inference.
  *Journal of the American Statistical Association*, 22(158), 209-212.
- Newcombe R. G. (1998). Interval estimation for the difference between independent proportions.
  *Statistics in Medicine*, 17(8), 873-890.
- O'Brien P. C. & Fleming T. R. (1979). A multiple testing procedure for clinical trials.
  *Biometrics*, 35(3), 549-556.
- Lan K. K. G. & DeMets D. L. (1983). Discrete sequential boundaries for clinical trials.
  *Biometrika*, 70(3), 659-663.
- Fleiss J. L., Levin B. & Paik M. C. (2003). *Statistical Methods for Rates and Proportions*,
  3e éd. Wiley.
- Lerner A. P. (1934). The concept of monopoly and the measurement of monopoly power.
  *Review of Economic Studies*, 1(3), 157-175.
- Arrow K. J., Harris T. & Marschak J. (1951). Optimal inventory policy. *Econometrica*, 19(3),
  250-272.
- Petruzzi N. C. & Dada M. (1999). Pricing and the newsvendor problem: a review with extensions.
  *Operations Research*, 47(2), 183-194.

Les valeurs de coût d'achat, de freinte et de valeur de sauvetage utilisées dans un déploiement
doivent provenir des dispositifs achats et contrôle de gestion de l'enseigne, et non de cette
documentation.
