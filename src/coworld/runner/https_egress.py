"""Exact public HTTPS destinations registered with a player's encrypted environment."""

import ipaddress
import re
import socket

from pydantic import Field, RootModel, field_validator

HTTPS_HOSTS_SECRET_KEY = "COWORLD_HTTPS_HOSTS"


class HttpsHosts(RootModel[list[str]]):
    root: list[str] = Field(max_length=32)

    @field_validator("root")
    @classmethod
    def validate_hosts(cls, hosts: list[str]) -> list[str]:
        for host in hosts:
            if (
                len(host) > 253
                or "." not in host
                or all(part.isdecimal() for part in host.split("."))
                or any(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part) is None for part in host.split("."))
            ):
                raise ValueError("HTTPS destinations must be exact lowercase DNS hostnames, without URLs or wildcards")
        return sorted(set(hosts))

    def require_public_dns(self) -> None:
        for host in self.root:
            addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            if not public_endpoint_addresses([str(address[4][0]) for address in addresses]):
                raise ValueError("HTTPS destination DNS must resolve exclusively to public addresses")


def public_endpoint_addresses(addresses: list[str]) -> bool:
    """Reject mixed public/private DNS answers, including IPv4-mapped IPv6."""
    ips = [ipaddress.ip_address(address) for address in addresses]
    return bool(ips) and all(
        (ip.ipv4_mapped if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped else ip).is_global for ip in ips
    )
