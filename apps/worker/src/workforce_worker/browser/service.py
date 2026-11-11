"""Sandboxed browser for agents (Playwright + Chromium).

Every call runs in a brand-new browser context: no cookies, no saved logins,
no downloads, no service workers, no pop-ups. Page content is returned as
*untrusted data*; the agent runtime wraps it so instructions inside a web page
are never followed as commands.

Capabilities:
  * read_page   - load a page, optionally follow links by their text, scroll to
                  load lazy content, and return readable text, links and a
                  screenshot. Read-only: it never clicks buttons or submits forms.
  * fill_form   - fill a form and return a screenshot preview; submit only when
                  told to (after your approval) and only on sites you allowed.
                  Refuses password and payment-card fields outright.
"""

import asyncio
import contextlib
import logging
import os
import re
from dataclasses import dataclass, field

from playwright.async_api import Browser, BrowserContext, Page, Playwright, Route, async_playwright
from playwright.async_api import Error as PlaywrightError

from .url_guard import BlockedURL, DomainPolicy, check_form_submission, check_url

log = logging.getLogger(__name__)

MAX_TEXT_CHARS = 20_000
MAX_LINKS = 60
NAV_TIMEOUT_MS = 20_000

_EXTRACT_JS = """
() => {
  const pick = () => {
    for (const sel of ['main', 'article', '[role=main]']) {
      const el = document.querySelector(sel);
      if (el && el.innerText.trim().length > 400) return el;
    }
    return document.body;
  };
  const root = pick();
  const text = (root.innerText || '').replace(/\\n{3,}/g, '\\n\\n').trim();
  const seen = new Set();
  const links = [];
  for (const a of document.querySelectorAll('a[href]')) {
    const href = a.href;
    const label = (a.innerText || a.getAttribute('aria-label') || '').trim().replace(/\\s+/g, ' ');
    if (!href.startsWith('http') || !label || seen.has(href)) continue;
    seen.add(href);
    links.push([label.slice(0, 120), href]);
  }
  return { title: document.title, text, links };
}
"""

_FORM_FIELDS_JS = """
() => Array.from(document.querySelectorAll('input, select, textarea')).map(el => ({
  tag: el.tagName.toLowerCase(),
  type: (el.getAttribute('type') || '').toLowerCase(),
  name: el.getAttribute('name') || '',
  id: el.id || '',
  autocomplete: (el.getAttribute('autocomplete') || '').toLowerCase(),
  label: (el.labels && el.labels[0] ? el.labels[0].innerText : '') ||
         el.getAttribute('aria-label') || el.getAttribute('placeholder') || '',
}))
"""

_FORBIDDEN_AUTOCOMPLETE = ("cc-", "current-password", "new-password", "one-time-code")


@dataclass
class PageResult:
    requested_url: str
    final_url: str
    title: str
    text: str
    links: list[tuple[str, str]]
    truncated: bool
    screenshot_png: bytes | None = None
    blocked_requests: int = 0


@dataclass
class FormResult:
    url: str
    filled: list[str]
    missing: list[str]
    submitted: bool
    final_url: str
    page_text_after: str = ""
    screenshot_png: bytes | None = None
    notes: list[str] = field(default_factory=list)


class BrowserError(RuntimeError):
    pass


