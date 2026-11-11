import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

import pytest
from workforce_worker.browser import (
    BlockedURL,
    BrowserError,
    BrowserService,
    DomainPolicy,
    check_url,
)
from workforce_worker.browser import url_guard

PAGES = {
    "/": """<html><head><title>Fitness Creators Mumbai</title></head><body>
        <nav><a href="/about">About us</a> <a href="/list">Creator list</a></nav>
        <main><h1>Top creators</h1><p>Mumbai has a thriving fitness creator scene.</p>
        <p>"""
    + ("Long text. " * 60)
    + """</p></main>
        <img src="http://169.254.169.254/latest/meta-data/">
        <a href="http://10.0.0.1/admin">Admin panel</a>
        <a href="/go-internal">Sneaky redirect</a>
        <script>window.open('/about')</script>
        </body></html>""",
    "/about": "<html><head><title>About</title></head><body><p>We rank creators.</p></body></html>",
    "/list": """<html><head><title>List</title></head><body><ul>
        <li>@fitwithriya - 120k followers</li><li>@mumbaimuscle - 45k followers</li>
        </ul><div style="height:3000px"></div><div id="more"></div>
        <script>window.addEventListener('scroll', () => {
          document.getElementById('more').innerText = '@lazyloaded - 30k followers';
        });</script></body></html>""",
    "/form": """<html><head><title>Register</title></head><body>
        <form action="/submit" method="post">
          <label for="name">Full name</label><input id="name" name="name">
          <label for="email">Email</label><input id="email" name="email" type="email">
          <label for="city">City</label>
          <select id="city" name="city"><option>Delhi</option><option>Mumbai</option></select>
          <label><input type="checkbox" name="newsletter" id="newsletter"> Newsletter</label>
          <button type="submit">Register</button>
        </form></body></html>""",
    "/login": """<html><body><form><label for="u">Username</label><input id="u" name="u">
        <label for="p">Password</label><input id="p" name="p" type="password"></form>
        </body></html>""",
}


class Handler(BaseHTTPRequestHandler):
    submissions: list[dict] = []

    def log_message(self, *args):
        pass

    def _send(self, status: int, body: str, headers: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body.encode())

    def do_GET(self):
        if self.path == "/go-internal":
            port = self.server.server_address[1]
            self._send(302, "", {"Location": f"http://localhost:{port}/about"})
        elif self.path in PAGES:
            self._send(200, PAGES[self.path])
        else:
            self._send(404, "not found")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        data = parse_qs(self.rfile.read(length).decode())
        Handler.submissions.append({k: v[0] for k, v in data.items()})
        self._send(200, "<html><body><h1>Thanks, you are registered!</h1></body></html>")


@pytest.fixture(scope="module")
def site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def run(coro):
    return asyncio.run(coro)


LOCAL = DomainPolicy(allow_private_hosts=frozenset({"127.0.0.1"}))


# --- URL guard ----------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "javascript:alert(1)",
        "ftp://example.com/x",
        "http://localhost:8000/",
        "http://127.0.0.1/",
        "http://0.0.0.0/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.1.2.3/",
        "http://192.168.1.1/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://user:pass@example.com/",
        "http://metadata.google.internal/",
    ],
)
def test_unsafe_urls_blocked(url):
    with pytest.raises(BlockedURL):
        check_url(url)


def test_public_url_allowed_and_dns_checked(monkeypatch):
    monkeypatch.setattr(url_guard, "_resolve", lambda host: ("93.184.215.14",))
    assert check_url("https://example.com/page?q=1") == "https://example.com/page?q=1"
    monkeypatch.setattr(url_guard, "_resolve", lambda host: ("10.0.0.5",))
    with pytest.raises(BlockedURL, match="private"):
        check_url("https://evil-rebind.example/")


def test_blocked_domains(monkeypatch):
    monkeypatch.setattr(url_guard, "_resolve", lambda host: ("93.184.215.14",))
    policy = DomainPolicy(blocked_domains=frozenset({"gambling.example"}))
    with pytest.raises(BlockedURL, match="blocked list"):
        check_url("https://www.gambling.example/", policy)


# --- reading pages --------------------------------------------------------------


def test_read_page_text_links_and_screenshot(site):
    async def go():
        async with BrowserService(LOCAL) as b:
            return await b.read_page(site + "/", screenshot=True)

    page = run(go())
    assert page.title == "Fitness Creators Mumbai"
    assert "thriving fitness creator scene" in page.text
    assert ("About us", site + "/about") in page.links
    assert page.screenshot_png and page.screenshot_png[:4] == b"\x89PNG"
    assert page.blocked_requests >= 1  # the metadata-IP image never loaded


def test_follow_links_and_lazy_content(site):
    async def go():
        async with BrowserService(LOCAL) as b:
            return await b.read_page(site + "/", follow_links=["Creator list"])

    page = run(go())
    assert page.final_url == site + "/list"
    assert "@fitwithriya" in page.text
    assert "@lazyloaded" in page.text  # appeared only after scrolling


def test_cannot_follow_links_into_private_network(site):
    async def go():
        async with BrowserService(LOCAL) as b:
            await b.read_page(site + "/", follow_links=["Admin panel"])

    with pytest.raises(BlockedURL):
        run(go())


def test_redirect_to_private_host_is_blocked(site):
    async def go():
        async with BrowserService(LOCAL) as b:
            await b.read_page(site + "/go-internal")

    with pytest.raises((BlockedURL, BrowserError)):
        run(go())


# --- forms --------------------------------------------------------------------


FIELDS = {
    "Full name": "Asha Rao",
    "Email": "asha@example.com",
    "City": "Mumbai",
    "Newsletter": "yes",
}


def test_fill_form_preview_does_not_submit(site):
    Handler.submissions.clear()

    async def go():
        async with BrowserService(LOCAL) as b:
            return await b.fill_form(site + "/form", FIELDS)

    result = run(go())
    assert result.filled == list(FIELDS) and not result.missing
    assert not result.submitted and Handler.submissions == []
    assert result.screenshot_png[:4] == b"\x89PNG"


def test_submit_requires_site_to_be_allowed(site):
    async def go():
        async with BrowserService(LOCAL) as b:
            await b.fill_form(site + "/form", FIELDS, submit=True)

    with pytest.raises(BlockedURL, match="not enabled"):
        run(go())


def test_submit_on_allowed_site(site):
    Handler.submissions.clear()
    policy = DomainPolicy(
        allow_private_hosts=frozenset({"127.0.0.1"}),
        form_submit_domains=frozenset({"127.0.0.1"}),
    )

    async def go():
        async with BrowserService(policy) as b:
            return await b.fill_form(site + "/form", FIELDS, submit=True)

    result = run(go())
    assert result.submitted
    assert "registered" in result.page_text_after
    assert Handler.submissions == [
        {"name": "Asha Rao", "email": "asha@example.com", "city": "Mumbai", "newsletter": "on"}
    ]


def test_refuses_password_fields(site):
    async def go():
        async with BrowserService(LOCAL) as b:
            await b.fill_form(site + "/login", {"Username": "asha", "Password": "x"})

    with pytest.raises(BrowserError, match="never entered by agents"):
        run(go())
