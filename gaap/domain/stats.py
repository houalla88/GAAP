"""Primitives statistiques de GAAP.

Ce module est volontairement ecrit en Python pur (stdlib `math` uniquement).
Trois raisons, toutes liees a l'usage bancaire du moteur :

1. **Auditabilite** : un controle interne ou un regulateur doit pouvoir relire
   la formule appliquee sans traverser une pile numerique compilee.
2. **Reproductibilite** : aucune dependance a une version de BLAS/LAPACK, donc
   aucun risque de divergence de resultat entre l'environnement de recette et
   la production.
3. **Portabilite** : le moteur de decision doit pouvoir tourner dans un
   conteneur minimal, au plus pres du service de tarification.

Toutes les fonctions sont pures et deterministes. Les references sont citees
au niveau de chaque fonction ; elles sont regroupees dans docs/METHODOLOGIE.md.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

__all__ = [
    "norm_pdf",
    "norm_cdf",
    "norm_ppf",
    "chi2_sf",
    "student_t_sf",
    "wilson_interval",
    "newcombe_difference_interval",
    "two_proportion_ztest",
    "welch_ttest",
    "chi_square_goodness_of_fit",
    "required_sample_size_per_arm",
    "detectable_effect",
    "obrien_fleming_bound",
    "bonferroni",
    "prob_b_beats_a",
    "expected_loss_choosing_b",
    "contribution_posterior",
    "ProportionTest",
    "MeanTest",
]

def _seed_from(*values: float) -> int:
    """Graine deterministe derivee des donnees d'entree.

    Derivation explicite par empreinte plutot que par `hash()` : le hachage
    natif de Python est sale par processus pour les chaînes, et rien ne
    garantit sa stabilite entre versions pour les autres types. Une estimation
    de Monte-Carlo qui changerait d'une execution a l'autre ruinerait la
    rejouabilite d'une decision de tarification en controle.
    """
    material = "|".join(repr(value) for value in values).encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


_SQRT_2 = math.sqrt(2.0)
_SQRT_2PI = math.sqrt(2.0 * math.pi)
_EPS = 1e-12


# ---------------------------------------------------------------------------
# Loi normale
# ---------------------------------------------------------------------------

def norm_pdf(x: float) -> float:
    """Densite de la loi normale centree reduite."""
    return math.exp(-0.5 * x * x) / _SQRT_2PI


def norm_cdf(x: float) -> float:
    """Fonction de repartition normale, via `math.erf` (precision ~1e-16)."""
    return 0.5 * (1.0 + math.erf(x / _SQRT_2))


def norm_ppf(p: float) -> float:
    """Quantile normal (fonction inverse de `norm_cdf`).

    Approximation rationnelle de Acklam, raffinee par une iteration de Halley.
    Erreur relative < 1e-15 sur (0, 1), ce qui depasse tout besoin metier.
    """
    if not 0.0 < p < 1.0:
        raise ValueError("norm_ppf attend une probabilite dans ]0, 1[")

    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00)

    p_low, p_high = 0.02425, 1.0 - 0.02425
    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    elif p <= p_high:
        q = p - 0.5
        r = q * q
        x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
            (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)

    # Raffinement de Halley : elimine l'erreur residuelle de l'approximation.
    err = norm_cdf(x) - p
    u = err * _SQRT_2PI * math.exp(x * x / 2.0)
    return x - u / (1.0 + x * u / 2.0)


# ---------------------------------------------------------------------------
# Fonctions gamma / beta incompletes -> lois du chi2 et de Student
# ---------------------------------------------------------------------------

def _lower_gamma_series(a: float, x: float) -> float:
    """P(a, x) par developpement en serie. Converge vite pour x < a + 1."""
    ap, total, term = a, 1.0 / a, 1.0 / a
    for _ in range(1000):
        ap += 1.0
        term *= x / ap
        total += term
        if abs(term) < abs(total) * 1e-16:
            break
    return total * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _upper_gamma_cf(a: float, x: float) -> float:
    """Q(a, x) par fraction continue (Lentz). Converge vite pour x >= a + 1."""
    tiny = 1e-300
    b, c, d = x + 1.0 - a, 1.0 / tiny, 1.0 / (x + 1.0 - a)
    h = d
    for i in range(1, 1000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-16:
            break
    return h * math.exp(-x + a * math.log(x) - math.lgamma(a))


def chi2_sf(x: float, df: int) -> float:
    """Probabilite de survie P(X > x) pour X ~ chi2(df)."""
    if df <= 0:
        raise ValueError("df doit etre strictement positif")
    if x <= 0.0:
        return 1.0
    a, y = df / 2.0, x / 2.0
    if y < a + 1.0:
        return max(0.0, min(1.0, 1.0 - _lower_gamma_series(a, y)))
    return max(0.0, min(1.0, _upper_gamma_cf(a, y)))


def _betacf(a: float, b: float, x: float) -> float:
    """Fraction continue de la beta incomplete (algorithme de Lentz)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-15:
            break
    return h


