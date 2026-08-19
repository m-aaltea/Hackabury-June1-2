import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlparse

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


def _to_hex(rgb: tuple) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _find_logo(soup, base_url: str) -> str | None:
    def rel_list(tag):
        r = tag.get("rel") or []
        return r.split() if isinstance(r, str) else r

    # 1. apple-touch-icon — high-res square, best for a pass logo
    for tag in soup.find_all("link"):
        if any("apple-touch-icon" in r for r in rel_list(tag)):
            href = tag.get("href", "").strip()
            if href:
                return urljoin(base_url, href)

    # 2. largest icon by sizes attribute (prefer 192x192, 96x96 etc over 16x16)
    best_href, best_size = None, 0
    for tag in soup.find_all("link"):
        if not any("icon" in r for r in rel_list(tag)):
            continue
        href = tag.get("href", "").strip()
        if not href:
            continue
        try:
            w = int(tag.get("sizes", "0x0").split("x")[0])
        except Exception:
            w = 1
        if w > best_size:
            best_size, best_href = w, href
    if best_href:
        return urljoin(base_url, best_href)

    # 3. any icon link
    for tag in soup.find_all("link"):
        if any("icon" in r for r in rel_list(tag)):
            href = tag.get("href", "").strip()
            if href:
                return urljoin(base_url, href)

    # 4. og:image (social share image — not ideal but better than nothing)
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        return og["content"].strip()

    return None


def _block_reason(resp, html: str) -> str | None:
    if resp.status_code == 429:
        return "rate_limited"

    h = {k.lower(): v for k, v in resp.headers.items()}
    low = html.lower()

    # Cloudflare — cf-ray header is definitive
    if "cf-ray" in h or "cloudflare" in h.get("server", "").lower():
        if any(s in low for s in ["just a moment", "checking your browser", "enable javascript and cookies"]):
            return "cloudflare"

    # Imperva / Incapsula
    if "x-iinfo" in h:
        return "bot_wall"
    if any(s in low for s in ["pardon our interruption", "isimpervaspasupport", "_imperva_"]):
        return "bot_wall"

    # Generic bot walls (DataDome, PerimeterX, etc.)
    if any(s in low for s in ["robot or human", "automated access", "access denied", "security check"]):
        return "bot_wall"

    # Captcha
    if any(s in low for s in ["recaptcha", "hcaptcha", "/captcha"]):
        return "captcha"

    # Empty / JS-only SPA
    if len(html.strip()) < 1000:
        return "empty_page"

    return None


async def _validate_public_url(url: str) -> None:
    """Reject non-HTTP and private-network targets before making a request."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("URL must start with http:// or https://")
    if parsed.username or parsed.password:
        raise ValueError("URLs containing credentials are not supported")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("URL contains an invalid port") from exc
    if port not in {None, 80, 443}:
        raise ValueError("Only standard HTTP and HTTPS ports are supported")

    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo,
            parsed.hostname,
            port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ValueError("Website hostname could not be resolved") from exc

    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ValueError("Private or local network URLs are not allowed")


async def _get_with_safe_redirects(
    client,
    url: str,
    *,
    max_bytes: int,
):
    current_url = url
    for _ in range(6):
        await _validate_public_url(current_url)
        request = client.build_request(
            "GET",
            current_url,
            headers=_HEADERS,
        )
        response = await client.send(request, stream=True)
        if response.is_redirect:
            location = response.headers.get("location")
            if location:
                await response.aclose()
                current_url = urljoin(str(response.url), location)
                continue

        content_length = response.headers.get("content-length")
        if content_length:
            try:
                declared_size = int(content_length)
            except ValueError:
                declared_size = None
            if declared_size is not None and declared_size > max_bytes:
                await response.aclose()
                raise ValueError("Remote response is too large")

        chunks = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > max_bytes:
                await response.aclose()
                raise ValueError("Remote response is too large")
            chunks.append(chunk)
        response._content = b"".join(chunks)
        await response.aclose()
        return response
    raise ValueError("Website redirected too many times")


async def scrape_page(url: str) -> dict:
    import httpx
    from bs4 import BeautifulSoup
    from colorthief import ColorThief
    from io import BytesIO

    domain = urlparse(url).netloc.replace("www.", "")

    async with httpx.AsyncClient(timeout=8) as client:
        resp = await _get_with_safe_redirects(client, url, max_bytes=2_000_000)

        if resp.status_code == 403:
            return {
                "title": domain,
                "description": "",
                "logo_url": None,
                "theme_color": None,
                "body_text": f"Brand: {domain}. Site blocked scraping — use your knowledge of this brand to generate realistic pass fields.",
                "image_colors": [],
                "blocked": True,
                "block_reason": "forbidden",
            }

        resp.raise_for_status()

    html = resp.text
    reason = _block_reason(resp, html)

    soup = BeautifulSoup(html, "html.parser")

    def meta(prop=None, name=None):
        tag = soup.find("meta", property=prop) if prop else soup.find("meta", attrs={"name": name})
        return (tag.get("content") or "").strip() if tag else ""

    title = meta(prop="og:title") or ((soup.title.string or "").strip() if soup.title else domain)
    description = meta(prop="og:description") or meta(name="description")
    theme_color = meta(name="theme-color") or None
    logo_url = _find_logo(soup, url)

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    body_text = " ".join(soup.get_text(" ", strip=True).split())[:800]

    if reason:
        return {
            "title": title or domain,
            "description": description,
            "logo_url": None,
            "theme_color": theme_color,
            "body_text": f"Brand: {domain}. Site uses bot protection — use your knowledge of this brand to generate realistic pass fields.",
            "image_colors": [],
            "blocked": True,
            "block_reason": reason,
        }

    image_colors: list[str] = []
    if logo_url:
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                img_resp = await _get_with_safe_redirects(
                    client,
                    logo_url,
                    max_bytes=200_000,
                )
            ct = ColorThief(BytesIO(img_resp.content))
            palette = ct.get_palette(color_count=3, quality=1)
            image_colors = [_to_hex(c) for c in palette]
        except Exception:
            pass

    return {
        "title": title,
        "description": description,
        "logo_url": logo_url,
        "theme_color": theme_color,
        "body_text": body_text,
        "image_colors": image_colors,
    }
