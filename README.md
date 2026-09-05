![Last Commit](https://shields.io/github/last-commit/BrodjagaRatnik/service.wireguard.manager.linux)
![Build Status](https://github.com/BrodjagaRatnik/service.wireguard.manager.linux/actions/workflows/test_addon.yml/badge.svg)
---
# Multi-Provider WireGuard VPN Manager for Linux (NordVPN, PIA, Mullvad, Proton, Custom)
![Release](https://img.shields.io/github/v/release/BrodjagaRatnik/service.wireguard.manager.linux)
![Size](https://img.shields.io/github/repo-size/BrodjagaRatnik/service.wireguard.manager.linux)
![License](https://img.shields.io/github/license/BrodjagaRatnik/service.wireguard.manager.linux)
---
A lightweight, high-performance Kodi service addon for standalone Linux distributions (Debian, Mint, Ubuntu, and LMDE).

Built entirely in pure Python with a memory-isolated, lazy-loaded architecture, this tool manages WireGuard connections natively via NetworkManager (`nmcli`). It features a zero-leak, post-connect firewall killswitch with automatic local subnet routing to guarantee complete data privacy without blocking cryptographic handshake authentication tokens. Fully architecture-independent, it delivers a rock-solid experience that runs flawlessly on x86_64 HTPCs and standalone Debian installations. Includes an automated desktop emergency recovery tool to instantly purge stuck kernel routing states.