def _betainc(a: float, b: float, x: float) -> float:
    """Beta incomplete regularisee I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log1p(-x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + b * math.log1p(-x) + a * math.log(x)
    ) * _betacf(b, a, 1.0 - x) / b


def student_t_sf(t: float, df: float) -> float:
    """Probabilite de survie P(T > t) pour T ~ Student(df)."""
    if df <= 0:
        raise ValueError("df doit etre strictement positif")
    p = 0.5 * _betainc(df / 2.0, 0.5, df / (df + t * t))
    return p if t > 0 else 1.0 - p


# ---------------------------------------------------------------------------
# Intervalles de confiance sur une proportion
# ---------------------------------------------------------------------------

def wilson_interval(successes: int, trials: int, alpha: float = 0.05) -> tuple[float, float]:
    """Intervalle de score de Wilson (1927).

    Prefere a l'intervalle de Wald : il reste dans [0, 1] et conserve sa
    couverture nominale au voisinage des bornes. C'est exactement le regime
    d'un rayon de frais : l'ecoulement observe se situe entre 70 et 95 %, ou
    l'intervalle de Wald deborde au-dela de 1 et sous-couvre.
    """
    if trials <= 0:
        return (0.0, 1.0)
    if not 0 <= successes <= trials:
        # Precondition violee : plus de succes que d'essais. En production c'est
        # impossible, la base comptant les deux. Le signaler clairement vaut
        # mieux que de bricher sur une racine negative, et mieux que de brider
        # silencieusement une donnee incoherente.
        raise ValueError(
            f"wilson_interval : {successes} succes pour {trials} essais, "
            "la donnee est incoherente."
        )
    z = norm_ppf(1.0 - alpha / 2.0)
    p = successes / trials
    denom = 1.0 + z * z / trials
    centre = (p + z * z / (2.0 * trials)) / denom
    half = z * math.sqrt(p * (1.0 - p) / trials + z * z / (4.0 * trials * trials)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def newcombe_difference_interval(
    successes_a: int, trials_a: int, successes_b: int, trials_b: int, alpha: float = 0.05
) -> tuple[float, float]:
    """IC sur p_b - p_a par la methode hybride de Newcombe (1998, methode 10).

    Construite a partir des bornes de Wilson de chaque bras. Retenue ici parce
    que sa couverture reste correcte quand un bras est petit ou quand le taux
    est faible - les deux situations sont la norme sur une cellule de prix
    volontairement peu exposee.
    """
    if trials_a <= 0 or trials_b <= 0:
        return (-1.0, 1.0)
    la, ua = wilson_interval(successes_a, trials_a, alpha)
    lb, ub = wilson_interval(successes_b, trials_b, alpha)
    pa, pb = successes_a / trials_a, successes_b / trials_b
    diff = pb - pa
    lower = diff - math.sqrt((pb - lb) ** 2 + (ua - pa) ** 2)
    upper = diff + math.sqrt((ub - pb) ** 2 + (pa - la) ** 2)
    return (max(-1.0, lower), min(1.0, upper))


# ---------------------------------------------------------------------------
# Tests d'hypothese
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProportionTest:
    """Resultat d'une comparaison de deux taux d'ecoulement."""

    rate_control: float
    rate_variant: float
    absolute_lift: float
    relative_lift: float
    ci_low: float
    ci_high: float
    z: float
    p_value: float
    significant: bool

    @property
    def ci_excludes_zero(self) -> bool:
        return self.ci_low > 0.0 or self.ci_high < 0.0


def two_proportion_ztest(
    successes_control: int,
    trials_control: int,
    successes_variant: int,
    trials_variant: int,
    alpha: float = 0.05,
) -> ProportionTest:
    """Test z bilateral sur deux proportions independantes (variance poolee).

    L'IC retourne est celui de Newcombe, pas l'IC de Wald associe au test : le
    test tranche l'hypothese nulle, l'intervalle sert a lire l'amplitude de
    l'effet. Les deux peuvent marginalement diverger au voisinage du seuil ;
    c'est assume et documente plutot que masque.
    """
    if trials_control <= 0 or trials_variant <= 0:
        return ProportionTest(0.0, 0.0, 0.0, 0.0, -1.0, 1.0, 0.0, 1.0, False)

    p_c = successes_control / trials_control
    p_v = successes_variant / trials_variant
    p_pool = (successes_control + successes_variant) / (trials_control + trials_variant)
    se = math.sqrt(p_pool * (1.0 - p_pool) * (1.0 / trials_control + 1.0 / trials_variant))
    z = (p_v - p_c) / se if se > _EPS else 0.0
    p_value = 2.0 * (1.0 - norm_cdf(abs(z)))
    ci_low, ci_high = newcombe_difference_interval(
        successes_control, trials_control, successes_variant, trials_variant, alpha
    )
    return ProportionTest(
        rate_control=p_c,
        rate_variant=p_v,
        absolute_lift=p_v - p_c,
        relative_lift=(p_v - p_c) / p_c if p_c > _EPS else 0.0,
        ci_low=ci_low,
        ci_high=ci_high,
        z=z,
        p_value=p_value,
        significant=p_value < alpha,
    )


@dataclass(frozen=True)
class MeanTest:
    """Resultat d'une comparaison de deux moyennes (metrique continue)."""

    mean_control: float
    mean_variant: float
    difference: float
    ci_low: float
    ci_high: float
    t: float
    df: float
    p_value: float
    significant: bool


