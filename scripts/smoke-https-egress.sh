#!/usr/bin/env bash
# Complete HTTPS transport: unprivileged client -> pod proxy -> mTLS relay -> public origin.
# Usage: bash scripts/smoke-https-egress.sh <coworld-runner-image> <egress-relay-image> <parley-player-image>
set -euo pipefail

runner_image=$1
relay_image=$2
client_image=$3
network=coworld-https-smoke-$$
relay=$network-relay
proxy=$network-proxy
other_proxy=$network-other
tls_dir=$(mktemp -d)

cleanup() {
  docker rm --force "$proxy" "$other_proxy" "$relay" > /dev/null 2>&1 || true
  docker network rm "$network" > /dev/null 2>&1 || true
  rm -rf "$tls_dir"
}
trap cleanup EXIT

openssl req -x509 -newkey rsa:2048 -nodes -keyout "$tls_dir/ca.key" -out "$tls_dir/ca.crt" \
  -subj '/CN=HTTPS smoke CA' -days 1 > /dev/null 2>&1
for identity in server client; do
  openssl req -newkey rsa:2048 -nodes -keyout "$tls_dir/$identity.key" -out "$tls_dir/$identity.csr" \
    -subj "/CN=$identity" > /dev/null 2>&1
  if [[ $identity == server ]]; then
    printf 'subjectAltName=DNS:relay\nextendedKeyUsage=serverAuth\n' > "$tls_dir/$identity.ext"
  else
    printf 'extendedKeyUsage=clientAuth\n' > "$tls_dir/$identity.ext"
  fi
  openssl x509 -req -in "$tls_dir/$identity.csr" -CA "$tls_dir/ca.crt" -CAkey "$tls_dir/ca.key" \
    -CAcreateserial -out "$tls_dir/$identity.crt" -days 1 -extfile "$tls_dir/$identity.ext" > /dev/null 2>&1
done
chmod 755 "$tls_dir"
chmod 644 "$tls_dir"/*.crt "$tls_dir"/client.key "$tls_dir"/server.key

network_options=()
if [[ -n ${COWORLD_SMOKE_SUBNET:-} ]]; then
  network_options=(--subnet "$COWORLD_SMOKE_SUBNET")
fi
docker network create "${network_options[@]}" "$network" > /dev/null
docker run --detach --name "$relay" --network "$network" --network-alias relay \
  --add-host private.example:127.0.0.1 \
  --volume "$tls_dir:/tls:ro" \
  --env EGRESS_RELAY_TLS_CERT_FILE=/tls/server.crt \
  --env EGRESS_RELAY_TLS_KEY_FILE=/tls/server.key \
  --env EGRESS_RELAY_TLS_CLIENT_CA_FILE=/tls/ca.crt \
  --env EGRESS_RELAY_ALLOWED_CLIENT_COMMON_NAMES=client \
  --env EGRESS_RELAY_ALLOWED_UPSTREAMS=openrouter.ai:443 \
  --env EGRESS_RELAY_ALLOW_PUBLIC_EXTERNAL_UPSTREAMS=true \
  "$relay_image" > /dev/null

start_proxy() {
  docker run --detach --name "$1" --network "$network" \
    --volume "$tls_dir/ca.crt:/var/run/secrets/egress-relay/ca.crt:ro" \
    --volume "$tls_dir/client.crt:/var/run/secrets/egress-relay/tls.crt:ro" \
    --volume "$tls_dir/client.key:/var/run/secrets/egress-relay/tls.key:ro" \
    --env COWORLD_GAME_EGRESS_UPSTREAM_RELAY_URL=https://relay:3128 \
    --env COWORLD_GAME_EGRESS_ALLOWED_UPSTREAMS= \
    --env "COWORLD_HTTPS_EXTERNAL_UPSTREAMS=$2" \
    --health-cmd "python -c \"import socket; socket.create_connection(('127.0.0.1',3129),2).close()\"" \
    --health-interval 1s --health-timeout 3s --health-retries 20 \
    --entrypoint python "$runner_image" -m coworld.runner.game_egress_proxy > /dev/null
  for _ in {1..30}; do
    if [[ $(docker inspect --format '{{.State.Health.Status}}' "$1") == healthy ]]; then
      return
    fi
    sleep 1
  done
  docker logs "$1"
  return 1
}
start_proxy "$proxy" 'example.com:443,private.example:443'
start_proxy "$other_proxy" 'www.python.org:443'

# The application shares only the network namespace. It has no relay certificate mount.
docker run --rm --user 1000:1000 --cap-drop ALL --security-opt no-new-privileges --network "container:$proxy" \
  --env HTTPS_PROXY=http://127.0.0.1:3129 --env NO_PROXY= \
  --entrypoint python "$client_image" -c '
from pathlib import Path
import httpx
assert not Path("/var/run/secrets/egress-relay/tls.key").exists()
response = httpx.get("https://example.com/", timeout=30)
response.raise_for_status()
assert "Example Domain" in response.text
print("Declared public HTTPS succeeds without exposing relay credentials")
'

for instance in "$proxy" "$other_proxy"; do
  docker run --rm -i --user 1000:1000 --cap-drop ALL --security-opt no-new-privileges \
    --network "container:$instance" --entrypoint python "$client_image" - "$instance" "$proxy" << 'PY'
import socket
import sys

targets = ["undeclared.example:443", "169.254.169.254:443", "example.com:80"]
targets += ["private.example:443"] if sys.argv[1] == sys.argv[2] else ["example.com:443"]
for target in targets:
    with socket.create_connection(("127.0.0.1", 3129), timeout=10) as connection:
        # Spoofing the relay marker must never expand this player's declared destinations.
        connection.sendall(
            f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\nProxy-Authorization: Coworld-External\r\n\r\n".encode()
        )
        response = connection.recv(4096)
        assert response.startswith(b"HTTP/1.1 403 "), (target, response)
print("Undeclared hosts, private DNS, ports, and cross-player destinations are denied")
PY
done
