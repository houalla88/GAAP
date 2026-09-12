"""Graphiques : SVG generes cote serveur.

Aucune bibliotheque de visualisation, aucun CDN, aucun script en ligne. Trois
raisons, dans cet ordre :

1. **Securite.** La politique de securite de contenu peut rester stricte
   (`script-src 'self'`, `style-src 'self'`) sans exception. Un tableau de bord
   de tarification qui charge du JavaScript tiers introduit une dependance
   externe dans un outil de decision - c'est un point d'audit evitable.
2. **Reproductibilite.** Le graphique fait partie de la reponse serveur : il
   est identique dans le navigateur, dans un export PDF et dans un test.
3. **Densite.** Un rendu serveur permet de calibrer chaque echelle sur les
   donnees reelles plutot que de subir les choix par defaut d'une librairie.

Les couleurs suivent la charte DataOptimization : palette categorielle dediee
a la data-visualisation, distincte de la palette de marque, et jamais la menthe
vive pour un element porteur d'information. Aucune information n'est portee par
la couleur seule - chaque serie est aussi etiquetee.
"""

from __future__ import annotations

import math
from html import escape

from markupsafe import Markup

__all__ = ["price_ladder", "takeup_chart", "elasticity_chart", "contribution_chart", "progress_bar",
           "sequential_chart", "sparkline", "floor_donut"]

#: Palette categorielle de la charte. Les deux premieres positions sont les
#: couleurs de marque accessibles.
CATEGORICAL = ("#09806c", "#5439b4", "#b06400", "#1b6ca8", "#a03050", "#5a6472")

#: Decomposition du plancher : echelle sequentielle, car les composantes
#: s'empilent en magnitude ordonnee.
FLOOR_COLORS = ("#5fc9b2", "#22a68c", "#09806c", "#065445")

GRID = "#dde1e8"
AXIS_TEXT = "#525a6b"
INK = "#090b10"


def _fmt_pct(value: float, decimals: int = 2) -> str:
    return f"{value * 100:.{decimals}f} %".replace(".", ",")


def _nice_ticks(low: float, high: float, count: int = 5) -> list[float]:
    """Graduations lisibles : pas arrondi a 1, 2, 2.5 ou 5 fois une puissance de 10."""
    if high <= low:
        return [low]
    raw = (high - low) / max(1, count)
    magnitude = 10 ** math.floor(math.log10(raw))
    for factor in (1, 2, 2.5, 5, 10):
        if raw <= factor * magnitude:
            step = factor * magnitude
            break
    else:
        step = 10 * magnitude
    start = math.floor(low / step) * step
    ticks, value = [], start
    while value <= high + step * 0.5:
        ticks.append(round(value, 10))
        value += step
    return ticks


def _svg(width: int, height: int, body: str, label: str) -> Markup:
    return Markup(
        f'<svg class="chart" viewBox="0 0 {width} {height}" width="100%" '
        f'preserveAspectRatio="xMidYMid meet" role="img" aria-label="{escape(label)}">'
        f"{body}</svg>"
    )


def _text(x: float, y: float, content: str, cls: str = "chart-label",
          anchor: str = "middle") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" '
            f'class="{cls}">{escape(content)}</text>')


# ---------------------------------------------------------------------------
# 1. Echelle tarifaire : ou passe l'argent, cellule par cellule
# ---------------------------------------------------------------------------

