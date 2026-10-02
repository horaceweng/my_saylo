"""The one way the server downloads something from an address a user typed (articles, RSS, podcast audio, EPUBs).

Without a guard, "paste a link" lets any logged-in user make this Mac fetch http://127.0.0.1:11434 (Ollama),
the router, or another Tailscale machine and read the answer back (SSRF). Each request therefore:
  - only speaks http/https on ports 80/443, with no user:password in the link;
  - resolves the name itself and refuses it if ANY address is not a plain public one;
  - connects to the address it vetted (Host header and TLS name stay the real ones), so a name that
    answers differently the second time (DNS rebinding) cannot send the connection somewhere else;
  - follows redirects by hand, running every hop through the same checks;
  - stops reading when the body gets larger than the caller's limit or takes too long.

Residual risk: with a client passed in by a caller (tests only) the connection is not pinned. Names that
resolve to a public address but are reachable only through some proxy are not handled; `trust_env` is off so
proxy variables in the environment are ignored."""

import ipaddress
import re
import socket
import time
from contextlib import contextmanager
from typing import Iterator
from urllib.parse import urljoin, urlsplit

import httpx

ALLOWED_PORTS = (80, 443)
MAX_REDIRECTS = 5
_REDIRECT = (301, 302, 303, 307, 308)
_BAD_SUFFIXES = (".local", ".localhost", ".localdomain", ".internal", ".ts.net", ".lan", ".home", ".home.arpa", ".corp", ".intranet")


_NUMBERISH = re.compile(r"^(0x[0-9a-f]*|\d+)$")


class FetchError(ValueError):
    """The link was refused or the download did not work; the message says why (shown to the user)."""


def _blocked(ip: ipaddress._BaseAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address):
        # Addresses that carry an IPv4 address inside must be judged by that address.
        for inner in (ip.ipv4_mapped, ip.sixtofour, ip.teredo[1] if ip.teredo else None):
            if inner is not None and _blocked(inner):
                return True
        if ip in ipaddress.ip_network("64:ff9b::/96"):
            return _blocked(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    return ip.is_multicast or not ip.is_global  # private, loopback, link-local, CGNAT (Tailscale), reserved, unspecified


def resolve(host: str, port: int) -> list[str]:
    """Every address the name points to (a seam for tests)."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise FetchError("找不到這個網址的主機") from e
    return list(dict.fromkeys(info[4][0].split("%")[0] for info in infos))


def vet(url: str) -> tuple[httpx.URL, str, int, list[str]]:
    """Check one link. Returns (parsed url, host, port, the public addresses to connect to) or raises FetchError."""
    try:
        parts = urlsplit(url.strip())
        host, port = (parts.hostname or "").lower().rstrip("."), parts.port
    except ValueError as e:
        raise FetchError("網址格式不正確") from e
    if parts.scheme not in ("http", "https") or not host:
        raise FetchError("請貼上以 http:// 或 https:// 開頭的完整網址")
    if parts.username is not None or parts.password is not None:
        raise FetchError("網址不能包含帳號密碼")
    port = port or (443 if parts.scheme == "https" else 80)
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
        # Single names (resolved through search domains or mDNS) and numbers written in odd ways (0x7f.1) are not websites.
        if host == "localhost" or host.endswith(_BAD_SUFFIXES) or "." not in host or all(_NUMBERISH.match(p) for p in host.split(".")):
            raise FetchError("不能連到這台電腦或內部網路的位址") from None
    addresses = [str(literal)] if literal else resolve(host, port)
    if not addresses:
        raise FetchError("找不到這個網址的主機")
    for address in addresses:
        if _blocked(ipaddress.ip_address(address)):
            raise FetchError("不能連到這台電腦或內部網路的位址")
    if port not in ALLOWED_PORTS:
        raise FetchError("只能連到一般的網站（80／443 連接埠）")
    return httpx.URL(parts.geturl()), host, port, addresses


def new_client(timeout: httpx.Timeout, headers: dict | None = None) -> httpx.Client:
    return httpx.Client(timeout=timeout, headers=headers, follow_redirects=False, trust_env=False)


@contextmanager
def open_stream(url: str, *, timeout: httpx.Timeout, headers: dict | None = None, client: httpx.Client | None = None) -> Iterator[httpx.Response]:
    """GET `url` and yield the final (non-redirect) streaming response. Redirects are followed here, each one checked."""
    own = client is None
    http = client or new_client(timeout, headers)
    try:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            parsed, host, port, addresses = vet(current)
            last_error: Exception | None = None
            for address in addresses:
                if own:  # pinned: connect to the vetted address, keep the real name for Host and TLS
                    target = parsed.copy_with(host=address)
                    request = http.build_request("GET", target, headers={"Host": parsed.netloc.decode()}, extensions={"sni_hostname": host})
                else:  # a caller-supplied client (tests with a mock transport): no pinning
                    request = http.build_request("GET", parsed)
                try:
                    response = http.send(request, stream=True)
                except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                    last_error = e
                    continue
                break
            else:
                raise last_error or FetchError("連不上這個網址")
            if response.status_code in _REDIRECT and (location := response.headers.get("location")):
                response.close()
                current = urljoin(current, location)
                continue
            try:
                yield response
            finally:
                response.close()
            return
        raise FetchError("這個網址轉址太多次")
    finally:
        if own:
            http.close()


def read_limited(response: httpx.Response, max_bytes: int, too_big: str, deadline: float | None) -> bytes:
    declared = response.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise FetchError(too_big)
    body = bytearray()
    for chunk in response.iter_bytes(1 << 16):
        body += chunk
        if len(body) > max_bytes:
            raise FetchError(too_big)
        if deadline is not None and time.monotonic() > deadline:
            raise FetchError("下載太慢，已中止")
    return bytes(body)


def fetch(url: str, *, max_bytes: int, too_big: str = "這個網址的內容太大", timeout: httpx.Timeout | None = None,
          headers: dict | None = None, client: httpx.Client | None = None, max_seconds: float = 60.0) -> httpx.Response:
    """The whole answer (up to `max_bytes`) as an ordinary httpx.Response; status codes are for the caller to judge."""
    deadline = time.monotonic() + max_seconds
    with open_stream(url, timeout=timeout or httpx.Timeout(30.0, connect=10.0), headers=headers, client=client) as response:
        body = read_limited(response, max_bytes, too_big, deadline)
        kept = {k: v for k, v in response.headers.items() if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")}
        return httpx.Response(response.status_code, headers=kept, content=body, request=response.request)
