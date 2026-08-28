"""Local HTML/CSS/JS interface using only Python's standard-library HTTP server.

The server binds exclusively to 127.0.0.1 and reuses the existing Python core.
"""
from __future__ import annotations

import json
import logging
import mimetypes
import os
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlparse

from gui.config import ConfigManager
from src.converter import convert_to_cbz, convert_to_pdf
from src.downloader import ChapterDownloader, discover_chapter_reader_pages_with_cookies, get_chapter_list
from src.models import Chapter, Manga
from src.search import get_manga_details, search_manga


PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"
TEMPLATE_DIR = PACKAGE_DIR / "templates"
_config = ConfigManager()
_jobs: Dict[str, Dict[str, Any]] = {}
_jobs_lock = threading.RLock()

web_logger = logging.getLogger("mangago.web")



def _configure_logging() -> None:
    level_name = os.environ.get("MANGAGO_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )

def _manga_dict(manga: Manga) -> Dict[str, Any]:
    return {
        "title": manga.title,
        "url": manga.url,
        "author": manga.author or "",
        "genres": list(manga.genres or []),
        "total_chapters": manga.total_chapters or 0,
        "cover_image_url": manga.cover_image_url or "",
        "summary": manga.summary or "",
    }


def _chapter_dict(chapter: Chapter) -> Dict[str, Any]:
    return {"number": chapter.number, "url": chapter.url, "title": chapter.title or f"Capítulo {chapter.number:g}"}


def _job_snapshot(job_id: str) -> Dict[str, Any] | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        snap = {k: v for k, v in job.items() if k != "chapters"}
        snap["chapters"] = [dict(row) for row in job.get("chapters", [])]
        return snap


def _update_job(job_id: str, **values: Any) -> None:
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id].update(values)


def _update_chapter_row(job_id: str, chapter_url: str, **values: Any) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return
        for row in job.get("chapters", []):
            if row.get("url") == chapter_url:
                row.update(values)
                return


def _refresh_job_progress(job_id: str) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return
        rows = job.get("chapters", [])
        total = len(rows)
        if not total:
            job["progress"] = 0
            job["active_count"] = 0
            return
        job["progress"] = max(0, min(100, round(sum(float(r.get("progress", 0)) for r in rows) / total)))
        job["active_count"] = sum(1 for r in rows if r.get("status") in {"downloading", "converting"})


