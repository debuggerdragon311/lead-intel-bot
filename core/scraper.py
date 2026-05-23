"""Asynchronous stealth browser scraping pipeline.

Provides a single async entry point, harvest_company_data(), that spins up
a sandboxed headless Chromium instance and runs a two-phase text harvesting
workflow:

    Phase A -- DuckDuckGo static HTML query
        Retrieves contextual snippets (founder, CEO, key people) from
        DuckDuckGo's no-JavaScript HTML frontend to avoid bot-detection
        mechanisms present on the JavaScript-rendered endpoint.

    Phase B -- Direct landing page crawl
        Navigates to the company's root domain and extracts the visible
        body text for downstream AI entity extraction.

Stealth posture:
    playwright_stealth patches the page's JavaScript navigator fingerprint
    so that headless Chromium is indistinguishable from a regular browser
    session. Automation flags are stripped at the Chromium argument level
    as well (--disable-blink-features=AutomationControlled).

uBlock Origin:
    If a packaged uBlock Origin extension is present in the application
    sandbox (resolved via resource_path()), it is loaded into the browser
    context to suppress ad and tracker network requests, reducing page
    load times and preventing ad scripts from poisoning the harvested text.

Error isolation:
    Each phase wraps its navigation in an independent try-except block.
    A failure in Phase A does not abort Phase B, and vice versa. The
    browser is always closed in a finally block to prevent orphaned
    Chromium child processes from accumulating in system memory.
"""

import os
import re

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    Playwright,
    ViewportSize,
)
from playwright_stealth import Stealth

from core.config import resource_path
from core.state  import add_log


# =============================================================================
# Module-Level Constants
# =============================================================================

# Emulated Windows Chrome user-agent string. Matches the viewport and locale
# below to form a coherent, non-headless browser fingerprint.
_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_VIEWPORT_WIDTH:  int = 1280
_VIEWPORT_HEIGHT: int = 800
_LOCALE:          str = "en-US"

# Hard navigation timeout in milliseconds applied to every goto() call.
_NAV_TIMEOUT_MS: int = 20_000

# Maximum number of DuckDuckGo result snippets consumed per query.
_DDG_SNIPPET_LIMIT: int = 4

# Maximum characters taken from the raw landing page body text.
_BODY_TEXT_LIMIT: int = 1_500

# DuckDuckGo static HTML endpoint. Using the /html/ variant avoids the
# JavaScript-rendered frontend and its associated bot-detection layer.
_DDG_URL: str = "https://html.duckduckgo.com/html/"

# CSS selector for DuckDuckGo result snippet elements.
_DDG_SNIPPET_SELECTOR: str = ".result__snippet"

# Chromium launch arguments applied regardless of extension availability.
_BASE_CHROMIUM_ARGS: list[str] = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-infobars",
]


# =============================================================================
# Internal Helpers
# =============================================================================

def _normalize_domain(target: str) -> str:
    """
    Derive a valid lowercase domain string from a raw company target.

    The target is lowercased and stripped of leading/trailing whitespace.
    If it contains no dot (i.e., no TLD is present), ".com" is appended
    as the default TLD so that bare company names like "acme" resolve to
    "acme.com" rather than producing a malformed URL.

    Args:
        target: Raw company name or domain string supplied by the caller.

    Returns:
        A lowercase domain string guaranteed to contain at least one dot.

    Examples:
        "Acme Corp"  ->  "acme corp.com"   (no TLD detected, .com appended)
        "acme.io"    ->  "acme.io"         (TLD present, returned as-is)
        "ACME.CO.UK" ->  "acme.co.uk"      (multi-part TLD preserved)
    """
    normalized: str = target.strip().lower()
    if "." not in normalized:
        normalized = f"{normalized}.com"
    return normalized


def _clean_body_text(raw: str) -> str:
    """
    Collapse consecutive whitespace sequences in raw page body text.

    inner_text() on a live page body frequently returns large blocks of
    whitespace, repeated newlines, and tab characters originating from
    CSS-hidden elements or whitespace-collapsing rules. This function
    reduces all such sequences to a single space so that the downstream
    AI prompt receives clean, token-efficient prose.

    Args:
        raw: Unprocessed string returned by Playwright's inner_text().

    Returns:
        A whitespace-normalized string with no leading/trailing spaces.
    """
    return re.sub(r"\s+", " ", raw).strip()


