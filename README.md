![Release](https://img.shields.io/github/v/release/BrodjagaRatnik/service.wireguard.manager.linux)
![Size](https://img.shields.io/github/repo-size/BrodjagaRatnik/service.wireguard.manager.linux)
![Last Commit](https://shields.io/github/last-commit/BrodjagaRatnik/service.wireguard.manager.linux)
![Build Status](https://github.com/BrodjagaRatnik/service.wireguard.manager.linux/actions/workflows/test_addon.yml/badge.svg)

---

# Multi-Provider WireGuard VPN Manager for Linux Desktop (NordVPN, PIA, Mullvad, Custom)

---

A lightweight, high-performance Kodi service addon for standalone Linux distributions (Debian, Mint, Ubuntu, and LMDE).

Built entirely in pure Python with a memory-isolated, lazy-loaded architecture, this tool manages WireGuard connections natively via NetworkManager (`nmcli`). It features a zero-leak, post-connect firewall killswitch with automatic local subnet routing to guarantee complete data privacy without blocking cryptographic handshake authentication tokens. Fully architecture-independent, it delivers a rock-solid experience that runs flawlessly on x86_64 HTPCs and standalone Debian installations. Includes an automated desktop emergency recovery tool to instantly purge stuck kernel routing states.

## Providers

- **NordVPN** (NordLynx)
- **Private Internet Access** (PIA)
- **Mullvad**
- **Custom** (bring your own WireGuard `.conf`, incl. ProtonVPN via Custom Mode)

## Features

- Multi-Provider Support (Nord, PIA, Mullvad, Custom)
- Pure Python WireGuard handshake logic
- Smart watchdog & auto-reconnect (unprivileged user-space systemd unit)
- Zero-leak firewall killswitch (dedicated iptables chain)
- Hardened DNS & IPv6 leak protection
- Dynamic network device detection (no hardcoded interface names)

## Requirements

- Linux Desktop (Debian, Mint, Ubuntu, LMDE)
- Kodi with Python 3 support (xbmc.python 3.0.1+)
- NetworkManager with nmcli 1.36+ (WireGuard profile import support)
- iptables (killswitch chain management)
- curl

Minimal install on a headless or stripped-down system:

    sudo apt update && sudo apt install -y wireguard wireguard-tools curl network-manager iptables

On a typical desktop installation, NetworkManager and iptables are already
present, so this suffices:

    sudo apt update && sudo apt install -y wireguard wireguard-tools curl

## Installation

Install the addon from [Doemela's Kodi repo](https://github.com/BrodjagaRatnik/doemela-kodi-repo), then pick a provider, import your credentials, and connect via the addon menu. See [Installation & Setup](https://github.com/BrodjagaRatnik/service.wireguard.manager.linux/wiki/Installation-&-Setup).

## Troubleshooting & documentation

See the [wiki](https://github.com/BrodjagaRatnik/service.wireguard.manager.linux/wiki) — including
[coexisting with other network setups](https://github.com/BrodjagaRatnik/service.wireguard.manager.linux/wiki/Coexisting-with-other-network-setups) (Docker/br-* known limitation).

## Issues

Bug reports and feature requests:
[issues page](https://github.com/BrodjagaRatnik/service.wireguard.manager.linux/issues).
Please include the addon version (from `addon.xml`), relevant `kodi.log` lines
around the event, and the output of `ls /sys/class/net` and
`sudo iptables -L -n` if the issue involves networking.

---

> [!NOTE]
> ### ⚠️ EARLY RELEASE — DISTRO TESTERS WANTED!
> The NetworkManager (`nmcli`) core loop is fully validated on Debian and Mint systems. We are actively **seeking testers for other Linux distributions** (Fedora, Arch, openSUSE, Gentoo) to ensure compatibility with varying kernel routing structures and firewall frameworks.

---
*Created by Doemela*