def _run_download(job_id: str, manga: Manga, chapters: List[Chapter], settings: Dict[str, Any]) -> None:
    downloader = None
    completed = 0
    failed = 0
    try:
        workers = max(1, min(3, int(settings.get("max_workers", 3))))
        _update_job(job_id, state="running", phase="preparing", message="Preparando capítulos…", active_count=0)
        downloader = ChapterDownloader(
            max_workers=workers,
            download_dir=settings.get("download_location") or str(Path.home() / "Downloads" / "mangago"),
            image_format=settings.get("image_format", "original"),
            keep_originals=bool(settings.get("keep_originals", False)),
            page_delay=float(settings.get("page_delay", 2.0)),
            retry_count=int(settings.get("retry_count", 3)),
            timeout=int(settings.get("timeout", 30)),
        )

        # Keep Playwright discovery sequential. This avoids opening several browsers at once.
        valid_chapters: List[Chapter] = []
        for chapter in chapters:
            _update_job(job_id, phase="locating", message=f"Localizando páginas do capítulo {chapter.number:g}…")
            _update_chapter_row(job_id, chapter.url, status="locating", message="Localizando páginas", progress=0)
            try:
                web_logger.info(
                    "[JOB %s] discovery Ch.%s iniciado | url=%s | workers=%s | timeout=%ss",
                    job_id[:8], chapter.number, chapter.url, workers, int(settings.get("timeout", 30)),
                )
                page_urls, cookie_header = discover_chapter_reader_pages_with_cookies(
                    chapter.url,
                    timeout=int(settings.get("timeout", 30)),
                )
                chapter.image_urls = page_urls
                setattr(chapter, "reader_cookie_header", cookie_header)
                web_logger.info(
                    "[JOB %s] discovery Ch.%s concluído | páginas=%s",
                    job_id[:8], chapter.number, len(chapter.image_urls),
                )
                valid_chapters.append(chapter)
                _update_chapter_row(job_id, chapter.url, status="queued", message=f"{len(chapter.image_urls)} páginas encontradas", total_pages=len(chapter.image_urls))
            except Exception as exc:
                web_logger.exception("[JOB %s] discovery Ch.%s falhou: %s", job_id[:8], chapter.number, exc)
                failed += 1
                completed += 1
                _update_chapter_row(job_id, chapter.url, status="failed", message=str(exc), progress=100)
                _update_job(job_id, completed=completed, failed=failed)
                _refresh_job_progress(job_id)

        if valid_chapters:
            _update_job(job_id, phase="downloading", message=f"Baixando páginas com até {workers} downloads simultâneos…")

            def on_page(chapter: Chapter, current: int, total_pages: int) -> None:
                pct = round((current / total_pages) * 100) if total_pages else 0
                _update_chapter_row(job_id, chapter.url, status="downloading", current_page=current,
                                    total_pages=total_pages, progress=pct, message=f"{current}/{total_pages} páginas")
                _refresh_job_progress(job_id)

            downloader.progress_callback = on_page

            def on_result(result) -> None:
                nonlocal completed, failed
                chapter = result.chapter
                if result.success:
                    format_type = str(settings.get("format", "images")).lower()
                    if format_type in {"pdf", "cbz"} and result.file_path:
                        _update_chapter_row(job_id, chapter.url, status="converting", message=f"Gerando {format_type.upper()}…", progress=100)
                        _refresh_job_progress(job_id)
                        if format_type == "pdf":
                            convert_to_pdf(result.file_path, delete_images=bool(settings.get("delete_images", False)))
                        else:
                            convert_to_cbz(result.file_path, delete_images=bool(settings.get("delete_images", False)))
                    _update_chapter_row(job_id, chapter.url, status="completed", progress=100, message="Concluído")
                else:
                    failed += 1
                    _update_chapter_row(job_id, chapter.url, status="failed", progress=100, message=result.error_message or "Falha no download")
                completed += 1
                _update_job(job_id, completed=completed, failed=failed)
                _refresh_job_progress(job_id)

            downloader.download_chapters(manga, valid_chapters, result_callback=on_result)

        state = "completed" if failed == 0 else "completed_with_errors"
        message = "Download concluído" if failed == 0 else f"Concluído com {failed} falha(s)"
        _update_job(job_id, state=state, phase="done", progress=100, active_count=0, message=message, finished_at=time.time())
    except Exception as exc:
        _update_job(job_id, state="failed", phase="error", active_count=0, message=str(exc), finished_at=time.time())
    finally:
        if downloader:
            downloader.close()


