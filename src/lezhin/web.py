"""Safe lifecycle helpers for the dedicated Lezhin Chrome session."""
from __future__ import annotations

import shutil
import subprocess
import time
import urllib.request
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

from .session import LEZHIN_HOME_URL, get_lezhin_cdp_url
from .urls import is_lezhin_url


def _profile_path() -> Path:
    configured = os.environ.get("LEZHIN_CHROME_PROFILE")
    profile = (Path(configured).expanduser() if configured else
               Path("/private/tmp/lezhin_pilot_profile_20261020"))
    profile = profile.resolve()
    personal_roots = (Path.home() / "Library/Application Support/Google/Chrome",
                      Path.home() / ".config/google-chrome",
                      Path.home() / ".cache/ridibooks_chrome_profile")
    if any(profile == root.resolve() or root.resolve() in profile.parents for root in personal_roots):
        raise RuntimeError("O perfil configurado não é exclusivo do Lezhin.")
    return profile


def _cdp_uses_profile() -> bool:
    """Require the CDP listener to belong to the dedicated profile before attaching."""
    try:
        pids = subprocess.check_output(
            ["/usr/sbin/lsof", "-tiTCP:9223", "-sTCP:LISTEN"],
            text=True, stderr=subprocess.DEVNULL, timeout=2,
        ).split()
        expected = f"--user-data-dir={_profile_path()}"
        return any(expected in subprocess.check_output(
            ["ps", "-p", pid, "-o", "command="], text=True,
            stderr=subprocess.DEVNULL, timeout=2,
        ) for pid in pids)
    except Exception:
        return False


def _chrome_binary() -> Path:
    candidates = (
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    for name in ("google-chrome", "google-chrome-stable", "chrome", "chromium"):
        found = shutil.which(name)
        if found:
            return Path(found)
    raise RuntimeError("Google Chrome não encontrado para o perfil Lezhin.")


def lezhin_session_status() -> dict:
    """Check CDP and visible page state without inspecting cookies or credentials."""
    try:
        with urllib.request.urlopen(get_lezhin_cdp_url() + "/json/version", timeout=1.5):
            pass
    except Exception:
        return {"chrome_state": "unavailable", "session_state": "unknown",
                "message": "Chrome Lezhin indisponível."}
    if not _cdp_uses_profile():
        return {"chrome_state": "error", "session_state": "unknown",
                "message": "A porta CDP 9223 não corresponde ao perfil exclusivo Lezhin; nenhum processo foi alterado."}
    playwright = None
    try:
        playwright = sync_playwright().start()
        browser = playwright.chromium.connect_over_cdp(get_lezhin_cdp_url(), no_defaults=True)
        pages = [page for context in browser.contexts for page in context.pages]
        lezhin_pages = [page for page in pages if is_lezhin_url(page.url)]
        if any("/login" in page.url.split("?", 1)[0].lower() for page in lezhin_pages):
            session_state, message = "unauthenticated", "Chrome conectado; sessão Lezhin não autenticada."
        elif any(page.locator("[data-cut-index]").count() > 0 for page in lezhin_pages):
            session_state, message = "authenticated", "Chrome conectado; leitor autorizado visível."
        else:
            session_state, message = "not_verified", "Chrome conectado; autenticação ainda não confirmada."
        return {"chrome_state": "connected", "session_state": session_state, "message": message}
    except Exception:
        return {"chrome_state": "error", "session_state": "unknown",
                "message": "Falha ao consultar a sessão Chrome Lezhin."}
    finally:
        if playwright:
            try:
                playwright.stop()
            except Exception:
                pass


def start_lezhin_chrome() -> dict:
    """Start only a dedicated Lezhin profile; never take ownership of other Chrome."""
    current = lezhin_session_status()
    if current["chrome_state"] == "connected":
        current["started"] = False
        return current
    if current["chrome_state"] == "error":
        current["started"] = False
        return current
    profile = _profile_path()
    profile.mkdir(parents=True, exist_ok=True)
    command = [str(_chrome_binary()), f"--user-data-dir={profile}",
               "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=9223",
               "--no-first-run", "--no-default-browser-check", "--new-window", LEZHIN_HOME_URL]
    subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        status = lezhin_session_status()
        if status["chrome_state"] == "connected":
            status["started"] = True
            return status
        time.sleep(0.25)
    return {"chrome_state": "unavailable", "session_state": "unknown", "started": True,
            "message": "Chrome iniciado; aguardando disponibilidade do CDP 9223."}
