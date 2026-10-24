"""Task network policy, installed in the task network namespace by a trusted guard.

Only this container has NET_ADMIN. The task has no network-administration capabilities or shared PID
namespace. Replacing the entire filter table also cuts established connections;
there is deliberately no established-connection exception in OUTPUT.
"""

import argparse
import subprocess
from typing import Literal

PRIVATE_IPV4 = (
    "0.0.0.0/8",
    "10.0.0.0/8",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.0.0.0/24",
    "192.168.0.0/16",
    "198.18.0.0/15",
    "224.0.0.0/4",
    "240.0.0.0/4",
)


def apply_network(mode: Literal["public", "no-network"]) -> None:
    # External IPv6 is unsupported. Remove its configured addresses so libc's
    # AI_ADDRCONFIG does not select IPv6 for IPv4-only localhost services.
    # Keep host-scope ::1 available for explicit IPv6 loopback traffic.
    for scope in ("global", "link"):
        subprocess.run(["ip", "-6", "address", "flush", "scope", scope], check=True, timeout=10)
    rules = [
        "*filter",
        ":INPUT DROP [0:0]",
        ":FORWARD DROP [0:0]",
        ":OUTPUT DROP [0:0]",
        "-A INPUT -i lo -j ACCEPT",
        "-A OUTPUT -o lo -j ACCEPT",
    ]
    if mode == "public":
        rules.append("-A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT")
        # Use public resolvers: no exception for cluster DNS or metadata networks.
        for resolver in ("1.1.1.1", "8.8.8.8"):
            rules.append(f"-A OUTPUT -d {resolver} -p udp --dport 53 -j ACCEPT")
        for cidr in PRIVATE_IPV4:
            rules.append(f"-A OUTPUT -d {cidr} -j DROP")
        rules.append("-A OUTPUT -j ACCEPT")
    rules.append("COMMIT")
    # Block IPv6 in both phases; do not leave an alternate route around IPv4.
    subprocess.run(
        ["ip6tables-restore", "--wait", "5"],
        input=(
            "*filter\n:INPUT DROP [0:0]\n:FORWARD DROP [0:0]\n:OUTPUT DROP [0:0]\n"
            "-A INPUT -i lo -j ACCEPT\n-A OUTPUT -o lo -j ACCEPT\nCOMMIT\n"
        ),
        text=True,
        check=True,
        timeout=10,
    )
    subprocess.run(
        ["iptables-restore", "--wait", "5"], input="\n".join(rules) + "\n", text=True, check=True, timeout=10
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("public", "no-network"))
    apply_network(parser.parse_args().mode)