def welch_ttest(
    mean_control: float, var_control: float, n_control: int,
    mean_variant: float, var_variant: float, n_variant: int,
    alpha: float = 0.05,
) -> MeanTest:
    """Test t de Welch (variances inegales).

    C'est le test adapte a la marge par kilo : la variance de la contribution
    depend du prix de la cellule, donc l'hypothese d'homoscedasticite du test
    de Student classique est fausse par construction dans un test tarifaire.
    """
    if n_control < 2 or n_variant < 2:
        return MeanTest(mean_control, mean_variant, mean_variant - mean_control,
                        0.0, 0.0, 0.0, 0.0, 1.0, False)
    se_c2 = var_control / n_control
    se_v2 = var_variant / n_variant
    se = math.sqrt(se_c2 + se_v2)
    if se < _EPS:
        return MeanTest(mean_control, mean_variant, mean_variant - mean_control,
                        0.0, 0.0, 0.0, 0.0, 1.0, False)
    diff = mean_variant - mean_control
    t = diff / se
    num = (se_c2 + se_v2) ** 2
    den = se_c2 ** 2 / (n_control - 1) + se_v2 ** 2 / (n_variant - 1)
    df = num / den if den > _EPS else float(n_control + n_variant - 2)
    p_value = 2.0 * student_t_sf(abs(t), df)
    # Quantile de Student approxime par la normale au-dela de 100 ddl.
    crit = norm_ppf(1.0 - alpha / 2.0) if df > 100 else _student_ppf(1.0 - alpha / 2.0, df)
    return MeanTest(
        mean_control=mean_control,
        mean_variant=mean_variant,
        difference=diff,
        ci_low=diff - crit * se,
        ci_high=diff + crit * se,
        t=t,
        df=df,
        p_value=p_value,
        significant=p_value < alpha,
    )


def _student_ppf(p: float, df: float) -> float:
    """Quantile de Student par bissection sur la fonction de survie."""
    lo, hi = -200.0, 200.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if 1.0 - student_t_sf(mid, df) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def chi_square_goodness_of_fit(
    observed: list[int], expected_weights: list[float]
) -> tuple[float, int, float]:
    """Test du chi2 d'adequation. Retourne (statistique, ddl, p-value).

    Usage principal dans GAAP : le controle SRM (Sample Ratio Mismatch). Un
    ecart entre l'allocation theorique et l'allocation observee invalide le
    test, quelle que soit la beaute du resultat : il signale une fuite dans le
    routage, un filtre applique en aval ou une exclusion asymetrique.
    """
    total = sum(observed)
    weight_sum = sum(expected_weights)
    if total == 0 or weight_sum <= 0 or len(observed) != len(expected_weights):
        return (0.0, 0, 1.0)
    stat = 0.0
    for obs, weight in zip(observed, expected_weights):
        exp = total * weight / weight_sum
        if exp <= 0:
            continue
        stat += (obs - exp) ** 2 / exp
    df = len(observed) - 1
    return (stat, df, chi2_sf(stat, df) if df > 0 else 1.0)


