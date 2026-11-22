import asyncio
from typing import Literal
from urllib.parse import urljoin, urlsplit, urlunsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright
from pydantic import Field, model_validator

from .contracts import Contract
from .nodes import Export, Filename, Result, artifact, node, record_result
from .security import read_file, request_bytes

MAX_HTML = 512 * 1024
STATIC_POLICY = (
    '<!doctype html><meta http-equiv="Content-Security-Policy" content="'
    "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'\">"
)


class Browser(Contract):
    selector: str = Field(default="table", min_length=1, max_length=240)
    fixture: Literal["catalog", "catalog2"] = "catalog"
    url: str = Field(default="", max_length=2048)
    pages: int = Field(default=1, ge=1, le=5)
    next_selector: str = Field(default='a[rel="next"]', min_length=1, max_length=240)
    max_records: int = Field(default=100, ge=1, le=250)
    seconds: float = Field(default=6, ge=0.1, le=20)


async def load_page(ctx, address, seconds):
    if address in ("catalog", "catalog2"):
        data = read_file(ctx.fixtures, address + ".html")
        return data.decode(), address
    if not ctx.browser_hosts:
        raise ValueError("External browser URLs need an administrator-approved domain")
    data, media, final = await asyncio.to_thread(
        request_bytes, address, ctx.browser_hosts, timeout=seconds,
        accept="text/html, application/xhtml+xml", limit=MAX_HTML,
    )
    if media.split(";", 1)[0].strip().lower() not in {"text/html", "application/xhtml+xml"}:
        raise ValueError("Browser extraction requires an HTML response")
    return data.decode("utf-8", errors="replace"), final


async def next_page(page, address, selector):
    if address in ("catalog", "catalog2"):
        return "catalog2" if address == "catalog" else ""
    link = page.locator(selector).first
    href = await link.get_attribute("href") if await link.count() else ""
    if not href:
        return ""
    if len(href) > 2048:
        raise ValueError("Browser pagination URL exceeds its size limit")
    parts = urlsplit(urljoin(address, href))
    return urlunsplit(parts._replace(fragment=""))


async def browse(ctx, config, extract, *, first_page_only=False):
    address = config.url or ctx.first.get("browser_url") or config.fixture
    if not isinstance(address, str):
        raise ValueError("Browser URL must be text")
    # Validate the first resource before launching a browser. Chromium never fetches page resources.
    html, final = await load_page(ctx, address, config.seconds)
    results, seen = [], set()
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(channel=ctx.browser or None,
                                                        args=["--disable-background-networking"])
            try:
                session = await browser.new_context(
                    java_script_enabled=False, service_workers="block", offline=True, accept_downloads=False,
                    viewport={"width": 1200, "height": 900},
                )
                async def deny(route):
                    await route.abort()
                await session.route("**/*", deny)
                page = await session.new_page()
                page.set_default_timeout(config.seconds * 1000)
                count = 0
                for index in range(1 if first_page_only else config.pages):
                    if index:
                        html, final = await load_page(ctx, address, config.seconds)
                    if final in seen:
                        break
                    seen.add(final)
                    await page.set_content(STATIC_POLICY + html, wait_until="domcontentloaded")
                    selected = page.locator(config.selector)
                    if not await selected.count():
                        raise ValueError("Selector matched no elements in the approved fixture or page")
                    result = await extract(page, selected, config.max_records - count, final)
                    results.append(result)
                    count += len(result) if isinstance(result, list) else 0
                    if count >= config.max_records or index + 1 >= config.pages or first_page_only:
                        break
                    address = await next_page(page, final, config.next_selector)
                    if not address or address in seen:
                        break
            finally:
                await browser.close()
    except PlaywrightError:
        raise ValueError("Browser could not render the approved page or apply its selectors") from None
    return results


