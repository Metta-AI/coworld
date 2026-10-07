"""Contributor-owned chat endpoints, registered with a policy's encrypted secrets."""

import hashlib
import ipaddress
import json
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

EXTERNAL_LLM_SECRET_KEY = "COWORLD_LLM_EXTERNAL_ROUTE"


class ExternalLlmRoute(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    base_url: str
    model: str = Field(min_length=1, max_length=256)
    api_key: SecretStr = SecretStr("")
    timeout_seconds: float = Field(default=60, gt=0, le=600)

    @model_validator(mode="after")
    def validate_endpoint(self) -> "ExternalLlmRoute":
        url = urlsplit(self.base_url)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.port not in (None, 443)
            or url.hostname.endswith(".")
            or "." not in url.hostname
        ):
            raise ValueError("External LLM base URL must use a public HTTPS hostname on port 443 without credentials")
        # Hostnames, rather than IP literals, allow the relay to enforce TLS SNI.
        if all(part.isdecimal() for part in url.hostname.split(".")) or ":" in url.hostname:
            raise ValueError("External LLM endpoints require a DNS hostname")
        return self

    @property
    def model_id(self) -> str:
        identity = json.dumps([self.base_url.rstrip("/"), self.model], separators=(",", ":"))
        return f"self-hosted/external-{hashlib.sha256(identity.encode()).hexdigest()}"

    def secret_json(self) -> str:
        return json.dumps(self.model_dump(mode="json") | {"api_key": self.api_key.get_secret_value()})


def public_endpoint_addresses(addresses: list[str]) -> bool:
    """Reject mixed public/private DNS answers, including IPv4-mapped IPv6."""
    ips = [ipaddress.ip_address(address) for address in addresses]
    return bool(ips) and all(
        (ip.ipv4_mapped if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped else ip).is_global for ip in ips
    )