# ---------------------------------------------------------------------------
# Dimensionnement d'experience
# ---------------------------------------------------------------------------

def bonferroni(alpha: float, comparisons: int) -> float:
    """Correction de Bonferroni pour comparaisons multiples au controle.

    Un plan a k cellules de prix produit k-1 comparaisons. Sans correction, le
    risque de premiere espece familial derive vers 1 - (1 - alpha)^(k-1), soit
    14 % pour trois variantes a alpha = 5 %. Conservateur mais defendable
    devant un comite de tarification.
    """
    return alpha / max(1, comparisons)


def required_sample_size_per_arm(
    baseline_rate: float, relative_mde: float, alpha: float = 0.05, power: float = 0.80
) -> int:
    """Taille d'echantillon par bras pour detecter un effet relatif donne.

    Formule classique a deux proportions (Fleiss et al.), sans correction de
    continuite. Retourne un entier par bras, a multiplier par le nombre de
    cellules pour obtenir le volume total a router.
    """
    if not 0.0 < baseline_rate < 1.0 or relative_mde == 0.0:
        return 0
    p1 = baseline_rate
    p2 = max(_EPS, min(1.0 - _EPS, baseline_rate * (1.0 + relative_mde)))
    p_bar = (p1 + p2) / 2.0
    z_alpha = norm_ppf(1.0 - alpha / 2.0)
    z_beta = norm_ppf(power)
    num = (z_alpha * math.sqrt(2.0 * p_bar * (1.0 - p_bar))
           + z_beta * math.sqrt(p1 * (1.0 - p1) + p2 * (1.0 - p2))) ** 2
    return int(math.ceil(num / (p2 - p1) ** 2))


def detectable_effect(
    baseline_rate: float, n_per_arm: int, alpha: float = 0.05, power: float = 0.80
) -> float:
    """Effet relatif minimal detectable (MDE) pour un volume donne par bras.

    Approximation normale a variances egales : suffisante pour cadrer un plan
    d'experience, pas pour conclure. Retourne un ratio (0.05 = 5 % relatif).
    """
    if n_per_arm <= 0 or not 0.0 < baseline_rate < 1.0:
        return float("inf")
    z_alpha = norm_ppf(1.0 - alpha / 2.0)
    z_beta = norm_ppf(power)
    absolute = (z_alpha + z_beta) * math.sqrt(2.0 * baseline_rate * (1.0 - baseline_rate) / n_per_arm)
    return absolute / baseline_rate


def obrien_fleming_bound(information_fraction: float, alpha: float = 0.05) -> float:
    """Frontiere d'arret sequentielle de type O'Brien-Fleming.

    Approximation de Lan-DeMets : z*(t) = z_(alpha/2) / sqrt(t), ou t est la
    fraction d'information accumulee. Tres conservatrice au debut du test,
    elle converge vers le seuil nominal a la fin.

    Interet metier direct : un test tarifaire est regarde tous les jours par
    des gens qui ont un interet a l'arreter tot. Cette frontiere donne une
    regle d'arret ecrite avant le lancement, opposable, qui protege contre le
    "peeking" - premiere cause de faux positifs en experimentation en ligne.
    """
    t = max(1e-6, min(1.0, information_fraction))
    return norm_ppf(1.0 - alpha / 2.0) / math.sqrt(t)


# ---------------------------------------------------------------------------
# Lecture bayesienne
# ---------------------------------------------------------------------------

