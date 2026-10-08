"""HTTP client for trusted Coworld traffic through the selected egress relay."""

import os
import ssl

import httpx


def egress_relay_ssl_context(*, ca_file: str, cert_file: str, key_file: str) -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=ca_file)
    context.load_cert_chain(cert_file, key_file)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def relay_proxy(relay_url: str) -> httpx.Proxy:
    context = egress_relay_ssl_context(
        ca_file=os.environ["COWORLD_EGRESS_RELAY_CA_FILE"],
        cert_file=os.environ["COWORLD_EGRESS_RELAY_CLIENT_CERT_FILE"],
        key_file=os.environ["COWORLD_EGRESS_RELAY_CLIENT_KEY_FILE"],
    )
    return httpx.Proxy(relay_url, ssl_context=context)


def relay_http_client(relay_url: str) -> httpx.Client:
    return httpx.Client(proxy=relay_proxy(relay_url), timeout=60.0, follow_redirects=True)