def price_ladder(results, floor) -> Markup:
    """Colonnes empilees : decomposition du plancher, puis marge au-dessus.

    C'est le graphique central de GAAP. Il repond d'un coup d'oeil a la
    question que pose tout comite de tarification : *que paie ce prix, et que
    reste-t-il ?* Un ecart de 45 bps devient lisible en regard des 602 bps qu'il
    faut couvrir avant de gagner le premier euro.
    """
    width, height = 780, 360
    pad_left, pad_bottom, pad_top = 62, 76, 24
    plot_w = width - pad_left - 24
    plot_h = height - pad_top - pad_bottom

    max_rate = max((r.effective_rate for r in results), default=0.08) * 1.18
    ticks = _nice_ticks(0.0, max_rate, 5)
    scale = lambda v: pad_top + plot_h * (1 - v / max_rate)

    parts = [f'<rect x="0" y="0" width="{width}" height="{height}" class="chart-bg"/>']
    for tick in ticks:
        y = scale(tick)
        parts.append(f'<line x1="{pad_left}" y1="{y:.1f}" x2="{width - 24}" y2="{y:.1f}" '
                     f'stroke="{GRID}" stroke-width="1"/>')
        parts.append(_text(pad_left - 8, y + 4, f"{tick * 100:.0f} %", "chart-axis", "end"))

    components = list(floor.components)
    slot = plot_w / max(1, len(results))
    bar_w = min(72.0, slot * 0.58)

    for index, result in enumerate(results):
        cx = pad_left + slot * (index + 0.5)
        x = cx - bar_w / 2
        cursor = 0.0
        for depth, (_, value) in enumerate(components):
            y0, y1 = scale(cursor + value), scale(cursor)
            parts.append(
                f'<rect x="{x:.1f}" y="{y0:.1f}" width="{bar_w:.1f}" '
                f'height="{max(0.0, y1 - y0):.1f}" fill="{FLOOR_COLORS[depth]}"/>'
            )
            cursor += value
        # Une cellule sous le plancher ne doit pas apparaître comme une colonne
        # a marge nulle : c'est un deficit, et il doit se voir. Le manque est
        # trace en negatif sous la ligne de plancher, avec son libelle.
        gap = result.effective_rate - floor.total
        if gap >= 0:
            y0, y1 = scale(cursor + gap), scale(cursor)
            parts.append(
                f'<rect x="{x:.1f}" y="{y0:.1f}" width="{bar_w:.1f}" '
                f'height="{max(0.0, y1 - y0):.1f}" class="ladder-margin"/>'
            )
            parts.append(_text(cx, y0 - 8, f"+{gap * 10000:.0f} bps", "chart-value"))
        else:
            y0, y1 = scale(cursor), scale(cursor + gap)
            parts.append(
                f'<rect x="{x:.1f}" y="{y0:.1f}" width="{bar_w:.1f}" '
                f'height="{max(0.0, y1 - y0):.1f}" class="ladder-deficit"/>'
            )
            parts.append(_text(cx, y0 - 8, f"deficit {gap * 10000:.0f} bps",
                               "chart-deficit"))
        label = result.cell.label.split("(")[0].strip()
        parts.append(_text(cx, height - 48, label[:18], "chart-label"))
        parts.append(_text(cx, height - 32, _fmt_pct(result.effective_rate), "chart-strong"))
        if result.is_control:
            parts.append(_text(cx, height - 16, "reference", "chart-muted"))

    # Ligne de plancher, annotee : la lecture doit tenir sans legende.
    y_floor = scale(floor.total)
    parts.append(f'<line x1="{pad_left}" y1="{y_floor:.1f}" x2="{width - 24}" y2="{y_floor:.1f}" '
                 f'class="floor-line"/>')
    parts.append(_text(width - 26, y_floor - 7,
                       f"plancher {_fmt_pct(floor.total)}", "chart-strong", "end"))
    return _svg(width, height, "".join(parts), "Decomposition du prix par cellule")


# ---------------------------------------------------------------------------
# 2. Take-up avec intervalles de confiance
# ---------------------------------------------------------------------------