class MangagoWebHandler(BaseHTTPRequestHandler):
    server_version = "MangagoDownloaderWeb/2"

    def log_message(self, fmt: str, *args: Any) -> None:
        # Keep terminal output useful; ignore noisy static asset GETs.
        if not str(args[0] if args else "").startswith("GET /static/"):
            super().log_message(fmt, *args)

    def _json(self, payload: Any, status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def _file(self, path: Path, content_type: str | None = None) -> None:
        if not path.is_file():
            self.send_error(404)
            return
        raw = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            self._file(TEMPLATE_DIR / "index.html", "text/html; charset=utf-8")
            return
        if path == "/static/styles.css":
            self._file(STATIC_DIR / "styles.css", "text/css; charset=utf-8")
            return
        if path == "/static/app.js":
            self._file(STATIC_DIR / "app.js", "application/javascript; charset=utf-8")
            return
        if path == "/api/health":
            self._json({"ok": True, "app": "Mangago Downloader Web V2"})
            return
        if path == "/api/settings":
            self._json(_config.get_all())
            return
        if path == "/api/search":
            query = (parse_qs(parsed.query).get("q") or [""])[0].strip()
            if not query:
                self._json({"error": "Informe um título para buscar."}, 400)
                return
            try:
                page = max(1, int((parse_qs(parsed.query).get("page") or ["1"])[0]))
                results = search_manga(query, page)
                self._json({"query": query, "page": page, "results": [_manga_dict(item.manga) for item in results]})
            except Exception as exc:
                self._json({"error": str(exc)}, 502)
            return
        if path == "/api/downloads":
            with _jobs_lock:
                ids = list(_jobs.keys())[::-1]
            self._json([_job_snapshot(job_id) for job_id in ids])
            return
        if path.startswith("/api/downloads/"):
            job_id = path.rsplit("/", 1)[-1]
            snapshot = _job_snapshot(job_id)
            if not snapshot:
                self._json({"error": "Download não encontrado."}, 404)
            else:
                self._json(snapshot)
            return
        self.send_error(404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        payload = self._read_json()
        if path == "/api/manga":
            url = str(payload.get("url") or "").strip()
            if not url:
                self._json({"error": "URL do mangá não informada."}, 400)
                return
            try:
                manga, handle = get_manga_details(url)
                chapters = get_chapter_list(handle)
                manga.total_chapters = len(chapters)
                self._json({"manga": _manga_dict(manga), "chapters": [_chapter_dict(ch) for ch in chapters]})
            except Exception as exc:
                self._json({"error": str(exc)}, 502)
            return

        if path == "/api/downloads":
            manga_payload = payload.get("manga") or {}
            chapter_payloads = payload.get("chapters") or []
            if not manga_payload.get("url") or not chapter_payloads:
                self._json({"error": "Selecione ao menos um capítulo."}, 400)
                return
            manga = Manga(
                title=str(manga_payload.get("title") or "Manga"), url=str(manga_payload.get("url")),
                author=str(manga_payload.get("author") or ""), genres=list(manga_payload.get("genres") or []),
                cover_image_url=str(manga_payload.get("cover_image_url") or ""), summary=str(manga_payload.get("summary") or ""),
            )
            chapters = [Chapter(number=float(item["number"]), url=str(item["url"]), title=str(item.get("title") or ""))
                        for item in chapter_payloads if item.get("url") and item.get("number") is not None]
            if not chapters:
                self._json({"error": "Nenhum capítulo válido foi informado."}, 400)
                return
            job_id = uuid.uuid4().hex[:12]
            settings = _config.get_all()
            rows = [{"number": ch.number, "title": ch.title or f"Capítulo {ch.number:g}", "url": ch.url,
                     "status": "queued", "progress": 0, "current_page": 0, "total_pages": 0, "message": "Aguardando"}
                    for ch in chapters]
            with _jobs_lock:
                _jobs[job_id] = {
                    "id": job_id, "state": "queued", "phase": "queued", "message": "Na fila", "manga": _manga_dict(manga),
                    "total": len(chapters), "completed": 0, "failed": 0, "progress": 0, "active_count": 0,
                    "created_at": time.time(), "finished_at": None, "chapters": rows,
                }
            threading.Thread(target=_run_download, args=(job_id, manga, chapters, settings), daemon=True).start()
            self._json({"job_id": job_id}, 202)
            return
        self.send_error(404)

    def do_PUT(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/settings":
            self.send_error(404)
            return
        payload = self._read_json()
        allowed = {"download_location", "max_workers", "retry_count", "timeout", "page_delay", "overwrite_existing",
                   "format", "delete_images", "image_format", "keep_originals"}
        current = _config.get_all()
        for key, value in payload.items():
            if key in allowed:
                current[key] = value
        try:
            current["page_delay"] = max(0.0, float(current.get("page_delay", 2.0)))
            current["max_workers"] = max(1, min(3, int(current.get("max_workers", 3))))
            current["retry_count"] = max(0, int(current.get("retry_count", 3)))
            current["timeout"] = max(1, int(current.get("timeout", 30)))
        except (TypeError, ValueError):
            self._json({"error": "Configuração numérica inválida."}, 400)
            return
        _config.set_all(current)
        self._json(current)


def create_server(host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), MangagoWebHandler)


def main() -> None:
    host = "127.0.0.1"
    port = int(os.environ.get("MANGAGO_WEB_PORT", "8765"))
    url = f"http://{host}:{port}"
    server = create_server(host, port)
    if os.environ.get("MANGAGO_WEB_NO_BROWSER", "0") != "1":
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    print(f"Mangago Downloader Web V2: {url}")
    print("Pressione Ctrl+C para encerrar.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
