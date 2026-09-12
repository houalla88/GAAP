"""GAAP - Governed A/B Assignment for Pricing.

Moteur d'experimentation tarifaire gouvernee. L'acronyme est un clin d'oeil
assume aux *Generally Accepted Accounting Principles* : GAAP applique au prix
la meme exigence que la comptabilite applique aux comptes - des regles fixees
avant les faits, une piste d'audit, et une opinion motivee plutot qu'un chiffre
nu.

Assemblage de l'application selon le patron de fabrique : la configuration est
injectee, jamais lue globalement, ce qui permet aux tests de monter une
instance isolee sans toucher a l'environnement.
"""

from __future__ import annotations

import logging

from flask import Flask

from . import config as config_module

__version__ = "1.0.0"
__all__ = ["create_app", "__version__"]


def create_app(profile: str | None = None, **overrides) -> Flask:
    # Les gabarits et les ressources statiques vivent dans le paquet `web`,
    # a cote des vues qui les utilisent, plutot qu'a la racine du paquet.
    app = Flask(
        __name__,
        template_folder="web/templates",
        static_folder="web/static",
        instance_relative_config=False,
    )
    app.config.from_object(config_module.resolve(profile))
    app.config.update(overrides)

    if app.config.get("EPHEMERAL_SECRET") and not app.config.get("TESTING"):
        logging.getLogger(__name__).warning(
            "GAAP_SECRET_KEY absente : cle de session ephemere generee. "
            "Definir la variable d'environnement avant tout deploiement."
        )

    from .infrastructure import db
    db.init_app(app)

    from .api.routes import api
    from .web.views import web
    app.register_blueprint(api)
    app.register_blueprint(web)

    from .web import filters
    filters.register(app)

    from .cli import register_cli
    register_cli(app)

    @app.after_request
    def _security_headers(response):
        """En-tetes de securite appliques a toutes les reponses.

        Poses au niveau applicatif et non delegues au reverse proxy : une
        application qui depend d'un proxy pour etre sure ne l'est pas quand on
        la deplace.
        """
        response.headers.setdefault("Content-Security-Policy",
                                    app.config["CONTENT_SECURITY_POLICY"])
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy",
                                    "geolocation=(), microphone=(), camera=()")
        return response

    return app