class BrowserService:
    def __init__(self, policy: DomainPolicy | None = None, *, max_concurrency: int = 2):
        self.policy = policy or DomainPolicy()
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._slots = asyncio.Semaphore(max_concurrency)

    async def start(self) -> None:
        self._pw = await async_playwright().start()
        executable = os.environ.get("BROWSER_EXECUTABLE_PATH") or None
        proxy = os.environ.get("BROWSER_PROXY_SERVER")  # only where egress needs a proxy
        self._browser = await self._pw.chromium.launch(
            executable_path=executable,
            proxy={"server": proxy} if proxy else None,
            args=["--disable-dev-shm-usage", "--disable-extensions"],
        )

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def __aenter__(self) -> "BrowserService":
        await self.start()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    # --- internals ------------------------------------------------------------------

    async def _new_context(self) -> tuple[BrowserContext, dict]:
        if not self._browser:
            raise BrowserError("browser not started")
        ctx = await self._browser.new_context(
            accept_downloads=False,
            service_workers="block",
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            viewport={"width": 1280, "height": 900},
            java_script_enabled=True,
        )
        stats = {"blocked": 0}

        async def guard(route: Route) -> None:
            req = route.request
            if req.resource_type == "media":
                stats["blocked"] += 1
                await route.abort()
                return
            try:
                await asyncio.to_thread(check_url, req.url, self.policy)
            except BlockedURL:
                stats["blocked"] += 1
                await route.abort("blockedbyclient")
                return
            await route.continue_()

        await ctx.route("**/*", guard)

        # No pop-ups or new tabs.
        async def close_popups(new_page: Page) -> None:
            if await new_page.opener() is not None:
                stats["blocked"] += 1
                await new_page.close()

        ctx.on("page", close_popups)
        return ctx, stats

    async def _goto(self, page: Page, url: str) -> None:
        safe = await asyncio.to_thread(check_url, url, self.policy)
        try:
            response = await page.goto(safe, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        except PlaywrightError as exc:
            raise BrowserError(f"could not load {url}: {exc.message.splitlines()[0]}") from exc
        # Redirects are followed by the browser itself; re-check where we landed.
        await asyncio.to_thread(check_url, page.url, self.policy)
        if response is not None and response.status >= 400:
            raise BrowserError(f"{url} returned HTTP {response.status}")
        # Busy pages never go idle; what has loaded by then is fine.
        with contextlib.suppress(PlaywrightError):
            await page.wait_for_load_state("networkidle", timeout=5_000)

    @staticmethod
    async def _scroll(page: Page, steps: int = 4) -> None:
        for _ in range(steps):
            await page.mouse.wheel(0, 1600)
            await page.wait_for_timeout(250)

    # --- public API ------------------------------------------------------------------

    async def read_page(
        self,
        url: str,
        *,
        follow_links: list[str] | None = None,
        scroll: bool = True,
        screenshot: bool = False,
        max_chars: int = MAX_TEXT_CHARS,
    ) -> PageResult:
        """Load ``url`` (then follow each link text in ``follow_links``) and read it."""
        async with self._slots:
            ctx, stats = await self._new_context()
            try:
                page = await ctx.new_page()
                page.on("dialog", lambda d: asyncio.ensure_future(d.dismiss()))
                await self._goto(page, url)
                for link_text in follow_links or []:
                    href = await self._find_link(page, link_text)
                    await self._goto(page, href)
                if scroll:
                    await self._scroll(page)
                data = await page.evaluate(_EXTRACT_JS)
                text: str = data["text"]
                shot = await page.screenshot(full_page=False, type="png") if screenshot else None
                return PageResult(
                    requested_url=url,
                    final_url=page.url,
                    title=data["title"],
                    text=text[:max_chars],
                    links=[tuple(link) for link in data["links"][:MAX_LINKS]],
                    truncated=len(text) > max_chars,
                    screenshot_png=shot,
                    blocked_requests=stats["blocked"],
                )
            finally:
                await ctx.close()

    @staticmethod
    async def _find_link(page: Page, link_text: str) -> str:
        """Resolve a link by its visible text. Only <a href> navigation (GET) is allowed."""
        anchors = await page.evaluate(
            "() => Array.from(document.querySelectorAll('a[href]'))"
            ".map(a => [(a.innerText || a.getAttribute('aria-label') || '').trim(), a.href])"
        )
        wanted = link_text.strip().lower()
        for text, href in anchors:
            if text.lower() == wanted:
                return href
        for text, href in anchors:
            if wanted in text.lower():
                return href
        raise BrowserError(f"no link with text {link_text!r} on {page.url}")

    async def fill_form(
        self,
        url: str,
        fields: dict[str, str],
        *,
        submit: bool = False,
        submit_text: str | None = None,
    ) -> FormResult:
        """Fill a form by field label/name/placeholder. Submits only if ``submit``."""
        if submit:
            check_form_submission(url, self.policy)
        async with self._slots:
            ctx, _ = await self._new_context()
            try:
                page = await ctx.new_page()
                page.on("dialog", lambda d: asyncio.ensure_future(d.dismiss()))
                await self._goto(page, url)
                inventory = await page.evaluate(_FORM_FIELDS_JS)
                filled, missing, notes = [], [], []
                for key, value in fields.items():
                    el_info = self._match_field(inventory, key)
                    if el_info is None:
                        missing.append(key)
                        continue
                    if el_info["type"] == "password" or el_info["autocomplete"].startswith(
                        _FORBIDDEN_AUTOCOMPLETE
                    ):
                        raise BrowserError(
                            f"refusing to fill {key!r}: passwords, OTPs and card details are "
                            "never entered by agents"
                        )
                    locator = page.locator(self._selector(el_info)).first
                    if el_info["tag"] == "select":
                        await locator.select_option(label=value)
                    elif el_info["type"] in ("checkbox", "radio"):
                        if value.strip().lower() in ("true", "yes", "1", "on"):
                            await locator.check()
                    else:
                        await locator.fill(value)
                    filled.append(key)

                shot = await page.screenshot(full_page=True, type="png")
                submitted = False
                if submit:
                    if missing:
                        raise BrowserError(f"not submitting: could not find {', '.join(missing)}")
                    await self._click_submit(page, submit_text)
                    submitted = True
                    try:
                        await page.wait_for_load_state("networkidle", timeout=8_000)
                    except PlaywrightError:
                        notes.append("page still busy after submit")
                    await asyncio.to_thread(check_url, page.url, self.policy)
                    shot = await page.screenshot(full_page=True, type="png")
                after = (await page.evaluate("() => document.body.innerText"))[:4000]
                return FormResult(
                    url=url,
                    filled=filled,
                    missing=missing,
                    submitted=submitted,
                    final_url=page.url,
                    page_text_after=after,
                    screenshot_png=shot,
                    notes=notes,
                )
            finally:
                await ctx.close()

    @staticmethod
    def _match_field(inventory: list[dict], key: str) -> dict | None:
        k = key.strip().lower()
        for attr in ("label", "name", "id"):
            for f in inventory:
                if f[attr] and f[attr].strip().lower().rstrip("*: ").strip() == k:
                    return f
        for f in inventory:
            if k in (f["label"] or "").lower():
                return f
        return None

    @staticmethod
    def _selector(f: dict) -> str:
        if f["id"]:
            return f"#{f['id']}"
        if f["name"]:
            return f'{f["tag"]}[name="{f["name"]}"]'
        raise BrowserError("field has no id or name to target")

    @staticmethod
    async def _click_submit(page: Page, submit_text: str | None) -> None:
        if submit_text:
            await page.get_by_role("button", name=submit_text).first.click()
            return
        candidates = page.locator("button[type=submit], input[type=submit]")
        if await candidates.count() == 0:
            candidates = page.get_by_role(
                "button", name=re.compile("submit|register|send|continue", re.IGNORECASE)
            )
        await candidates.first.click()
