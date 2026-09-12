"""Configuration de l'application.

Aucun secret n'est ecrit dans le code. En l'absence de `GAAP_SECRET_KEY`,
l'application demarre avec une cle ephemere et le signale : les sessions sont
alors invalidees a chaque redemarrage, ce qui est le comportement souhaitable
en developpement et un defaut bruyant - donc visible - en production.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

__all__ = ["Config", "DevelopmentConfig", "TestingConfig", "ProductionConfig", "resolve"]

_ROOT = Path(__file__).resolve().parent.parent


class Config:
    """Valeurs communes a tous les environnements."""

    SECRET_KEY = os.environ.get("GAAP_SECRET_KEY") or secrets.token_hex(32)
    EPHEMERAL_SECRET = "GAAP_SECRET_KEY" not in os.environ
    DATABASE = os.environ.get("GAAP_DATABASE", str(_ROOT / "instance" / "gaap.sqlite"))

    #: Acteur par defaut des actions non authentifiees. En integration reelle,
    #: il est remplace par l'identite du referentiel d'habilitations : la piste
    #: d'audit n'a de valeur que si l'acteur est nomme.
    DEFAULT_ACTOR = os.environ.get("GAAP_ACTOR", "demo@dataoptimization.be")

    #: Politique de securite de contenu. Stricte par defaut : aucune ressource
    #: externe, aucun script ni style en ligne. Les graphiques sont des SVG
    #: generes cote serveur, precisement pour rendre cette politique tenable.
    CONTENT_SECURITY_POLICY = (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
        "connect-src 'self'; font-src 'self'; object-src 'none'; frame-ancestors 'none'; "
        "base-uri 'none'; form-action 'self'"
    )

    JSON_SORT_KEYS = False


class DevelopmentConfig(Config):
    DEBUG = True


class TestingConfig(Config):
    TESTING = True
    DATABASE = ":memory:"
    SECRET_KEY = "test-only-not-a-secret"
    EPHEMERAL_SECRET = False


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"


_PROFILES = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def resolve(name: str | None = None) -> type[Config]:
    return _PROFILES.get(name or os.environ.get("GAAP_ENV", "development"), DevelopmentConfig)
