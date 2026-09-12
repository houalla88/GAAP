"""Point d'entree de developpement.

En production, servir l'application par un serveur WSGI (gunicorn, uWSGI) :

    gunicorn "gaap:create_app('production')" --bind 0.0.0.0:8000 --workers 4

Le serveur de developpement de Flask n'est ni concurrent ni durci ; l'utiliser
ailleurs qu'en local est une erreur d'exploitation.
"""

from gaap import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
