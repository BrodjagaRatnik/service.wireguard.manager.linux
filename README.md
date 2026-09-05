# Multi-Provider WireGuard VPN Manager for Linux (NordVPN, PIA, Mullvad, Proton, Custom)
---
A lightweight, high-performance Kodi service addon for standalone Linux distributions (Debian, Mint, Ubuntu, and LMDE).

Built entirely in pure Python with a memory-isolated, lazy-loaded architecture, this tool manages WireGuard connections natively via NetworkManager (`nmcli`). It features a zero-leak, post-connect firewall killswitch with automatic local subnet routing to guarantee complete data privacy without blocking cryptographic handshake authentication tokens. Fully architecture-independent, it delivers a rock-solid experience that runs flawlessly on x86_64 HTPCs and standalone Debian installations. Includes an automated desktop emergency recovery tool to instantly purge stuck kernel routing states.
  
> [!NOTE]
> ### ⚠️ ACTIVE DEBUGGING STAGE – DISTRO TESTERS WANTED!
> This addon is currently undergoing heavy infrastructure testing. While the native NetworkManager (`nmcli`) core loop is fully validated on Debian and Mint systems, we are actively **seeking testers for other Linux distributions** (such as Fedora, Arch, openSUSE, or Gentoo) to ensure global compatibility with varying kernel routing structures and firewall frameworks.

---
*Created by Doemela*