@node("browser_table", "Extract Browser Table", "Browser Automation", Browser, output_kind="records")
async def browser_table(ctx, config):
    """Extract bounded table records from fixtures or approved static HTTPS pages."""
    async def extract(_, selection, limit, __):
        table = selection.first
        labels = await table.locator("thead th").all_text_contents()
        if not labels:
            labels = await table.locator("th").all_text_contents()
        if (not labels or len(labels) > 64 or len(set(labels)) != len(labels)
                or any(not label.strip() for label in labels)):
            raise ValueError("Table must have at most 64 unique nonempty column labels")
        rows = table.locator("tbody tr").filter(has=table.page.locator("td"))
        result = []
        for index in range(min(await rows.count(), limit)):
            values = await rows.nth(index).locator("td").all_text_contents()
            if len(values) != len(labels):
                raise ValueError("Table cells do not match the header")
            result.append(dict(zip(labels, values, strict=True)))
        return result
    pages = await browse(ctx, config, extract)
    return record_result([row for page in pages for row in page], pages=len(pages))


@node("browser_text", "Extract Browser Text", "Browser Automation", Browser)
async def browser_text(ctx, config):
    """Read text from matching elements, with optional approved pagination."""
    async def extract(_, selection, limit, __):
        return [(await selection.nth(index).inner_text())[:4096]
                for index in range(min(await selection.count(), limit))]
    pages = await browse(ctx, config, extract)
    return Result({"text": "\n".join(text for page in pages for text in page)[:100_000], "pages": len(pages)})


@node("browser_links", "Extract Browser Links", "Browser Automation", Browser)
async def browser_links(ctx, config):
    """Read link labels and destinations without making requests to those destinations."""
    async def extract(_, selection, limit, address):
        links = selection.locator("a")
        result = []
        for index in range(min(await links.count(), limit)):
            link = links.nth(index)
            href = await link.get_attribute("href")
            if href and len(href) <= 2048 and urlsplit(href).scheme in ("", "http", "https"):
                result.append({"text": (await link.inner_text())[:512],
                               "href": urljoin(address, href) if address.startswith("https:") else href})
        return result
    pages = await browse(ctx, config, extract)
    return Result({"links": [link for page in pages for link in page], "pages": len(pages)})


class BrowserOpen(Browser):
    selector: str = "body"


@node("browser_open", "Open Browser Page", "Browser Automation", BrowserOpen)
async def browser_open(ctx, config):
    """Open approved static HTML and return the title and canonical retrieval URL."""
    async def extract(page, selection, _, address):
        return {"title": (await page.title())[:512], "text": (await selection.first.inner_text())[:4096],
                "browser_url": address if address.startswith("https:") else ""}
    pages = await browse(ctx, config, extract, first_page_only=True)
    return Result(pages[0])


class BrowserFields(Browser):
    fields: dict[str, str] = Field(default_factory=lambda: {"text": ""}, min_length=1, max_length=20)

    @model_validator(mode="after")
    def bounded_fields(self):
        if any(not key or len(key) > 60 or len(selector) > 240 for key, selector in self.fields.items()):
            raise ValueError("Element fields require bounded names and selectors")
        return self


@node("browser_elements", "Extract Browser Elements", "Browser Automation", BrowserFields, output_kind="records")
async def browser_elements(ctx, config):
    """Extract named text fields per matched row and emit records for export nodes."""
    async def extract(_, selection, limit, __):
        rows = []
        for index in range(min(await selection.count(), limit)):
            row, record = selection.nth(index), {}
            for key, selector in config.fields.items():
                field = row.locator(selector).first if selector else row
                record[key] = (await field.inner_text())[:1024] if await field.count() else None
            rows.append(record)
        return rows
    pages = await browse(ctx, config, extract)
    return record_result([row for page in pages for row in page], pages=len(pages))


class Screenshot(Browser, Export):
    filename: Filename = "capture"


@node("browser_capture", "Capture Browser Screenshot", "Browser Automation", Screenshot)
async def browser_capture(ctx, config):
    """Capture one viewport-bounded PNG for the first approved page and selector."""
    async def extract(page, selection, _, __):
        target = selection.first
        await target.scroll_into_view_if_needed()
        box = await target.bounding_box()
        if not box:
            raise ValueError("Screenshot target is not rendered")
        x, y = max(0, box["x"]), max(0, box["y"])
        width, height = min(1200, box["x"] + box["width"]) - x, min(900, box["y"] + box["height"]) - y
        if width < 1 or height < 1:
            raise ValueError("Screenshot target is outside the bounded viewport")
        return await page.screenshot(animations="disabled", clip={"x": x, "y": y, "width": width, "height": height})
    pages = await browse(ctx, config, extract, first_page_only=True)
    return artifact(config, "png", "image/png", pages[0])