def _build_chromium_args() -> list[str]:
    """
    Assemble the full Chromium launch argument list.

    Starts with the static base arguments and conditionally appends the
    uBlock Origin extension flags if the packaged extension directory
    exists inside the application sandbox. The extension path is resolved
    through resource_path() to support both dev and PyInstaller-frozen
    environments transparently.

    Returns:
        A list of Chromium command-line argument strings ready to be
        passed to playwright.chromium.launch(args=...).
    """
    args: list[str] = list(_BASE_CHROMIUM_ARGS)

    ublock_path: str = resource_path("extensions/ublock")

    if os.path.isdir(ublock_path):
        add_log(
            f"[SCRAPER] uBlock Origin extension found. "
            f"Loading from sandbox: {ublock_path}"
        )
        args.append(f"--disable-extensions-except={ublock_path}")
        args.append(f"--load-extension={ublock_path}")
    else:
        add_log(
            "[SCRAPER] uBlock Origin extension not found in sandbox. "
            "Proceeding without ad-blocking."
        )

    return args


# =============================================================================
# Scraping Phase Implementations
# =============================================================================

async def _phase_a_duckduckgo(
    page:           Page,
    company_target: str,
    payload:        list[str],
) -> None:
    """
    Phase A: Query DuckDuckGo's static HTML frontend for company context.

    Searches for "<company_target> founder CEO key people" on the /html/
    endpoint, extracts the top _DDG_SNIPPET_LIMIT result snippets, and
    appends them as a labeled block to the shared payload list.

    Args:
        page:           An active Playwright Page instance.
        company_target: The normalized company domain or name string.
        payload:        The mutable list accumulating all harvested text.
    """
    query: str = f'"{company_target}" founder CEO key people'
    add_log(f"[HARVEST] Phase A: Querying DuckDuckGo for `{query}`")

    try:
        await page.goto(_DDG_URL, timeout=_NAV_TIMEOUT_MS)
        await page.fill('[name="q"]', query)
        await page.keyboard.press("Enter")
        await page.wait_for_load_state("domcontentloaded")

        snippet_elements = await page.query_selector_all(_DDG_SNIPPET_SELECTOR)
        snippets: list[str] = []

        for element in snippet_elements[:_DDG_SNIPPET_LIMIT]:
            text: str = (await element.inner_text()).strip()
            if text:
                snippets.append(text)

        if snippets:
            payload.append(
                f"\n--- [DUCKDUCKGO CONTEXT: {company_target}] ---\n"
                + "\n".join(snippets)
            )
            add_log(
                f"[HARVEST] Phase A complete. "
                f"Collected {len(snippets)} DuckDuckGo snippet(s)."
            )
        else:
            add_log("[HARVEST] Phase A: No snippets extracted from DuckDuckGo.")

    except Exception as exc:
        add_log(
            f"[HARVEST] Phase A WARNING: DuckDuckGo query failed "
            f"for `{company_target}`. Reason: {exc}"
        )


async def _phase_b_landing_page(
    page:    Page,
    domain:  str,
    payload: list[str],
) -> None:
    """
    Phase B: Crawl the company's root landing page for raw body text.

    Navigates to https://<domain>, extracts visible body text via
    inner_text(), normalizes whitespace, and appends the first
    _BODY_TEXT_LIMIT characters to the payload list.

    Args:
        page:    An active Playwright Page instance.
        domain:  The normalized domain string (e.g., "acme.com").
        payload: The mutable list accumulating all harvested text.
    """
    url: str = f"https://{domain}"
    add_log(f"[HARVEST] Phase B: Crawling landing page `{url}`")

    try:
        await page.goto(
            url,
            timeout=_NAV_TIMEOUT_MS,
            wait_until="domcontentloaded",
        )

        body_element = await page.query_selector("body")

        if body_element is None:
            add_log(
                f"[HARVEST] Phase B WARNING: No <body> element found "
                f"on `{url}`. Skipping."
            )
            return

        raw_text:   str = await body_element.inner_text()
        clean_text: str = _clean_body_text(raw_text)
        excerpt:    str = clean_text[:_BODY_TEXT_LIMIT]

        if excerpt:
            payload.append(
                f"\n--- [DIRECT PAGE COPY: {url}] ---\n{excerpt}"
            )
            add_log(
                f"[HARVEST] Phase B complete. "
                f"Captured {len(excerpt)} characters from `{url}`."
            )
        else:
            add_log(
                f"[HARVEST] Phase B: Body text was empty after "
                f"normalization for `{url}`."
            )

    except Exception as exc:
        add_log(
            f"[HARVEST] Phase B WARNING: Landing page crawl failed "
            f"for `{url}`. Reason: {exc}"
        )


