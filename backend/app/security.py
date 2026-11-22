import http.client
import ipaddress
import json
import re
import socket
import ssl
from pathlib import Path
from urllib.parse import urljoin, urlsplit

MAX_BODY = 1_048_576
MAX_FILE = 4 * 1024 * 1024
SENSITIVE = re.compile(
    r"(^|[-_])(password|passwd|secret|token|authorization|cookie|api[-_]?key)([s_-]|$)"
    r"|^(accessToken|refreshToken|apiKey|clientSecret|privateKey|setCookie)$", re.IGNORECASE
)
INLINE_SECRET = re.compile(
    r"(?i)(?:bearer\s+|(?:api[_ -]?key|access[_ -]?token|password|client[_ -]?secret)\s*[:=]\s*)"
    r"[\"']?[^\s,;\"']+|\bsk-[A-Za-z0-9_-]{12,}"
)


def redact(value, secrets=()):
    if isinstance(value, dict):
        return {key: "[redacted]" if SENSITIVE.search(key) else redact(item, secrets)
                for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]")
        return INLINE_SECRET.sub("[redacted]", value)
    return value


def json_size(value):
    try:
        return len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    except (ValueError, RecursionError) as exc:
        raise ValueError("Expected finite JSON within the depth limit") from exc


def safe_path(root: Path, filename: str):
    if (not isinstance(filename, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}", filename)
            or filename.endswith(".") or re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]",
                                                       filename.split(".")[0].upper())):
        raise ValueError("Use a plain file name inside the approved directory")
    root = root.resolve()
    target = root / filename
    if target.resolve() != target:
        raise ValueError("Linked files are unavailable")
    return target


def read_file(root, filename):
    with safe_path(root, filename).open("rb") as source:
        data = source.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise ValueError("File exceeds the 4 MiB limit")
    return data


def resolve_target(url, allowed):
    if any(ord(character) <= 32 or ord(character) == 127 for character in url):
        raise ValueError("URL contains disallowed characters")
    parts = urlsplit(url)
    host = parts.hostname
    if (parts.scheme != "https" or not host or host not in allowed or parts.username is not None
            or parts.port not in (None, 443) or parts.fragment or "\\" in url):
        raise ValueError("Destination is outside the approved HTTPS allowlist")
    addresses = {row[4][0] for row in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    if not addresses or any(not ipaddress.ip_address(ip).is_global
                            or ipaddress.ip_address(ip).is_multicast for ip in addresses):
        raise ValueError("Destination must resolve exclusively to public IP addresses")
    target = parts.path or "/"
    if parts.query:
        target += "?" + parts.query
    return host, min(addresses), target


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout):
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        raw = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def request_bytes(url, allowed, *, body=None, authorization=None, timeout=5,
                  accept="application/json", redirects=True, limit=MAX_BODY):
    method = "GET" if body is None else "POST"
    headers = {"Accept": accept, "Accept-Encoding": "identity"}
    if body is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(body, allow_nan=False).encode()
        if len(body) > MAX_BODY:
            raise ValueError("HTTP request exceeds the 1 MiB limit")
    if authorization:
        headers["Authorization"] = authorization
    for hop in range(4):
        host, address, target = resolve_target(url, allowed)
        connection = PinnedHTTPS(host, address, timeout)
        try:
            connection.request(method, target, body=body, headers=headers)
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not redirects or method != "GET" or hop == 3 or not location:
                    raise ValueError("HTTP redirect is outside the allowed policy")
                url = urljoin(url, location)
                headers.pop("Authorization", None)
                continue
            if not 200 <= response.status < 300:
                raise RuntimeError(f"Remote service returned HTTP {response.status}")
            if response.getheader("Content-Encoding", "identity").lower() != "identity":
                raise ValueError("Encoded HTTP responses are unavailable")
            data = response.read(limit + 1)
            if len(data) > limit:
                raise ValueError("HTTP response exceeds its size limit")
            return data, response.getheader("Content-Type", ""), url
        finally:
            connection.close()
    raise ValueError("HTTP redirect limit reached")


def request_json(url, allowed, **kwargs):
    data, _, _ = request_bytes(url, allowed, **kwargs)
    return json.loads(data)
