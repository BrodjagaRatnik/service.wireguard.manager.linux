![Release](https://img.shields.io/github/v/release/BrodjagaRatnik/service.wireguard.manager.linux)
![Size](https://img.shields.io/github/repo-size/BrodjagaRatnik/service.wireguard.manager.linux)
![Last Commit](https://shields.io/github/last-commit/BrodjagaRatnik/service.wireguard.manager.linux)
![Build Status](https://github.com/BrodjagaRatnik/service.wireguard.manager.linux/actions/workflows/test_addon.yml/badge.svg)
[![CodeQL](https://github.com/BrodjagaRatnik/service.wireguard.manager.linux/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/BrodjagaRatnik/service.wireguard.manager.linux/actions/workflows/codeql.yml)
---
# Multi-Provider WireGuard VPN Manager for Linux (NordVPN, PIA, Mullvad, Proton, Custom)
---
A lightweight, high-performance Kodi service addon for standalone Linux distributions (Debian, Mint, Ubuntu, and LMDE).

Built entirely in pure Python with a memory-isolated, lazy-loaded architecture, this tool manages WireGuard connections natively via NetworkManager (`nmcli`). It features a zero-leak, post-connect firewall killswitch with automatic local subnet routing to guarantee complete data privacy without blocking cryptographic handshake authentication tokens. Fully architecture-independent, it delivers a rock-solid experience that runs flawlessly on x86_64 HTPCs and standalone Debian installations. Includes an automated desktop emergency recovery tool to instantly purge stuck kernel routing states.
  
> [!NOTE]
> ### ⚠️ ACTIVE DEBUGGING STAGE – DISTRO TESTERS WANTED!
> This addon is currently undergoing heavy infrastructure testing. While the native NetworkManager (`nmcli`) core loop is fully validated on Debian and Mint systems, we are actively **seeking testers for other Linux distributions** (such as Fedora, Arch, openSUSE, or Gentoo) to ensure global compatibility with varying kernel routing structures and firewall frameworks.

---
*Created by Doemela*