def takeup_chart(results, alpha: float) -> Markup:
    """Take-up par cellule avec intervalle de Wilson.

    Les bornes sont tracees systematiquement : un taux de conversion sans son
    intervalle laisse croire a une precision qui n'existe pas, et c'est la
    premiere facon de conclure a tort sur un test tarifaire.
    """
    width, height = 380, 300
    pad_left, pad_bottom, pad_top = 52, 58, 22
    plot_w = width - pad_left - 20
    plot_h = height - pad_top - pad_bottom

    highs = [r.take_up_ci[1] for r in results] or [0.1]
    max_y = max(highs) * 1.20
    ticks = _nice_ticks(0.0, max_y, 4)
    scale = lambda v: pad_top + plot_h * (1 - v / max_y)

    parts = [f'<rect x="0" y="0" width="{width}" height="{height}" class="chart-bg"/>']
    for tick in ticks:
        y = scale(tick)
        parts.append(f'<line x1="{pad_left}" y1="{y:.1f}" x2="{width - 20}" y2="{y:.1f}" '
                     f'stroke="{GRID}" stroke-width="1"/>')
        parts.append(_text(pad_left - 8, y + 4, f"{tick * 100:.1f}%", "chart-axis", "end"))

    slot = plot_w / max(1, len(results))
    for index, result in enumerate(results):
        cx = pad_left + slot * (index + 0.5)
        colour = CATEGORICAL[index % len(CATEGORICAL)]
        low, high = result.take_up_ci
        parts.append(f'<line x1="{cx:.1f}" y1="{scale(low):.1f}" x2="{cx:.1f}" '
                     f'y2="{scale(high):.1f}" stroke="{colour}" stroke-width="2"/>')
        for bound in (low, high):
            parts.append(f'<line x1="{cx - 7:.1f}" y1="{scale(bound):.1f}" '
                         f'x2="{cx + 7:.1f}" y2="{scale(bound):.1f}" '
                         f'stroke="{colour}" stroke-width="2"/>')
        parts.append(f'<circle cx="{cx:.1f}" cy="{scale(result.take_up):.1f}" r="5.5" '
                     f'fill="{colour}"/>')
        if result.is_control:
            parts.append(f'<circle cx="{cx:.1f}" cy="{scale(result.take_up):.1f}" r="9" '
                         f'fill="none" stroke="{colour}" stroke-width="1.5" '
                         f'stroke-dasharray="3 2"/>')
        parts.append(_text(cx, scale(high) - 10, f"{result.take_up * 100:.2f}%", "chart-value"))
        parts.append(_text(cx, height - 32, _fmt_pct(result.effective_rate, 2), "chart-label"))
        parts.append(_text(cx, height - 18,
                           "controle" if result.is_control else f"{result.delta_bp:+.0f} bps",
                           "chart-muted"))
    parts.append(_text(pad_left - 40, 14, f"IC {(1 - alpha) * 100:.1f} %", "chart-muted", "start"))
    return _svg(width, height, "".join(parts), "Taux de take-up par cellule de prix")


# ---------------------------------------------------------------------------
# 3. Courbe d'elasticite
# ---------------------------------------------------------------------------

