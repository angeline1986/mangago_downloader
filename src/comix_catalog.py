"""Find Comix chapter groups across the title catalog's pages."""
from __future__ import annotations

import logging
import re

from .utils import DownloadError, ParsingError


logger = logging.getLogger("mangago.comix.catalog")


async def has_next_page(page, current: int) -> bool:
    """Use the site's pager instead of requesting an empty page."""
    return await page.locator(".npager").evaluate_all(
        """(pagers, current) => pagers.some(pager => {
          const numbers = [...pager.querySelectorAll('.npager__num')]
            .map(button => Number(button.textContent.trim()));
          const next = [...pager.querySelectorAll('.npager__nav')]
            .some(button => button.getAttribute('aria-label') === 'Next page'
              && !button.disabled);
          return numbers.some(number => number > current) || next;
        })""",
        current,
    )


async def collect_chapter_groups(page, base_url: str, timeout_ms: int) -> list[dict]:
    """Collect group links from every unfiltered title page."""
    groups: dict[str, dict] = {}
    page_number = 1

    while True:
        links = await page.locator('a[href^="/groups/"]').evaluate_all(
            """els => els.map(el => ({
              name: (el.textContent || '').trim(),
              href: el.getAttribute('href') || '',
              official: el.classList.contains('is-official')
            }))"""
        )
        for link in links:
            match = re.search(r"/groups/(\d+)", link.get("href") or "")
            if not match:
                continue
            group_id = match.group(1)
            groups[group_id] = {
                "id": group_id,
                "name": str(link.get("name") or "").strip() or f"Group {group_id}",
                "official": bool(link.get("official")),
            }

        logger.info("Catálogo · página=%s fontes acumuladas=%s", page_number, len(groups))
        if not await has_next_page(page, page_number):
            break
        if page_number >= 200:
            raise ParsingError("Comix title catalog exceeded 200 pages.")

        page_number += 1
        response = await page.goto(
            f"{base_url}?page={page_number}",
            wait_until="domcontentloaded",
            timeout=timeout_ms,
        )
        if response is not None and response.status >= 400:
            raise DownloadError(f"Comix title catalog returned HTTP {response.status}.")
        await page.locator(".mchap-item").first.wait_for(
            state="attached", timeout=timeout_ms,
        )

    if not groups:
        raise ParsingError("Comix title page exposed no chapter groups.")
    return sorted(groups.values(), key=lambda group: (
        not group["official"], group["name"].casefold(), group["id"],
    ))
