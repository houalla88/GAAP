"""Filtres de presentation.

Les conventions typographiques francophones sont appliquees ici et nulle part
ailleurs : virgule decimale, espace insecable avant le symbole de pourcentage,
separateur de milliers par espace fine. Regrouper ces regles dans un seul
module evite qu'une moitie de l'application affiche 6.90% et l'autre 6,90 %.
"""

from __future__ import annotations

from datetime import datetime

from flask import Flask

from . import charts

__all__ = ["register"]

_NBSP = " "


def _fr(value: str) -> str:
    return value.replace(",", _NBSP).replace(".", ",")


def pct(value: float | None, decimals: int = 2) -> str:
    """Taux decimal en pourcentage francophone : 0.069 -> 6,90 %."""
    if value is None:
        return "-"
    return f"{value * 100:.{decimals}f}".replace(".", ",") + _NBSP + "%"


def pp(value: float | None, decimals: int = 2) -> str:
    """Ecart en points de pourcentage, signe."""
    if value is None:
        return "-"
    return f"{value * 100:+.{decimals}f}".replace(".", ",") + _NBSP + "pt"


def bp(value: float | None, decimals: int = 0) -> str:
    """Points de base, signes."""
    if value is None:
        return "-"
    return f"{value:+.{decimals}f}".replace(".", ",") + _NBSP + "bps"


def eur(value: float | None, decimals: int = 0) -> str:
    if value is None:
        return "-"
    return _fr(f"{value:,.{decimals}f}") + _NBSP + "EUR"


def eur_signed(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "-"
    return _fr(f"{value:+,.{decimals}f}") + _NBSP + "EUR"


def num(value: float | int | None, decimals: int = 0) -> str:
    if value is None:
        return "-"
    return _fr(f"{value:,.{decimals}f}")


def dec(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "-"
    return f"{value:.{decimals}f}".replace(".", ",")


def pvalue(value: float | None) -> str:
    """p-value lisible. En dessous de 1e-4, notation scientifique.

    Ne jamais afficher "p = 0,0000" : ce n'est pas zero, et laisser croire le
    contraire est la porte ouverte a une surinterpretation.
    """
    if value is None:
        return "-"
    if value < 1e-4:
        return f"< 10^-4 ({value:.1e})"
    return f"{value:.4f}".replace(".", ",")


def when(value: str | None) -> str:
    if not value:
        return "-"
    try:
        return datetime.fromisoformat(value).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return value


def day(value: str | None) -> str:
    if not value:
        return "-"
    try:
        return datetime.fromisoformat(value).strftime("%d/%m/%Y")
    except ValueError:
        return value


def register(app: Flask) -> None:
    app.jinja_env.filters.update(
        pct=pct, pp=pp, bp=bp, eur=eur, eur_signed=eur_signed,
        num=num, dec=dec, pvalue=pvalue, when=when, day=day,
    )
    app.jinja_env.globals.update(progress_bar=charts.progress_bar)