def elasticity_chart(results, elasticity) -> Markup:
    """Nuage log-log et droite d'ajustement.

    L'echelle logarithmique n'est pas un effet de style : sous l'hypothese
    d'elasticite constante, la relation est lineaire dans cet espace. Une
    courbure visible sur ce graphique *refute* l'hypothese, et c'est
    precisement ce qu'on veut pouvoir voir avant de tarifer dessus.
    """
    width, height = 380, 300
    pad_left, pad_bottom, pad_top = 52, 58, 22
    plot_w = width - pad_left - 20
    plot_h = height - pad_top - pad_bottom

    usable = [r for r in results if r.take_up > 0 and r.exposed > 0]
    if len(usable) < 2 or elasticity is None:
        return _svg(width, height,
                    _text(width / 2, height / 2, "Donnees insuffisantes", "chart-muted"),
                    "Elasticite indisponible")

    xs = [math.log(r.effective_rate) for r in usable]
    ys = [math.log(r.take_up) for r in usable]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    x_pad = (x_max - x_min) * 0.22 or 0.02
    y_pad = (y_max - y_min) * 0.28 or 0.06
    x_min, x_max = x_min - x_pad, x_max + x_pad
    y_min, y_max = y_min - y_pad, y_max + y_pad

    sx = lambda v: pad_left + plot_w * (v - x_min) / (x_max - x_min)
    sy = lambda v: pad_top + plot_h * (1 - (v - y_min) / (y_max - y_min))

    parts = [f'<rect x="0" y="0" width="{width}" height="{height}" class="chart-bg"/>']
    for value in _nice_ticks(y_min, y_max, 4):
        y = sy(value)
        if pad_top - 2 <= y <= pad_top + plot_h + 2:
            parts.append(f'<line x1="{pad_left}" y1="{y:.1f}" x2="{width - 20}" y2="{y:.1f}" '
                         f'stroke="{GRID}" stroke-width="1"/>')
            parts.append(_text(pad_left - 8, y + 4, f"{math.exp(value) * 100:.1f}%",
                               "chart-axis", "end"))

    # Ajustement pondere et bande d'incertitude a +/- 1 erreur-type sur la pente.
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    intercept = mean_y - elasticity.value * mean_x
    if elasticity.std_error > 0:
        band = []
        upper = []
        steps = 24
        for i in range(steps + 1):
            xv = x_min + (x_max - x_min) * i / steps
            centre = intercept + elasticity.value * xv
            spread = abs(elasticity.std_error * (xv - mean_x))
            band.append(f"{sx(xv):.1f},{sy(centre + spread):.1f}")
            upper.append(f"{sx(xv):.1f},{sy(centre - spread):.1f}")
        parts.append(f'<polygon points="{" ".join(band + list(reversed(upper)))}" '
                     f'class="uncertainty-band"/>')
    parts.append(
        f'<line x1="{sx(x_min):.1f}" y1="{sy(intercept + elasticity.value * x_min):.1f}" '
        f'x2="{sx(x_max):.1f}" y2="{sy(intercept + elasticity.value * x_max):.1f}" '
        f'class="fit-line"/>'
    )

    for index, result in enumerate(usable):
        colour = CATEGORICAL[index % len(CATEGORICAL)]
        x, y = sx(math.log(result.effective_rate)), sy(math.log(result.take_up))
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="{colour}"/>')
        parts.append(_text(x, y - 12, _fmt_pct(result.effective_rate, 2), "chart-value"))

    for value in _nice_ticks(x_min, x_max, 4):
        x = sx(value)
        if pad_left - 2 <= x <= pad_left + plot_w + 2:
            parts.append(_text(x, height - 34, f"{math.exp(value) * 100:.2f}%", "chart-axis"))
    parts.append(_text(width / 2, height - 14,
                       "prix effectif (echelle logarithmique)", "chart-muted"))
    parts.append(_text(pad_left, 14,
                       f"e = {elasticity.value:.2f}" +
                       (f"  R2 = {elasticity.r_squared:.2f}" if elasticity.points > 2 else ""),
                       "chart-strong", "start"))
    return _svg(width, height, "".join(parts), "Courbe d'elasticite prix de la demande")


# ---------------------------------------------------------------------------
# 4. Contribution ajustee du risque
# ---------------------------------------------------------------------------

