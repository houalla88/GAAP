"""Moteur d'analyse : hierarchie des metriques, elasticite, selection qualite."""

import pytest

from gaap.domain.analysis import CellAggregate, analyse


def _aggregats(plan, taux: dict[str, float], volume: int = 12_000,
               qualite: dict[str, float] | None = None):
    """Fabrique des agregats coherents a partir de taux d'ecoulement cibles."""
    qualite = qualite or {}
    out = []
    for cell in plan.cells:
        presente = volume * 2 if cell.is_control else volume
        vendu = int(round(presente * taux[cell.key]))
        q = qualite.get(cell.key, 0.70)
        out.append(CellAggregate(
            cell_key=cell.key, presented=presente, sold=vendu,
            quality_sum_presented=presente * 0.70,
            quality_sq_sum_presented=presente * (0.70 ** 2 + 0.02),
            quality_sum_sold=vendu * q,
            quality_sq_sum_sold=vendu * (q ** 2 + 0.02),
        ))
    return out


def _isoelastique(plan, elasticite: float, base: float = 0.82) -> dict[str, float]:
    """Taux d'ecoulement iso-elastiques, bornes a 99 %.

    Un taux superieur a 100 % n'a pas de sens physique : on ne peut pas vendre
    plus de kilos qu'on n'en presente.
    """
    reference = plan.control.effective_price
    return {c.key: min(0.99, base * (c.effective_price / reference) ** elasticite)
            for c in plan.cells}


class TestHierarchieDesMetriques:
    def test_le_meilleur_ecoulement_n_est_pas_le_meilleur_prix(self, plan):
        """Le cas qui justifie l'existence de GAAP : un outil d'A/B testing
        generaliste designerait ici la cellule la moins chere, et un objectif de
        reduction du gaspillage la designerait aussi."""
        analysis = analyse(plan, _aggregats(plan, _isoelastique(plan, -0.7)))
        assert analysis.best_by_sell_through.cell.key == "m20"
        assert analysis.best_by_contribution.cell.key == "p40"
        assert analysis.metric_conflict
        # La cellule la plus rentable est aussi celle qui casse le plus.
        assert analysis.best_by_contribution.waste_rate > analysis.best_by_sell_through.waste_rate

    def test_pas_de_conflit_en_demande_elastique(self, plan):
        """A |e| nettement superieur a 1, baisser le prix gagne sur les deux
        tableaux. Le conflit n'est pas un artefact du modele."""
        analysis = analyse(plan, _aggregats(plan, _isoelastique(plan, -2.5)))
        assert not analysis.metric_conflict

    def test_contribution_suit_la_definition(self, plan):
        analysis = analyse(plan, _aggregats(plan, {c.key: 0.80 for c in plan.cells}))
        control = analysis.control_result
        cost = plan.cost
        attendu = (0.80 * (plan.control.effective_price - cost.salvage_value - cost.capital_cost)
                   + cost.salvage_value - cost.acquisition_cost)
        assert control.contribution_per_unit == pytest.approx(attendu, rel=1e-6)

    def test_plancher_recalcule_a_la_rotation_observee(self, plan):
        """Une cellule qui tourne lentement casse davantage et supporte donc un
        plancher plus haut que celui du plan."""
        analysis = analyse(plan, _aggregats(plan, _isoelastique(plan, -0.7)))
        lente = next(r for r in analysis.results if r.cell.key == "p40")
        rapide = next(r for r in analysis.results if r.cell.key == "m20")
        assert lente.floor_observed > analysis.floor_planned > rapide.floor_observed

    def test_cout_d_apprentissage_negatif_quand_le_test_rapporte(self, plan):
        analysis = analyse(plan, _aggregats(plan, _isoelastique(plan, -0.7)))
        assert analysis.learning_cost < 0

    def test_cout_d_apprentissage_positif_quand_le_test_coute(self, plan):
        analysis = analyse(plan, _aggregats(plan, _isoelastique(plan, -2.5)))
        assert analysis.learning_cost > 0


