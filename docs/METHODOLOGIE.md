# Note de méthode

Document de référence de GAAP : formules appliquées, hypothèses retenues, limites assumées.
Les docstrings du code renvoient à ce fichier. Une version condensée est servie par l'application
elle-même sur `/methode`, parce qu'une méthode qu'il faut aller chercher ailleurs n'est pas
opposable.

---

## 1. Modèle économique

### 1.1 Plancher de rentabilité

```
r_plancher = f + o + PD × LGD + k × (h − f)          k = RW × ratio CET1
```

| Terme | Signification | Source dans un dispositif réel |
|---|---|---|
| `f` | Coût de refinancement | Taux de cession interne, sortie du dispositif ALM |
| `o` | Coûts opérationnels annualisés, rapportés à l'encours moyen | Comptabilité analytique |
| `PD × LGD` | Perte attendue annualisée | Modèle de score, calibrage Bâle / IFRS 9 |
| `k` | Fonds propres immobilisés par euro d'encours | Pondération réglementaire × ratio CET1 cible |
| `h` | Coût des fonds propres | Exigence actionnariale, cohérente avec le RAROC cible |

Le capital immobilisé ne rapporte pas `f` mais doit rapporter `h` : son coût marginal est l'écart
entre les deux, appliqué à l'intensité capitalistique. D'où le terme `k × (h − f)` et non `k × h`.

**Simplifications assumées.** Elles sont listées ici plutôt que dissimulées, avec le sens de leur
effet :