def contribution_chart(results) -> Markup:
    """Contribution par lead expose, cellule par cellule.

    La metrique de decision de GAAP. Le trait de reference est le prix courant :
    tout ce qui depasse est un gain potentiel, tout ce qui reste dessous est une
    destruction de valeur, quel que soit le taux de conversion.
    """
    width, height = 380, 300
    pad_left, pad_bottom, pad_top = 60, 58, 26
    plot_w = width - pad_left - 20
    plot_h = height - pad_top - pad_bottom

    values = [r.rac_per_lead for r in results] or [0.0]
    max_y = max(values) * 1.25 or 1.0
    control = next((r for r in results if r.is_control), None)
    ticks = _nice_ticks(0.0, max_y, 4)
    scale = lambda v: pad_top + plot_h * (1 - v / max_y)

    parts = [f'<rect x="0" y="0" width="{width}" height="{height}" class="chart-bg"/>']
    for tick in ticks:
        y = scale(tick)
        parts.append(f'<line x1="{pad_left}" y1="{y:.1f}" x2="{width - 20}" y2="{y:.1f}" '
                     f'stroke="{GRID}" stroke-width="1"/>')
        parts.append(_text(pad_left - 8, y + 4, f"{tick:.0f} EUR", "chart-axis", "end"))

    slot = plot_w / max(1, len(results))
    bar_w = min(46.0, slot * 0.56)
    for index, result in enumerate(results):
        cx = pad_left + slot * (index + 0.5)
        colour = CATEGORICAL[index % len(CATEGORICAL)]
        y = scale(result.rac_per_lead)
        parts.append(f'<rect x="{cx - bar_w / 2:.1f}" y="{y:.1f}" width="{bar_w:.1f}" '
                     f'height="{max(0.0, pad_top + plot_h - y):.1f}" fill="{colour}"/>')
        parts.append(_text(cx, y - 8, f"{result.rac_per_lead:.2f}", "chart-value"))
        parts.append(_text(cx, height - 32,
                           "controle" if result.is_control else f"{result.delta_bp:+.0f} bps",
                           "chart-label"))
        if result.rac_test:
            parts.append(_text(cx, height - 18, f"{result.rac_test.difference:+.2f}",
                               "chart-muted"))
    if control:
        y = scale(control.rac_per_lead)
        parts.append(f'<line x1="{pad_left}" y1="{y:.1f}" x2="{width - 20}" y2="{y:.1f}" '
                     f'class="reference-line"/>')
    parts.append(_text(pad_left, 15, "EUR de contribution par lead expose", "chart-muted", "start"))
    return _svg(width, height, "".join(parts), "Contribution ajustee du risque par cellule")


# ---------------------------------------------------------------------------
# 5. Suivi sequentiel
# ---------------------------------------------------------------------------

def sequential_chart(series, boundary_fn, label: str = "") -> Markup:
    """Statistique de decision contre frontiere d'arret, au fil de l'information.

    Tracer la frontiere *avant* la courbe n'est pas un detail de mise en page :
    c'est la representation de la regle d'arret fixee avant le test. Tant que la
    courbe reste sous la frontiere, il n'y a rien a decider - et le graphique le
    montre sans qu'il faille le dire.
    """
    width, height = 780, 260
    pad_left, pad_bottom, pad_top = 52, 52, 24
    plot_w = width - pad_left - 110
    plot_h = height - pad_top - pad_bottom

    max_y = max([4.5] + [abs(v) for _, v in series] + [boundary_fn(0.18)])
    max_y = min(max_y, 12.0) * 1.08
    sx = lambda t: pad_left + plot_w * min(1.0, max(0.0, t))
    sy = lambda v: pad_top + plot_h * (1 - min(1.0, abs(v) / max_y))

    parts = [f'<rect x="0" y="0" width="{width}" height="{height}" class="chart-bg"/>']
    for tick in _nice_ticks(0, max_y, 4):
        y = sy(tick)
        parts.append(f'<line x1="{pad_left}" y1="{y:.1f}" x2="{pad_left + plot_w}" '
                     f'y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>')
        parts.append(_text(pad_left - 8, y + 4, f"{tick:.0f}", "chart-axis", "end"))

    boundary_points = []
    for i in range(6, 101):
        t = i / 100.0
        boundary_points.append(f"{sx(t):.1f},{sy(boundary_fn(t)):.1f}")
    parts.append(f'<polyline points="{" ".join(boundary_points)}" class="boundary-line"/>')
    parts.append(_text(pad_left + plot_w + 8, sy(boundary_fn(1.0)) + 4,
                       "frontiere d'arret", "chart-muted", "start"))

    if series:
        points = " ".join(f"{sx(t):.1f},{sy(v):.1f}" for t, v in series)
        parts.append(f'<polyline points="{points}" class="series-line"/>')
        last_t, last_v = series[-1]
        parts.append(f'<circle cx="{sx(last_t):.1f}" cy="{sy(last_v):.1f}" r="5" '
                     f'fill="{CATEGORICAL[0]}"/>')
        parts.append(_text(pad_left + plot_w + 8, sy(last_v) + 4,
                           f"|t| = {abs(last_v):.2f}", "chart-strong", "start"))

    for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
        parts.append(_text(sx(fraction), height - 28, f"{fraction * 100:.0f} %", "chart-axis"))
    parts.append(_text(pad_left + plot_w / 2, height - 10,
                       "information accumulee", "chart-muted"))
    if label:
        parts.append(_text(pad_left, 15, label, "chart-strong", "start"))
    return _svg(width, height, "".join(parts), "Suivi sequentiel de la statistique de decision")