def prob_b_beats_a(
    successes_a: int, trials_a: int, successes_b: int, trials_b: int
) -> float:
    """P(p_b > p_a) sous posteriors Beta et prior uniforme Beta(1, 1).

    Forme fermee de Cook (2005). Le prior uniforme rend les parametres entiers,
    donc la somme exacte. Au-dela de 50 000 termes, bascule sur une
    approximation normale des posteriors - l'ecart est alors negligeable devant
    l'incertitude de modele.

    Cette lecture complete le test frequentiste sans le remplacer : elle repond
    a "quelle est ma probabilite de me tromper en basculant le prix ?", qui est
    la question reellement posee en comite.
    """
    a_a, b_a = successes_a + 1, trials_a - successes_a + 1
    a_b, b_b = successes_b + 1, trials_b - successes_b + 1
    if a_b > 50_000:
        mean_a = a_a / (a_a + b_a)
        mean_b = a_b / (a_b + b_b)
        var_a = mean_a * (1 - mean_a) / (a_a + b_a + 1)
        var_b = mean_b * (1 - mean_b) / (a_b + b_b + 1)
        return norm_cdf((mean_b - mean_a) / math.sqrt(var_a + var_b + _EPS))

    def log_beta(x: float, y: float) -> float:
        return math.lgamma(x) + math.lgamma(y) - math.lgamma(x + y)

    total = 0.0
    base = log_beta(a_a, b_a)
    for i in range(a_b):
        total += math.exp(
            log_beta(a_a + i, b_a + b_b) - math.log(b_b + i) - log_beta(1 + i, b_b) - base
        )
    return max(0.0, min(1.0, total))


def expected_loss_choosing_b(
    successes_a: int, trials_a: int, successes_b: int, trials_b: int, draws: int = 20_000
) -> float:
    """Perte attendue (en points d'ecoulement) si l'on bascule sur B.

    E[max(p_a - p_b, 0)] estimee par Monte-Carlo sur les posteriors Beta. La
    graine est derivee deterministiquement des comptages : deux executions sur
    les memes donnees produisent le meme chiffre, condition necessaire pour
    qu'une decision de tarification soit rejouable en controle.

    Regle d'arret associee (Chris Stucchio, VWO) : basculer quand la perte
    attendue passe sous un seuil de tolerance fixe avant le test.
    """
    import random

    rng = random.Random(_seed_from(successes_a, trials_a, successes_b, trials_b))
    a_a, b_a = successes_a + 1, trials_a - successes_a + 1
    a_b, b_b = successes_b + 1, trials_b - successes_b + 1
    total = 0.0
    for _ in range(draws):
        pa = rng.betavariate(a_a, b_a)
        pb = rng.betavariate(a_b, b_b)
        if pa > pb:
            total += pa - pb
    return total / draws


@dataclass(frozen=True)
class ContributionPosterior:
    """Lecture bayesienne de la metrique de decision.

    Attributes:
        probability: P(contribution_variante > contribution_controle).
        expected_loss: perte attendue en euros par kilo presente si l'on bascule
            a tort, soit E[max(C_controle - C_variante, 0)].
    """

    probability: float
    expected_loss: float


def contribution_posterior(
    successes_a: int, trials_a: int, contribution_a: float,
    successes_b: int, trials_b: int, contribution_b: float,
    draws: int = 20_000,
) -> ContributionPosterior:
    """Posterior sur la contribution, pas sur le seul ecoulement.

    C'est la correction d'une erreur courante et couteuse : la probabilite
    bayesienne habituelle repond a "la variante ecoule-t-elle mieux ?", alors
    que la decision porte sur "la variante rapporte-t-elle plus ?". Sur un test
    tarifaire, les deux reponses sont regulierement opposees - une cellule plus
    chere ecoule moins et rapporte davantage.

    La contribution par kilo presente est s x V + K, ou V et K sont des constantes
    connues une fois le prix fixe (valeur d'une vente, et perte sur un invendu). On echantillonne donc les posteriors Beta des taux et on compare
    les produits. La graine est derivee des comptages : deux executions sur les
    memes donnees produisent le meme chiffre, condition necessaire pour qu'une
    decision de tarification soit rejouable en controle.

    La perte attendue est exprimee en euros par kilo presente, directement
    comparable a la tolerance de perte fixee dans le plan.
    """
    import random

    rng = random.Random(_seed_from(
        successes_a, trials_a, successes_b, trials_b,
        round(contribution_a, 6), round(contribution_b, 6),
    ))
    a_a, b_a = successes_a + 1, max(1, trials_a - successes_a + 1)
    a_b, b_b = successes_b + 1, max(1, trials_b - successes_b + 1)

    wins, loss_total = 0, 0.0
    for _ in range(draws):
        rac_a = rng.betavariate(a_a, b_a) * contribution_a
        rac_b = rng.betavariate(a_b, b_b) * contribution_b
        if rac_b > rac_a:
            wins += 1
        else:
            loss_total += rac_a - rac_b
    return ContributionPosterior(wins / draws, loss_total / draws)
