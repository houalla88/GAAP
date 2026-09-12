"""Economie du prix : plancher ajuste du risque et contribution.

C'est le module qui separe GAAP d'un moteur d'A/B testing generaliste. Un
outil visuel compare des taux de conversion. Un test tarifaire dans un
etablissement de credit doit repondre a une question differente et plus dure :

    "Le prix qui convertit le mieux est-il celui qui cree le plus de valeur,
     une fois payes le refinancement, le risque et le capital ?"

La reponse est presque toujours non. Le prix qui maximise le take-up est par
construction le prix le plus bas admissible, et il detruit de la marge des lors
que l'elasticite est superieure a -1 en valeur absolue seulement sur une partie
de la courbe. GAAP impose donc que toute cellule de prix soit evaluee contre un
plancher economique, et que la decision porte sur la contribution, pas sur la
conversion.

Hypotheses et limites : voir docs/METHODOLOGIE.md, section "Modele economique".
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

__all__ = ["CostOfRisk", "PriceFloor", "compute_price_floor", "contribution_per_contract",
           "contribution_per_lead", "raroc", "lerner_optimal_price", "basis_points"]


def basis_points(value: float) -> float:
    """Convertit un taux decimal en points de base (0.0045 -> 45.0)."""
    return value * 10_000.0


@dataclass(frozen=True)
class CostOfRisk:
    """Parametres de cout d'un produit de credit, exprimes en taux annuels.

    Tous les taux sont decimaux et rapportes a l'encours moyen, pas au capital
    initial : c'est la convention qui rend le plancher directement comparable a
    un TAEG.

    Attributes:
        funding_rate: cout de refinancement interne (FTP / taux de cession
            interne). Sortie du dispositif ALM, pas une hypothese libre.
        operating_cost_rate: couts operationnels annualises (acquisition,
            instruction, gestion, recouvrement) rapportes a l'encours moyen.
        pd: probabilite de defaut a 12 mois du segment (modele de score,
            calibre Bale / IFRS 9 selon l'usage).
        lgd: perte en cas de defaut, nette de recouvrement.
        risk_weight: ponderation de risque reglementaire du segment
            (approche standard ou notation interne).
        capital_ratio: ratio de fonds propres cible applique au RWA.
        hurdle_rate: cout des fonds propres exige par l'actionnaire.
    """

    funding_rate: float
    operating_cost_rate: float
    pd: float
    lgd: float
    risk_weight: float = 0.75
    capital_ratio: float = 0.125
    hurdle_rate: float = 0.10

    @property
    def expected_loss_rate(self) -> float:
        """Perte attendue annualisee : EL = PD x LGD (sur encours moyen)."""
        return self.pd * self.lgd

    @property
    def capital_intensity(self) -> float:
        """Fonds propres immobilises par euro d'encours : RW x ratio cible."""
        return self.risk_weight * self.capital_ratio

    @property
    def capital_charge_rate(self) -> float:
        """Surcout annuel du capital par euro d'encours.

        Le capital immobilise ne rapporte pas le taux de refinancement mais
        doit rapporter le hurdle : le cout marginal est donc l'ecart entre les
        deux, applique a l'intensite capitalistique.
        """
        return self.capital_intensity * max(0.0, self.hurdle_rate - self.funding_rate)

    def to_dict(self) -> dict:
        data = asdict(self)
        data.update(
            expected_loss_rate=self.expected_loss_rate,
            capital_intensity=self.capital_intensity,
            capital_charge_rate=self.capital_charge_rate,
        )
        return data


@dataclass(frozen=True)
class PriceFloor:
    """Decomposition du plancher tarifaire, composante par composante.

    La decomposition est conservee et affichee telle quelle : un comite de
    tarification qui voit un plancher a 4,92 % sans sa ventilation ne peut ni
    le challenger ni l'auditer.
    """

    funding: float
    operating: float
    expected_loss: float
    capital: float

    @property
    def total(self) -> float:
        return self.funding + self.operating + self.expected_loss + self.capital

    @property
    def components(self) -> list[tuple[str, float]]:
        return [
            ("Refinancement", self.funding),
            ("Couts operationnels", self.operating),
            ("Perte attendue (PD x LGD)", self.expected_loss),
            ("Charge en capital", self.capital),
        ]

    def to_dict(self) -> dict:
        return {
            "funding": self.funding,
            "operating": self.operating,
            "expected_loss": self.expected_loss,
            "capital": self.capital,
            "total": self.total,
        }


def compute_price_floor(cost: CostOfRisk) -> PriceFloor:
    """Plancher de rentabilite ajuste du risque.

        r_floor = f + o + PD x LGD + k x (h - f)

    Lecture : c'est le taux en dessous duquel un contrat detruit de la valeur
    actionnariale, meme s'il est comptablement profitable. Une cellule de prix
    positionnee sous ce plancher est bloquee par GAAP avant lancement, pas
    constatee apres coup.

    Simplifications assumees : pas d'effet fiscal, pas d'option de
    remboursement anticipe valorisee, hasard de defaut constant sur la duree,
    revenus accessoires (assurance, frais) exclus. Chacune deplace le plancher
    dans un sens connu, documente dans docs/METHODOLOGIE.md.
    """
    return PriceFloor(
        funding=cost.funding_rate,
        operating=cost.operating_cost_rate,
        expected_loss=cost.expected_loss_rate,
        capital=cost.capital_charge_rate,
    )


def contribution_per_contract(
    rate: float, floor_rate: float, principal: float, duration_factor: float
) -> float:
    """Contribution economique d'un contrat signe, en euros.

        C = (r - r_floor) x K x D

    `duration_factor` traduit le profil d'amortissement : c'est l'encours moyen
    exprime en fraction du capital initial, multiplie par la maturite en
    annees. Pour un pret amortissable lineairement sur n annees, D vaut
    approximativement n/2. Ce parametre evite de comparer a tort une marge de
    60 bps sur 12 mois et la meme marge sur 84 mois.
    """
    return (rate - floor_rate) * principal * duration_factor


def contribution_per_lead(
    take_up_rate: float, rate: float, floor_rate: float,
    principal: float, duration_factor: float
) -> float:
    """Contribution attendue par lead expose (metrique de decision de GAAP).

        RAC = take-up x (r - r_floor) x K x D

    C'est la seule metrique sur laquelle GAAP autorise une decision de
    bascule. Elle arbitre explicitement le compromis volume / marge que le
    taux de conversion seul masque.
    """
    return take_up_rate * contribution_per_contract(rate, floor_rate, principal, duration_factor)


def raroc(rate: float, cost: CostOfRisk) -> float:
    """Rendement des fonds propres ajuste du risque.

        RAROC = (r - f x (1 - k) - o - EL) / k

    Le refinancement n'est facture que sur la part de l'encours financee par
    dette : la fraction k couverte par fonds propres ne porte pas d'interet.
    Omettre ce detail - erreur courante - sous-estime le RAROC de f, soit pres
    de 300 bps au niveau actuel des taux, et fait passer pour destructeurs des
    prix qui remunerent correctement le capital.

    Cette formulation est celle qui rend le modele coherent : au prix plancher,
    RAROC vaut exactement le cout des fonds propres. C'est la propriete qui
    donne son sens au plancher, et elle est verifiee par les tests.

    A comparer au hurdle rate. Un RAROC de 9 % sur un hurdle de 11 % signale un
    prix qui couvre ses couts comptables mais ne remunere pas le capital :
    exactement la zone ou une cellule "gagnante" en conversion est perdante en
    valeur.
    """
    if cost.capital_intensity <= 0:
        return float("inf")
    k = cost.capital_intensity
    net = (rate - cost.funding_rate * (1.0 - k) - cost.operating_cost_rate
           - cost.expected_loss_rate)
    return net / k


def lerner_optimal_price(elasticity: float, floor_rate: float) -> float | None:
    """Prix optimal sous demande a elasticite constante (regle de Lerner).

    Pour q(p) = A x p^e, la maximisation de q(p) x (p - c) donne :

        p* = c x e / (1 + e),  valide uniquement pour e < -1

    soit l'indice de Lerner (p* - c) / p* = -1/e.

    Avertissement methodologique appuye : cette formule extrapole une
    elasticite estimee sur quelques points de prix a l'ensemble de la courbe.
    GAAP ne l'utilise jamais seule - le moteur de decision borne toujours la
    recommandation a l'enveloppe convexe des prix reellement testes et signale
    explicitement toute extrapolation. Sortir de cette enveloppe, c'est
    remplacer une mesure par une hypothese.
    """
    if elasticity >= -1.0:
        return None
    return floor_rate * elasticity / (1.0 + elasticity)