class TestIntegrite:
    def test_srm_conforme_sur_une_allocation_respectee(self, plan):
        analysis = analyse(plan, _aggregats(plan, {c.key: 0.80 for c in plan.cells}))
        assert analysis.srm.passed

    def test_srm_detecte_une_cellule_amputee(self, plan):
        aggregats = _aggregats(plan, {c.key: 0.80 for c in plan.cells})
        ampute = [
            CellAggregate(a.cell_key, int(a.presented * 0.8), int(a.sold * 0.8),
                          a.quality_sum_presented, a.quality_sq_sum_presented,
                          a.quality_sum_sold, a.quality_sq_sum_sold)
            if a.cell_key == "p20" else a
            for a in aggregats
        ]
        analysis = analyse(plan, ampute)
        assert not analysis.srm.passed
        assert analysis.warnings and "SRM" in analysis.warnings[0]


class TestElasticite:
    def test_la_pente_vraie_est_retrouvee(self, plan):
        """Taux construits sur une elasticite exacte de -0,7 : l'estimation doit
        la retrouver a la precision de l'echantillonnage pres."""
        analysis = analyse(plan, _aggregats(plan, _isoelastique(plan, -0.7), volume=60_000))
        assert analysis.elasticity is not None
        assert analysis.elasticity.value == pytest.approx(-0.7, abs=0.02)
        assert analysis.elasticity.r_squared > 0.99
        assert analysis.elasticity.ci_low < -0.7 < analysis.elasticity.ci_high

    def test_pas_d_optimum_de_lerner_en_demande_inelastique(self, plan):
        """|e| < 1 : aucun optimum interieur n'existe, et le moteur ne doit pas
        en inventer un."""
        analysis = analyse(plan, _aggregats(plan, _isoelastique(plan, -0.7)))
        assert analysis.elasticity.optimal_price is None
        assert not analysis.elasticity.is_elastic

    def test_extrapolation_signalee_hors_enveloppe(self, plan):
        analysis = analyse(plan, _aggregats(plan, _isoelastique(plan, -3.0, base=0.60)))
        elasticity = analysis.elasticity
        assert elasticity.optimal_price is not None
        basse, haute = elasticity.tested_range
        assert elasticity.optimal_is_extrapolated == (not basse <= elasticity.optimal_price <= haute)

    def test_deux_cellules_donnent_une_elasticite_d_arc_sans_incertitude(self, plan):
        duo = plan.with_status(plan.status, cells=plan.cells[:2])
        analysis = analyse(duo, _aggregats(duo, {"ctl": 0.82, "m20": 0.86}))
        assert analysis.elasticity.points == 2
        assert analysis.elasticity.std_error == 0.0
        assert "arc" in analysis.elasticity.method.lower()


class TestSelectionParLaQualite:
    def test_derive_de_fraîcheur_detectee(self, plan):
        """Signal propre au perissable : quand le prix monte, le client devient
        plus exigeant et le stock residuel se degrade."""
        analysis = analyse(plan, _aggregats(
            plan, _isoelastique(plan, -0.7),
            qualite={"ctl": 0.700, "m20": 0.694, "p20": 0.722, "p40": 0.741},
        ))
        assert analysis.quality_selection_alert
        derives = [r for r in analysis.results if r.quality_selection]
        assert {r.cell.key for r in derives} >= {"p40"}
        assert all(r.quality_drift > 0 for r in derives)

    def test_pas_d_alerte_quand_la_fraîcheur_est_stable(self, plan):
        analysis = analyse(plan, _aggregats(plan, _isoelastique(plan, -0.7)))
        assert not analysis.quality_selection_alert


class TestSequentiel:
    def test_la_frontiere_se_detend_avec_l_information(self, plan):
        petit = analyse(plan, _aggregats(plan, {c.key: 0.80 for c in plan.cells}, volume=500))
        grand = analyse(plan, _aggregats(plan, {c.key: 0.80 for c in plan.cells}, volume=20_000))
        assert petit.information_fraction < grand.information_fraction
        assert petit.boundary > grand.boundary

    def test_alpha_est_corrige_du_nombre_de_comparaisons(self, plan):
        analysis = analyse(plan, _aggregats(plan, {c.key: 0.80 for c in plan.cells}))
        assert analysis.alpha_adjusted == pytest.approx(plan.alpha / 3)
