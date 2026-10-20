"""Bounded Lezhin work-page discovery and explicit episode access probes."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from .catalog import EpisodeAvailability, LezhinCatalog, build_catalog, normalize_work_title
from .urls import validate_episode_url, validate_work_url


_ROWS_JS = r"""() => {
  const episode = /^\/[^/]+\/comic\/[^/]+\/\d+\/?$/;
  const workPrefix = location.pathname.replace(/\/$/, '') + '/';
  const rows = [];
  for (const link of document.querySelectorAll('a[href]')) {
    const url = new URL(link.href, location.href);
    if (url.origin !== location.origin || !url.pathname.startsWith(workPrefix) ||
        !episode.test(url.pathname)) continue;
    const row = link.closest('li, article, [class*=episode-item], [class*=episode-row], '
      + '[class*=chapter-item], [class*=chapter-row]') || link;
    const text = (row?.innerText || row?.textContent || '').replace(/\s+/g, ' ').trim();
    rows.push({url: url.href, title: (link.innerText || link.textContent || '').trim(),
      row_text: text, markers: [row?.className || '', row?.getAttribute?.('aria-label') || '',
        ...Array.from(row?.querySelectorAll?.('[aria-label], [title]') || [])
          .flatMap(el => [el.getAttribute('aria-label') || '', el.getAttribute('title') || ''])]
          .join(' ')});
  }
  const title = (document.querySelector('h1')?.innerText ||
    document.querySelector('meta[property="og:title"]')?.content || document.title || '').trim();
  return {title, rows};
}"""

def discover_lezhin_catalog(page: Page, work_url: str, max_scroll_steps: int = 100) -> LezhinCatalog:
    """Collect rendered episode rows while scrolling the work page, without unlocking."""
    canonical = validate_work_url(work_url)
    response = page.goto(canonical, wait_until="domcontentloaded", timeout=30_000)
    if response is not None and response.status >= 400:
        raise RuntimeError(f"Lezhin work page returned HTTP {response.status}")
    try:
        page.wait_for_function(r"""() => {
          const prefix = location.pathname.replace(/\/$/, '') + '/';
          return Array.from(document.querySelectorAll('a[href]')).some(a => {
            try { const path = new URL(a.href).pathname;
              return path.startsWith(prefix) && /^\/[^/]+\/comic\/[^/]+\/\d+\/?$/.test(path); }
            catch { return false; }
          });
        }""", timeout=15_000)
    except PlaywrightTimeoutError as exc:
        raise RuntimeError("Lezhin work page exposed no episode links") from exc
    rows_by_url: dict[str, dict] = {}
    title = ""
    steps = max(1, min(int(max_scroll_steps), 200))
    stable_bottom = 0
    for _ in range(steps):
        payload = page.evaluate(_ROWS_JS)
        title = normalize_work_title(str(payload.get("title") or title))
        for row in payload.get("rows") or []:
            rows_by_url.setdefault(str(row.get("url") or ""), row)
        position = page.evaluate("() => ({top: scrollY, view: innerHeight, height: document.documentElement.scrollHeight})")
        at_bottom = position["top"] + position["view"] >= position["height"] - 2
        before = len(rows_by_url)
        if at_bottom:
            page.wait_for_timeout(350)
            latest = page.evaluate(_ROWS_JS)
            for row in latest.get("rows") or []:
                rows_by_url.setdefault(str(row.get("url") or ""), row)
            stable_bottom = stable_bottom + 1 if len(rows_by_url) == before else 0
            if stable_bottom >= 2:
                break
        else:
            page.evaluate("() => window.scrollBy(0, Math.max(300, Math.floor(innerHeight * 0.75)))")
            page.wait_for_timeout(350)
    if not rows_by_url:
        raise RuntimeError("Lezhin work page rendered no episode rows")
    return build_catalog(canonical, title, list(rows_by_url.values()))


def verify_lezhin_episode_access(page: Page, episode_url: str) -> EpisodeAvailability:
    """Probe the supplied episode without buying/unlocking; listing alone is inconclusive."""
    target = validate_episode_url(episode_url)
    response = page.goto(target, wait_until="domcontentloaded", timeout=30_000)
    if response is not None and response.status >= 400:
        return EpisodeAvailability.UNAVAILABLE
    try:
        page.wait_for_function(r"""() => /\/login(?:\/|$)/i.test(location.pathname) ||
          document.querySelector('[data-cut-index]') ||
          document.querySelector('[class*=paywall i], [class*=locked i], [class*=purchase i]')""",
          timeout=8_000)
    except PlaywrightTimeoutError:
        pass
    current = urlsplit(page.url)
    if current.hostname not in {"lezhinus.com", "www.lezhinus.com"}:
        return EpisodeAvailability.UNAVAILABLE
    if re.search(r"/login(?:/|$)", current.path, re.I):
        return EpisodeAvailability.AUTH_REQUIRED
    try:
        page.wait_for_selector("[data-cut-index]", state="attached", timeout=5_000)
    except PlaywrightTimeoutError:
        pass
    if page.locator("[data-cut-index]").count() > 0:
        return EpisodeAvailability.ACCESSIBLE
    paywall = page.locator(
        '[class*="paywall" i], [class*="locked" i], [class*="purchase" i], '
        '[data-testid*="purchase" i]'
    )
    text = paywall.inner_text(timeout=5_000).casefold() if paywall.count() else ""
    if re.search(r"\b(locked|purchase|buy|coins?|not available)\b", text):
        return EpisodeAvailability.UNAVAILABLE
    return EpisodeAvailability.LISTED