# ---------------------------------------------------------------------------
# 6. Elements compacts
# ---------------------------------------------------------------------------

def sparkline(values: list[float], width: int = 120, height: int = 28) -> Markup:
    """Micro-courbe pour les listes. Sans axe : une forme, pas une mesure."""
    if len(values) < 2:
        return Markup('<svg class="spark" viewBox="0 0 120 28" width="120" height="28"></svg>')
    low, high = min(values), max(values)
    span = (high - low) or 1.0
    step = width / (len(values) - 1)
    points = " ".join(
        f"{i * step:.1f},{height - 3 - (v - low) / span * (height - 6):.1f}"
        for i, v in enumerate(values)
    )
    return Markup(
        f'<svg class="spark" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'role="img" aria-label="tendance"><polyline points="{points}" '
        f'class="spark-line"/></svg>'
    )


def floor_donut(floor) -> Markup:
    """Repartition du plancher en anneau. Complement du libelle, jamais son substitut."""
    size, radius, stroke = 132, 52, 18
    circumference = 2 * math.pi * radius
    parts = [f'<circle cx="{size/2}" cy="{size/2}" r="{radius}" fill="none" '
             f'stroke="{GRID}" stroke-width="{stroke}"/>']
    offset = 0.0
    total = floor.total or 1.0
    for index, (_, value) in enumerate(floor.components):
        length = circumference * value / total
        parts.append(
            f'<circle cx="{size/2}" cy="{size/2}" r="{radius}" fill="none" '
            f'stroke="{FLOOR_COLORS[index]}" stroke-width="{stroke}" '
            f'stroke-dasharray="{length:.2f} {circumference - length:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}" transform="rotate(-90 {size/2} {size/2})"/>'
        )
        offset += length
    parts.append(_text(size / 2, size / 2 + 2, f"{floor.total * 100:.2f}", "donut-value"))
    parts.append(_text(size / 2, size / 2 + 18, "% plancher", "chart-muted"))
    return Markup(
        f'<svg class="donut" viewBox="0 0 {size} {size}" width="{size}" height="{size}" '
        f'role="img" aria-label="Repartition du plancher de rentabilite">{"".join(parts)}</svg>'
    )


def progress_bar(fraction: float, label: str = "", width: int = 240,
                 height: int = 10) -> Markup:
    """Jauge de progression en SVG.

    Rendue en SVG et non par un attribut de style en ligne, pour que la
    politique de securite de contenu puisse interdire `style-src 'unsafe-inline'`
    sans exception. Une contrainte de securite qui oblige a une exception n'en
    est pas une.
    """
    fraction = min(1.0, max(0.0, fraction))
    filled = width * fraction
    return Markup(
        f'<svg class="progress" viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        f'preserveAspectRatio="none" role="img" aria-label="{escape(label or "progression")}">'
        f'<rect x="0" y="0" width="{width}" height="{height}" rx="{height/2}" '
        f'class="progress-track"/>'
        f'<rect x="0" y="0" width="{filled:.1f}" height="{height}" rx="{height/2}" '
        f'class="progress-fill"/></svg>'
    )
