from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

Resolver = Callable[..., list[tuple[Any, ...]]]
METADATA_HOSTS = {
    "169.254.169.254",
    "metadata.google.internal",
    "metadata.google.com",
    "instance-data",
    "instance-data.ec2.internal",
}


def _public_ip(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_global
    except ValueError:
        return False


class URLValidator:
    """Validate public HTTPS targets, with cached runtime DNS checks."""

    def __init__(self, resolver: Resolver | None = None):
        self.resolver = resolver or socket.getaddrinfo
        self._cache: dict[str, tuple[str, ...] | ValueError] = {}

    def validate(self, value: object, *, resolve: bool = True, field: str = "URL") -> str:
        if not isinstance(value, str):
            raise ValueError(f"{field} must be a public HTTPS URL")
        try:
            parsed = urlsplit(value)
            host = parsed.hostname
            port = parsed.port or 443
        except ValueError as exc:
            raise ValueError(f"{field} must be a public HTTPS URL") from exc
        if parsed.scheme.lower() != "https" or not host or parsed.username is not None:
            raise ValueError(f"{field} must be a public HTTPS URL")
        lowered = host.rstrip(".").lower()
        if lowered == "localhost" or lowered.endswith(".localhost") or lowered in METADATA_HOSTS:
            raise ValueError(f"{field} must target a public host")
        try:
            literal = ipaddress.ip_address(lowered)
        except ValueError:
            literal = None
        if literal is not None and not literal.is_global:
            raise ValueError(f"{field} must target a public IP")
        if resolve and literal is None:
            cached = self._cache.get(lowered)
            if isinstance(cached, ValueError):
                raise ValueError(str(cached))
            if cached is None:
                try:
                    answers = self.resolver(lowered, port, type=socket.SOCK_STREAM)
                    addresses = tuple({str(answer[4][0]) for answer in answers})
                    if not addresses or any(not _public_ip(ip) for ip in addresses):
                        raise ValueError(f"{field} DNS must resolve only to public IPs")
                    self._cache[lowered] = addresses
                except (OSError, ValueError) as exc:
                    error = ValueError(str(exc))
                    self._cache[lowered] = error
                    raise error from exc
        return value


def validate_public_url(value: object, *, field: str = "URL") -> str:
    return URLValidator().validate(value, resolve=False, field=field)