| Simplification | Effet sur le plancher réel |
|---|---|
| Pas d'effet fiscal (déductibilité des intérêts) | Le plancher calculé est **supérieur** au plancher réel |
| Option de remboursement anticipé non valorisée | Plancher **sous-estimé** (l'option est vendue au client) |
| Hasard de défaut constant sur la durée | Biais de signe indéterminé, faible sur des maturités courtes |
| Revenus accessoires exclus (assurance, frais annexes) | Plancher **surestimé** |

Le solde net est conservateur sur le poste qui compte le plus, le risque, ce qui est le sens dans
lequel une approximation de tarification bancaire doit se tromper.

### 1.2 RAROC

```
RAROC = (r − f × (1 − k) − o − PD × LGD) / k
```

Le refinancement n'est facturé que sur la part d'encours financée par dette : la fraction `k`
couverte par fonds propres ne porte pas d'intérêt. Omettre ce détail, erreur courante, sous-estime
le RAROC de `f`, soit près de 300 bps au niveau actuel des taux, et fait passer pour destructeurs
des prix qui rémunèrent correctement le capital.

**Propriété de cohérence, vérifiée par la suite de tests :** au prix plancher, `RAROC = h`. C'est
elle qui donne son sens au plancher, et c'est elle qui a révélé l'erreur ci-dessus.

### 1.3 Contribution ajustée du risque

```
Contribution par contrat :  C   = (r_effectif − r_plancher) × K × D
Contribution par lead     :  RAC = take-up × C
```

`K` est le capital moyen, `D` le facteur de durée, soit l'encours moyen rapporté au capital initial,
multiplié par la maturité en années. Pour un prêt amortissable linéairement sur `n` années, `D ≈ n/2`.

Ce paramètre évite de comparer à tort une marge de 60 bps sur 12 mois et la même marge sur 84 mois.

### 1.4 Mise en équivalence des leviers de prix

```
r_effectif = r + frais / (K × D)
```

Les frais de dossier deviennent comparables à un taux. Sans cette mise en équivalence, un test qui
déplace 150 EUR de frais et un test qui déplace 40 bps de taux seraient illisibles l'un à côté de
l'autre, alors qu'ils touchent la même poche du client.

---

## 2. Affectation

```
u = uint64( SHA-256( sel ‖ espace ‖ identifiant )[0:8] ) / 2⁶⁴
```

SHA-256 est retenu pour son uniformité et sa stabilité inter-langages : une réimplémentation Java
côté moteur de tarification produit exactement les mêmes affectations.

Deux espaces de nommage indépendants, `holdout` et `cell`. Les mélanger corrélerait le groupe
témoin au prix : biais discret, invisible dans les totaux, et fatal à l'interprétation.

Ordre des contrôles, du plus contraignant au moins contraignant :

1. Expérience active ?
2. Segment exclu ?
3. Dans le périmètre ciblé ?
4. Groupe témoin préservé ?
5. Tirage de cellule.

Cet ordre garantit qu'un segment protégé ne peut jamais être exposé à un prix de test, même par
accident de configuration des poids.

---

## 3. Inférence

### 3.1 Intervalles

- **Une proportion** : score de Wilson (1927). Reste dans [0, 1] et conserve sa couverture nominale
  aux faibles taux, le régime usuel d'un take-up de crédit (2 à 15 %).
- **Différence de deux proportions** : méthode hybride de Newcombe (1998, méthode 10), construite
  sur les bornes de Wilson de chaque bras.

Le test `z` sur deux proportions et l'intervalle de Newcombe peuvent marginalement diverger au
voisinage du seuil. C'est assumé et documenté plutôt que masqué : le test tranche l'hypothèse nulle,
l'intervalle sert à lire l'amplitude de l'effet.

### 3.2 Métrique continue

Test `t` de Welch. La variance de la contribution par lead dépend du prix de la cellule :
l'homoscédasticité du test de Student classique est fausse par construction dans un test tarifaire.

La contribution par lead étant une Bernoulli multipliée par une constante connue, sa variance vaut
exactement `c² × p × (1 − p)`. Les variances sont donc calculées sans jamais charger une observation
unitaire, ce qui rend l'analyse `O(nombre de cellules)` et non `O(nombre de leads)`.

### 3.3 Comparaisons multiples

Correction de Bonferroni sur le nombre de comparaisons au contrôle. Sans correction, le risque de
première espèce familial dérive vers `1 − (1 − α)^(k−1)`, soit 14 % pour trois variantes à α = 5 %.
Conservateur, mais défendable devant un comité de tarification.

### 3.4 Intégrité de l'allocation (SRM)

χ² d'adéquation entre allocation observée et poids déclarés, seuil sévère à **p < 0,001**
(convention Kohavi). Un échec invalide la lecture, quelle que soit l'apparence des chiffres.

Causes réelles d'un SRM, par ordre de fréquence : filtre appliqué en aval du routage, exclusion
asymétrique, perte de trafic sur une cellule, déduplication différenciée. Jamais le tirage aléatoire
lui-même, ce qui est vérifiable en simulant l'allocation sur des identifiants synthétiques
(`allocation_profile`).

### 3.5 Arrêt séquentiel

Frontière de type O'Brien-Fleming, approximation de Lan-DeMets :

```
z*(t) = z_{α/2} / √t
```

où `t` est la fraction d'information accumulée. Très conservatrice au début, elle converge vers le
seuil nominal à la fin. C'est l'approximation usuelle sous mouvement brownien, exacte pour des
analyses régulièrement espacées.

**La frontière porte sur la contribution, pas sur le taux de conversion.** Protéger du *peeking* la
statistique sur laquelle on ne décide pas n'aurait aucun sens.

### 3.6 Lecture bayésienne

Posteriors Beta à prior uniforme `Beta(1, 1)`, sur la **contribution** :

```
P( p_B × c_B  >  p_A × c_A )
```

estimée par Monte-Carlo à graine dérivée déterministiquement des comptages : deux exécutions sur les
mêmes données donnent le même chiffre, condition nécessaire pour qu'une décision de tarification
soit rejouable en contrôle.

La perte attendue `E[max(RAC_A − RAC_B, 0)]` est exprimée en **euros par lead exposé**, directement
comparable à la tolérance de perte fixée dans le plan.

La probabilité bayésienne usuelle, qui porte sur le taux de conversion, répondrait à « la variante
convertit-elle mieux ? » alors que la décision porte sur « la variante rapporte-t-elle plus ? ». Sur
un test tarifaire, les deux réponses sont régulièrement opposées.

### 3.7 Dimensionnement

```
n_par_bras = ( z_{1−α/2} √(2 p̄ q̄) + z_{1−β} √(p₁q₁ + p₂q₂) )² / (p₁ − p₂)²
```

Formule classique à deux proportions (Fleiss, Levin & Paik), sans correction de continuité.

Ordre de grandeur à retenir : détecter **8 % relatif** sur un take-up de 6 %, avec quatre cellules
et α corrigé, demande environ **52 000 leads par cellule**. C'est ce chiffre qui détermine ce qu'un
test tarifaire peut honnêtement prétendre mesurer.

---

## 4. Élasticité

```
ln q = a + e × ln p          poids  w_i = n_i × p_i / (1 − p_i)
```

Régression log-log pondérée dès trois paliers de prix. Les poids sont l'inverse de la variance de
`ln p` par la méthode delta : une cellule peu exposée ou à faible take-up pèse moins, ce qui est
exactement le comportement souhaité, puisque c'est la cellule dont la mesure est la plus bruitée.

À deux paliers, seule l'élasticité d'arc (formule du point milieu) est calculable, sans incertitude
estimable. Utilisable pour cadrer, pas pour décider.

L'échelle logarithmique n'est pas un effet de style : sous hypothèse d'élasticité constante, la
relation est linéaire dans cet espace. Une courbure visible **réfute** l'hypothèse, et c'est
précisément ce qu'on veut pouvoir voir avant de tarifer dessus.

### Règle de Lerner

```
(p* − c) / p* = −1 / e        soit        p* = c × e / (1 + e),   valide pour e < −1
```

GAAP calcule cette valeur, **la borne à l'enveloppe des prix testés** et signale toute
extrapolation. Sortir de l'enveloppe, c'est remplacer une mesure par une hypothèse de forme
fonctionnelle. La recommandation devient alors une hypothèse de modèle et le moteur de décision
refuse de s'en servir seul.

---

## 5. Anti-sélection

À chaque cellule, comparaison par test de Welch de la PD moyenne des dossiers **acceptés** contre
celle du contrôle. Une hausse significative lorsque le prix monte signale que la marge
supplémentaire est partiellement compensée par une dégradation du mélange de risque.

Mécanisme : quand le prix monte, ce sont relativement plus les demandeurs à PD élevée, ceux qui ont
le moins d'alternatives, qui acceptent. C'est le phénomène que la mesure du seul taux de conversion
ne voit pas, et qui fait qu'une hausse de prix rapporte moins qu'annoncé.

**Limite importante.** La PD utilisée est celle d'octroi, produite par le modèle de score. Elle
anticipe la perte, elle ne la constate pas. Toute conclusion sur le mélange de risque doit être
confirmée sur les cohortes à douze mois avant généralisation.

---

## 6. Règle de décision

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
sur la contribution est une preuve économique. GAAP exige les deux, parce que l'histoire des tests
tarifaires est pleine de gagnants statistiques qui perdaient de l'argent.

Toute recommandation porte ses réserves, y compris quand tout va bien : une recommandation tarifaire
livrée sans ses limites d'interprétation est une recommandation incomplète.

---

## 7. Ce que GAAP ne mesure pas

- La réaction de la concurrence à un changement de prix généralisé.
- L'effet du prix sur la valeur client à long terme (multi-détention, attrition, refinancement).
- La saisonnalité et les effets de nouveauté au-delà de la fenêtre du test.
- Le comportement des clients exclus par garde-fou, par construction non observés.
- La perte réellement constatée : seule la perte attendue à l'octroi entre dans le calcul.
- Les effets de report entre produits (un client qui renonce au prêt personnel et prend un crédit
  auto n'est pas suivi).

---

## 8. Références

- Kohavi R., Tang D. & Xu Y. (2020). *Trustworthy Online Controlled Experiments*. Cambridge
  University Press.
- Wilson E. B. (1927). Probable inference, the law of succession, and statistical inference.
  *Journal of the American Statistical Association*, 22(158), 209-212.
- Newcombe R. G. (1998). Interval estimation for the difference between independent proportions:
  comparison of eleven methods. *Statistics in Medicine*, 17(8), 873-890.
- O'Brien P. C. & Fleming T. R. (1979). A multiple testing procedure for clinical trials.
  *Biometrics*, 35(3), 549-556.
- Lan K. K. G. & DeMets D. L. (1983). Discrete sequential boundaries for clinical trials.
  *Biometrika*, 70(3), 659-663.
- Fleiss J. L., Levin B. & Paik M. C. (2003). *Statistical Methods for Rates and Proportions*, 3e éd.
  Wiley.
- Lerner A. P. (1934). The concept of monopoly and the measurement of monopoly power.
  *Review of Economic Studies*, 1(3), 157-175.
- Comité de Bâle sur le contrôle bancaire (2017). *Bâle III : finalisation des réformes
  post-crise*. BRI.
- IASB. *IFRS 9, Instruments financiers*, section sur les pertes de crédit attendues.

Les valeurs de coût du risque, de pondération et de coût des fonds propres utilisées dans un
déploiement doivent provenir des dispositifs ALM et de modélisation de l'établissement, et non de
cette documentation.
