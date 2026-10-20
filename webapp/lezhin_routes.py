"""Lezhin Central Web endpoints, delegating browser work to its provider modules."""
from __future__ import annotations

import math
from typing import Callable
from urllib.parse import urlsplit

from src.lezhin.discovery import discover_lezhin_catalog, verify_lezhin_episode_access
from src.lezhin.session import lezhin_cdp_session
from src.lezhin.urls import LEZHIN_PROVIDER_ID, validate_episode_url, validate_work_url
from src.lezhin.web import lezhin_session_status, start_lezhin_chrome
from src.lezhin.catalog import EpisodeAvailability
from src.models import Chapter, Manga


def _episode_rows(catalog) -> list[dict]:
    return [{"number": item.number, "title": item.title, "url": item.url,
             "availability": item.availability.value,
             "chapter_compatible": item.chapter is not None}
            for item in catalog.episodes]


def _canonical_episode(value: str) -> str:
    parsed = urlsplit(validate_episode_url(value))
    return f"https://www.lezhinus.com{parsed.path.rstrip('/')}"


def handle_get(path: str) -> tuple[int, dict]:
    if path == "/api/lezhinus/session":
        return 200, lezhin_session_status()
    return 404, {"error": "Endpoint Lezhin não encontrado."}


def handle_post(path: str, payload: dict, enqueue: Callable) -> tuple[int, dict]:
    if path == "/api/lezhinus/session/start":
        try:
            result = start_lezhin_chrome()
            if result.get("chrome_state") == "error":
                return 502, {"error": result.get("message") or "Falha na sessão Chrome Lezhin."}
            return 200, result
        except Exception:
            return 502, {"error": "Não foi possível iniciar o Chrome Lezhin dedicado."}
    if path == "/api/lezhinus/chapters":
        return _discover(payload)
    if path == "/api/lezhinus/verify":
        url = str(payload.get("url") or "")
        try:
            with lezhin_cdp_session() as session:
                availability = verify_lezhin_episode_access(session.page, url)
            return 200, {"url": _canonical_episode(url), "availability": availability.value}
        except ValueError:
            return 400, {"error": "Informe uma URL válida de episódio Lezhin."}
        except Exception:
            return 502, {"error": "Não foi possível verificar o acesso ao episódio."}
    if path == "/api/lezhinus/downloads":
        return _queue_accessible(payload, enqueue)
    return 404, {"error": "Endpoint Lezhin não encontrado."}


def _discover(payload: dict) -> tuple[int, dict]:
    try:
        work_url = validate_work_url(str(payload.get("url") or ""))
        with lezhin_cdp_session() as session:
            if "/login" in session.page.url.split("?", 1)[0].lower():
                return 401, {"error": "AUTH_REQUIRED", "code": "AUTH_REQUIRED"}
            catalog = discover_lezhin_catalog(session.page, work_url)
        return 200, {"provider": LEZHIN_PROVIDER_ID, "url": catalog.manga.url,
                     "title": catalog.manga.title, "chapters": _episode_rows(catalog)}
    except ValueError:
        return 400, {"error": "Informe uma URL válida de obra Lezhin."}
    except Exception:
        return 502, {"error": "Falha ao carregar os episódios Lezhin. Verifique a sessão e tente novamente."}


def _queue_accessible(payload: dict, enqueue: Callable) -> tuple[int, dict]:
    manga_data = payload.get("manga") or {}
    items = payload.get("chapters") or []
    try:
        work_url = validate_work_url(str(manga_data.get("url") or ""))
        title = str(manga_data.get("title") or "Lezhin").strip() or "Lezhin"
        chapters = []
        work_path = urlsplit(work_url).path.rstrip("/") + "/"
        if not items:
            return 400, {"error": "Selecione ao menos um episódio."}
        for item in items:
            url = _canonical_episode(str(item.get("url") or ""))
            if not urlsplit(url).path.startswith(work_path) or item.get("number") is None:
                return 400, {"error": "A seleção contém episódio inválido ou sem numeração confiável."}
            number = float(item["number"])
            if not math.isfinite(number) or number <= 0 or any(ch.url == url for ch in chapters):
                return 400, {"error": "A seleção contém número inválido ou episódio duplicado."}
            chapters.append(Chapter(number=number, url=url,
                                    title=str(item.get("title") or ""),
                                    folder_pattern=str(item.get("folder_pattern") or "").strip() or None))
    except (ValueError, TypeError, KeyError):
        return 400, {"error": "Dados de obra ou episódio Lezhin inválidos."}
    try:
        with lezhin_cdp_session() as session:
            for chapter in chapters:
                access = verify_lezhin_episode_access(session.page, chapter.url)
                if access is EpisodeAvailability.AUTH_REQUIRED:
                    return 401, {"error": "AUTH_REQUIRED", "code": "AUTH_REQUIRED"}
                if access is not EpisodeAvailability.ACCESSIBLE:
                    label = chapter.title or f"episódio {chapter.number:g}"
                    return 409, {"error": f"Acesso não confirmado para {label}; nada foi enfileirado."}
    except Exception:
        return 502, {"error": "Falha de conexão ou carregamento no Chrome Lezhin; nada foi enfileirado."}
    manga = Manga(title=title, url=work_url)
    return 202, {"job_id": enqueue(manga, chapters)}
