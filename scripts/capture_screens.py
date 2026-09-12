"""Captures d'ecran de la documentation.

Versionne avec le projet pour que les images du README soient reproductibles :
une capture faite a la main devient fausse des la premiere evolution de
l'interface, et personne ne s'en apercoit.

    python3 scripts/capture_screens.py

Demarre l'application sur une base de demonstration temporaire, capture les
ecrans dans docs/assets/, puis s'arrete. Chromium est pilote par Playwright.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, make_server

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUTPUT = ROOT / "docs" / "assets"
PORT = 5199
VIEWPORT = {"width": 1480, "height": 1000}

#: Certains environnements fournissent un Chromium pre-installe dont la version
#: de build ne correspond pas a celle attendue par le paquet Playwright. On le
#: designe explicitement plutot que de declencher un telechargement.
CHROMIUM = os.environ.get("GAAP_CHROMIUM") or next(
    (path for path in ("/opt/pw-browsers/chromium",) if Path(path).exists()), None
)

#: (nom de fichier, chemin, selecteur a capturer ou None pour la page entiere)
SHOTS = [
    ("01-cockpit.png", "/", None),
    ("02-experience-verdict.png", "/experiences/pp-taeg-2026q3", None),
    ("03-garde-fous-refus.png", "/experiences/auto-offensive-2026q4", None),
    ("04-laboratoire.png", "/laboratoire/pp-taeg-2026q3", None),
    ("05-piste-audit.png", "/piste-audit", None),
    ("06-nouveau-plan.png", "/experiences/nouvelle", None),
]

CLIPS = {
    "02-experience-verdict.png": 1750,
    "03-garde-fous-refus.png": 1500,
    "05-piste-audit.png": 1450,
    "06-nouveau-plan.png": 1550,
}


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, *_args):  # pragma: no cover - bruit inutile
        pass


def _prepare_database() -> Path:
    database = ROOT / "instance" / "gaap-docs.sqlite"
    database.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        Path(str(database) + suffix).unlink(missing_ok=True)
    env = {**os.environ, "GAAP_DATABASE": str(database), "FLASK_APP": "gaap"}
    subprocess.run([sys.executable, "-m", "flask", "init-db"], cwd=ROOT, env=env, check=True,
                   stdout=subprocess.DEVNULL)
    subprocess.run([sys.executable, "-m", "flask", "seed", "--reset"], cwd=ROOT, env=env,
                   check=True, stdout=subprocess.DEVNULL)
    return database


def main() -> int:
    from playwright.sync_api import sync_playwright

    from gaap import create_app

    database = _prepare_database()
    OUTPUT.mkdir(parents=True, exist_ok=True)

    app = create_app("production", DATABASE=str(database), SESSION_COOKIE_SECURE=False)
    server = make_server("127.0.0.1", PORT, app, handler_class=_QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.4)

    try:
        with sync_playwright() as playwright:
            launch_options = {"executable_path": CHROMIUM} if CHROMIUM else {}
            browser = playwright.chromium.launch(**launch_options)
            page = browser.new_page(viewport=VIEWPORT, device_scale_factor=2)
            for filename, path, selector in SHOTS:
                page.goto(f"http://127.0.0.1:{PORT}{path}", wait_until="networkidle")
                if filename == "04-laboratoire.png":
                    page.fill("#elasticity", "-4,0")
                    page.fill("#baseline", "6,10")
                    page.fill("#volume", "46000")
                    page.click("button[type=submit]")
                    page.wait_for_selector(".kpi.accent")
                page.wait_for_timeout(350)
                target = OUTPUT / filename
                if selector:
                    page.locator(selector).screenshot(path=str(target))
                elif filename in CLIPS:
                    page.screenshot(path=str(target), clip={
                        "x": 0, "y": 0, "width": VIEWPORT["width"], "height": CLIPS[filename],
                    })
                else:
                    page.screenshot(path=str(target), full_page=True)
                print(f"  {filename:32} {target.stat().st_size // 1024:>5} Ko")
            browser.close()
    finally:
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