# =============================================================================
# Primary Entry Point
# =============================================================================

async def harvest_company_data(company_target: str) -> str:
    """
    Spin up a sandboxed Chromium instance and harvest text for a company.

    Orchestrates the full two-phase scraping pipeline against a single
    company target. Stealth patches are applied to the page before any
    navigation to suppress automation fingerprints at the JavaScript layer.

    The browser is launched headless with anti-automation Chromium flags
    and, when available, the uBlock Origin extension. A persistent browser
    context emulates a real Windows Chrome session via user-agent, viewport,
    and locale configuration.

    Failure contract:
        Individual phase failures are caught and logged without aborting
        the pipeline. The browser is unconditionally closed in a finally
        block. The function always returns a string -- empty if all phases
        fail, partial if one phase succeeds.

    Args:
        company_target: Raw company name or domain string. Whitespace and
                        case are normalized internally.

    Returns:
        A single concatenated string containing all successfully harvested
        text blocks, separated by labeled section banners.
    """
    domain:  str        = _normalize_domain(company_target)
    payload: list[str]  = []

    add_log(
        f"[HARVEST] Initiating browser engine for target: `{domain}`"
    )

    chromium_args: list[str] = _build_chromium_args()

    playwright_instance: Playwright
    browser:             Browser
    context:             BrowserContext
    page:                Page

    try:
        async with async_playwright() as playwright_instance:
            # ------------------------------------------------------------------
            # Browser launch
            # headless=True suppresses the GUI window; the Chromium args
            # strip automation markers that headless mode would otherwise
            # expose to bot-detection scripts on target pages.
            # ------------------------------------------------------------------
            browser = await playwright_instance.chromium.launch(
                headless=True,
                args=chromium_args,
            )

            try:
                # --------------------------------------------------------------
                # Browser context
                # A fresh context is equivalent to a new incognito profile:
                # no cookies, no cache, no stored credentials from prior runs.
                # The emulated user-agent, viewport, and locale must be set
                # here at the context level to be inherited by every page.
                # --------------------------------------------------------------
                context = await browser.new_context(
                    user_agent=_USER_AGENT,
                    viewport=ViewportSize(
                        width=_VIEWPORT_WIDTH,
                        height=_VIEWPORT_HEIGHT,
                    ),
                    locale=_LOCALE,
                )

                page = await context.new_page()

                # Enforce default action timeout limits across all locator events [2]
                page.set_default_timeout(_NAV_TIMEOUT_MS)

                # --------------------------------------------------------------
                # Stealth patch
                # Stealth().apply_stealth_async() overwrites navigator.webdriver,
                # plugin arrays, language lists, and other JS properties that
                # headless Chromium exposes and that anti-bot scripts probe.
                # Must be called after page creation, before any navigation.
                # --------------------------------------------------------------
                await Stealth().apply_stealth_async(page)

                await _phase_a_duckduckgo(page, domain, payload)
                await _phase_b_landing_page(page, domain, payload)

            finally:
                # Unconditional browser teardown. Ensures no orphaned
                # Chromium child process lingers in system memory even if
                # an unhandled exception propagates from either phase.
                await browser.close()
                add_log("[HARVEST] Browser engine closed cleanly.")

    except Exception as exc:
        add_log(
            f"[HARVEST] CRITICAL: Browser session failed to initialize "
            f"for `{domain}`. Reason: {exc}"
        )

    result: str = "\n".join(payload)

    if result:
        add_log(
            f"[HARVEST] Pipeline complete for `{domain}`. "
            f"Total payload: {len(result)} characters."
        )
    else:
        add_log(
            f"[HARVEST] Pipeline complete for `{domain}`. "
            "No text was harvested from any phase."
        )

    return result