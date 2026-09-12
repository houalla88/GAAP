"""Economie du prix : plancher ajuste de la casse et contribution.

C'est le module qui separe GAAP d'un moteur d'A/B testing generaliste. Un outil
visuel compare des taux de conversion. Un test tarifaire sur un produit
perissable doit repondre a une question differente et plus dure :

    "Le prix qui ecoule le mieux est-il celui qui cree le plus de marge, une
     fois payes l'achat, la logistique, la casse et l'immobilisation du stock ?"

La reponse est rarement oui. Le prix qui maximise l'ecoulement est par
construction le prix le plus bas admissible, et il ne cree de la valeur que si
la demande est assez elastique pour que le volume compense la marge cedee.
GAAP impose donc que toute cellule de prix soit evaluee contre un plancher
economique, et que la decision porte sur la contribution, pas sur l'ecoulement.

**Particularite du perissable, et tout l'interet du domaine : le plancher
depend du prix.** Baisser le prix accelere la rotation, donc reduit la casse,
donc abaisse le cout complet par kilo vendu. Le relever fait l'inverse. Le
plancher n'est donc pas une constante posee une fois pour toutes mais une
fonction du taux d'ecoulement, que l'experience mesure cellule par cellule.

Hypotheses et limites : voir docs/METHODOLOGIE.md, section "Modele economique".
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

__all__ = ["CostStack", "PriceFloor", "compute_price_floor", "margin_per_unit_sold",
           "contribution_per_unit_presented", "return_on_working_capital",
           "lerner_optimal_price", "cents"]


def cents(value: float) -> float:
    """Convertit un montant en euros en centimes (0.045 -> 4.5)."""
    return value * 100.0


@dataclass(frozen=True)
class CostStack:
    """Structure de cout d'un produit frais, exprimee par kilo mis en rayon.

    Tous les montants sont en euros par kilo, sauf mention contraire. La
    convention est explicite parce qu'un melange d'unites entre le kilo achete,
    le kilo vendable et le kilo vendu est la premiere source d'erreur de marge
    en produits frais.

    Attributes:
        purchase_cost: prix d'achat au cadran ou au grossiste, par kilo livre.
        logistics_cost: transport, chaîne du froid et passage plateforme.
        handling_cost: reception, parage, mise en rayon, reassort.
        known_shrink: freinte connue en fraction du poids livre (parage,
            calibrage, deshydratation). Un kilo livre ne donne que
            (1 - known_shrink) kilo vendable.
        salvage_value: valeur de recuperation d'un kilo invendu (don defiscalise,
            transformation, alimentation animale). Zero si destruction.
        expected_sell_through: taux d'ecoulement de reference du plan, declare
            avant le test. C'est l'equivalent fonctionnel d'une probabilite de
            defaut : une hypothese sortie de l'historique, que l'experience
            viendra confirmer ou infirmer.
        capital_cost: cout d'immobilisation du stock, par kilo vendu.
    """

    purchase_cost: float
    logistics_cost: float
    handling_cost: float
    known_shrink: float = 0.06
    salvage_value: float = 0.0
    expected_sell_through: float = 0.82
    capital_cost: float = 0.01

    @property
    def acquisition_cost(self) -> float:
        """Cout d'acquisition par kilo **vendable**, freinte connue incluse.

        Diviser par (1 - freinte) plutot que soustraire : si 6 % du poids livre
        part au parage, il faut acheter 1 / 0,94 kilo pour en presenter un.
        """
        sellable = max(1e-6, 1.0 - self.known_shrink)
        return (self.purchase_cost + self.logistics_cost + self.handling_cost) / sellable

    @property
    def waste_odds(self) -> float:
        """Kilos invendus par kilo vendu, soit (1 - s) / s.

        Analogue fonctionnel du rapport de cotes du defaut. A 80 % d'ecoulement,
        chaque kilo vendu traîne 0,25 kilo d'invendu a financer.
        """
        # Seule la borne basse protege la division. Brider aussi le haut
        # laisserait une casse residuelle a 100 % d'ecoulement, ou elle doit
        # valoir exactement zero.
        rate = min(1.0, max(1e-6, self.expected_sell_through))
        return (1.0 - rate) / rate

    @property
    def expected_waste_loss(self) -> float:
        """Perte attendue sur invendus, par kilo vendu.

        Strictement l'equivalent de PD x LGD en credit : une probabilite
        d'echec multipliee par la perte encourue en cas d'echec. Ici la
        probabilite d'echec est (1 - taux d'ecoulement) et la perte est le cout
        d'acquisition diminue de la valeur de sauvetage.
        """
        return self.waste_odds * max(0.0, self.acquisition_cost - self.salvage_value)

    def to_dict(self) -> dict:
        data = asdict(self)
        data.update(
            acquisition_cost=self.acquisition_cost,
            waste_odds=self.waste_odds,
            expected_waste_loss=self.expected_waste_loss,
        )
        return data


@dataclass(frozen=True)
class PriceFloor:
    """Decomposition du plancher tarifaire, poste par poste.

    La decomposition est conservee et affichee telle quelle : un responsable de
    rayon qui voit un plancher a 2,41 EUR le kilo sans sa ventilation ne peut ni
    le challenger ni l'auditer.
    """

    purchase: float
    logistics: float
    handling: float
    waste: float
    capital: float

    @property
    def total(self) -> float:
        return self.purchase + self.logistics + self.handling + self.waste + self.capital

    @property
    def components(self) -> list[tuple[str, float]]:
        return [
            ("Achat", self.purchase),
            ("Logistique et froid", self.logistics),
            ("Manutention et mise en rayon", self.handling),
            ("Perte attendue sur invendus", self.waste),
            ("Immobilisation du stock", self.capital),
        ]

    def to_dict(self) -> dict:
        return {
            "purchase": self.purchase,
            "logistics": self.logistics,
            "handling": self.handling,
            "waste": self.waste,
            "capital": self.capital,
            "total": self.total,
        }


def compute_price_floor(cost: CostStack, sell_through: float | None = None) -> PriceFloor:
    """Plancher de rentabilite par kilo vendu.

        p_plancher = a / s - v x (1 - s) / s + c

    ou `a` est le cout d'acquisition par kilo vendable, `s` le taux
    d'ecoulement, `v` la valeur de sauvetage d'un invendu et `c` le cout
    d'immobilisation. La forme additive affichee separe les trois postes
    d'acquisition, la perte attendue sur invendus et le capital, ce qui la rend
    lisible en colonne empilee.

    `sell_through` permet de recalculer le plancher au taux **observe** d'une
    cellule plutot qu'au taux declare dans le plan. C'est la difference entre le
    plancher suppose avant le test et le plancher reel constate pendant, et
    l'ecart entre les deux est une information a part entiere : il dit de
    combien la rotation a bouge avec le prix.

    Lecture : c'est le prix en dessous duquel un kilo vendu detruit de la valeur,
    meme s'il degage une marge brute positive. Une cellule positionnee sous ce
    plancher est bloquee par GAAP avant lancement, pas constatee apres coup.

    Simplifications assumees : pas d'effet de gamme (la baisse de prix d'un
    produit deplace la demande des produits voisins), pas de valorisation de la
    fidelisation induite par un prix d'appel, freinte connue supposee
    independante du prix. Chacune deplace le plancher dans un sens documente
    dans docs/METHODOLOGIE.md.
    """
    effective = cost if sell_through is None else CostStack(
        purchase_cost=cost.purchase_cost,
        logistics_cost=cost.logistics_cost,
        handling_cost=cost.handling_cost,
        known_shrink=cost.known_shrink,
        salvage_value=cost.salvage_value,
        expected_sell_through=sell_through,
        capital_cost=cost.capital_cost,
    )
    sellable = max(1e-6, 1.0 - cost.known_shrink)
    return PriceFloor(
        purchase=cost.purchase_cost / sellable,
        logistics=cost.logistics_cost / sellable,
        handling=cost.handling_cost / sellable,
        waste=effective.expected_waste_loss,
        capital=cost.capital_cost,
    )


def margin_per_unit_sold(price: float, floor_rate: float) -> float:
    """Marge economique d'un kilo vendu, en euros.

    Difference nue entre le prix et le plancher. Positive, elle remunere le
    risque de casse pris en presentant la marchandise ; negative, elle le
    detruit.
    """
    return price - floor_rate


def contribution_per_unit_presented(
    sell_through: float, price: float, floor_rate: float
) -> float:
    """Contribution attendue par kilo **mis en rayon** (metrique de decision).

        C = taux d'ecoulement x (prix - plancher)

    C'est la seule metrique sur laquelle GAAP autorise une decision de bascule.
    Elle arbitre explicitement le compromis volume / marge que le taux
    d'ecoulement seul masque : un prix bas ecoule tout et ne gagne rien, un prix
    haut degage de la marge sur les kilos vendus et en jette une partie.

    L'unite est l'euro par kilo presente, et non par kilo vendu : c'est le kilo
    presente qui est engage, et c'est donc lui qui doit porter le rendement.
    """
    return sell_through * margin_per_unit_sold(price, floor_rate)


def return_on_working_capital(price: float, cost: CostStack,
                              sell_through: float | None = None) -> float:
    """Rendement du capital circulant immobilise dans le stock.

        r = (prix - plancher + immobilisation) / immobilisation

    A comparer au cout du capital de l'enseigne. Un produit qui degage une marge
    positive mais immobilise beaucoup de tresorerie pour une rotation lente peut
    rester destructeur de valeur au niveau du rayon.

    Propriete de coherence, verifiee par les tests : au prix plancher, le
    rendement vaut exactement 1, c'est-a-dire que le capital immobilise est
    rembourse sans remuneration.
    """
    if cost.capital_cost <= 0:
        return float("inf")
    floor = compute_price_floor(cost, sell_through).total
    return (price - floor + cost.capital_cost) / cost.capital_cost


def lerner_optimal_price(elasticity: float, floor_rate: float) -> float | None:
    """Prix optimal sous demande a elasticite constante (regle de Lerner).

    Pour q(p) = A x p^e, la maximisation de q(p) x (p - c) donne :

        p* = c x e / (1 + e),  valide uniquement pour e < -1

    soit l'indice de Lerner (p* - c) / p* = -1/e.

    Avertissement methodologique appuye : cette formule extrapole une elasticite
    estimee sur quelques points de prix a l'ensemble de la courbe, et elle
    traite le cout `c` comme une constante alors qu'en perissable il depend
    lui-meme du taux d'ecoulement, donc du prix. GAAP ne l'utilise jamais seule :
    le moteur de decision borne toujours la recommandation a l'enveloppe convexe
    des prix reellement testes et signale explicitement toute extrapolation.
    Sortir de cette enveloppe, c'est remplacer une mesure par une hypothese.
    """
    if elasticity >= -1.0:
        return None
    return floor_rate * elasticity / (1.0 + elasticity)
