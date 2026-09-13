""" resources/scripts/dnsleaktest.py """
import os
import sys
import time
import socket
import urllib.request
import json

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
LIB_PATH = os.path.abspath(os.path.join(CURRENT_DIR, '..', 'lib'))
if LIB_PATH not in sys.path:
    sys.path.insert(0, LIB_PATH)

API_DOMAIN = 'bash.ws'


def killswitch_engaged():
    try:
        import kodi_env
        addon_obj = kodi_env.get_addon_instance()
        if not addon_obj:
            return False
        if addon_obj.getSetting("enable_killswitch").lower() != "true":
            return False

        from state_manager import get_active_vpn
        return get_active_vpn() is not None
    except Exception:
        return False


def main():
    from logger import log_message

    try:
        import xbmcgui
        has_kodi = True
    except ImportError:
        has_kodi = False

    log_message("DNS Leak Test: Initializing connectivity check", 0)

    if killswitch_engaged():
        log_message("DNS Leak Test: Blocked - firewall killswitch is active.", 2)
        if has_kodi:
            title = "[B]DNS Leak Test[/B]"
            msg = (
                "[COLOR FFFFCC00]Firewall killswitch is active.[/COLOR]\n"
                "The killswitch blocks outbound DNS, so a leak test\n"
                "cannot produce valid results right now.\n\n"
                "Disconnect the VPN or disable the killswitch\n"
                "in the add-on settings and run the test again."
            )
            xbmcgui.Dialog().ok(title, msg)
        return

    if has_kodi:
        progress = xbmcgui.DialogProgress()
        progress.create("DNS Leak Test", "Checking connectivity...")
    else:
        progress = None

    try:
        req = urllib.request.Request(f"https://{API_DOMAIN}", method="HEAD")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status != 200:
                log_message("DNS Leak Test: Host unreachable", 3)
                if progress:
                    progress.close()
                if has_kodi:
                    xbmcgui.Dialog().ok("[B]DNS Test[/B]", "[COLOR FFFF0000]Host unreachable.[/COLOR]")
                return
    except Exception as e:
        log_message(f"DNS Leak Test: Connectivity failed: {e}", 3)
        if progress:
            progress.close()
        if has_kodi:
            xbmcgui.Dialog().ok("[B]DNS Test[/B]", "[COLOR FFFF0000]No VPN connection available.[/COLOR]")
        return

    try:
        with urllib.request.urlopen(f"https://{API_DOMAIN}/id", timeout=5) as resp:
            test_id = resp.read().decode('utf-8').strip()
    except Exception as e:
        log_message(f"DNS Leak Test: ID generation failed: {e}", 3)
        if progress:
            progress.close()
        if has_kodi:
            xbmcgui.Dialog().ok("[B]DNS Test[/B]", "[COLOR FFFF0000]Failed to generate test ID.[/COLOR]")
        return

    log_message(f"DNS Leak Test: Session ID allocated: {test_id}", 0)

    if progress:
        progress.update(20, "Sending DNS probes...")

    for i in range(1, 11):
        if progress and progress.iscanceled():
            log_message("DNS Leak Test: Cancelled by user", 2)
            progress.close()
            return

        target_host = f"{i}.{test_id}.{API_DOMAIN}"
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(b"\x00", (target_host, 53))
            sock.close()
        except Exception:
            pass
        time.sleep(0.05)

        if progress:
            progress.update(20 + (i * 7), "Sending DNS probes... %d/10" % i)

    if progress:
        progress.update(95, "Fetching results...")

    try:
        with urllib.request.urlopen(f"https://{API_DOMAIN}/dnsleak/test/{test_id}?json", timeout=8) as resp:
            server_data = json.loads(resp.read().decode('utf-8').strip())
    except Exception as e:
        log_message(f"DNS Leak Test: Failed fetching payload: {e}", 3)
        if progress:
            progress.close()
        if has_kodi:
            xbmcgui.Dialog().ok("[B]DNS Test[/B]", "[COLOR FFFF0000]Failed to fetch results.[/COLOR]")
        return

    detected_ip = "Unknown"
    dns_servers = []
    conclusion = "Unknown"

    for entry in server_data:
        etype = entry.get("type", "")
        ip_val = entry.get("ip", "").strip()
        country = entry.get("country_name", "").strip()

        if not ip_val:
            continue

        detail = f" [{country}]" if country and country != "false" else ""
        formatted = f"{ip_val}{detail}"

        if etype == "ip":
            detected_ip = formatted
        elif etype == "dns":
            dns_servers.append(formatted)
        elif etype == "conclusion":
            conclusion = entry.get("ip", "")

    log_message(f"DNS Leak Test Results - IP: {detected_ip} | DNS Count: {len(dns_servers)} | Conclusion: {conclusion}", 1)

    if progress:
        progress.close()

    if has_kodi:
        title = "[B]DNS LEAK TEST RESULTS[/B]"
        msg = f"[COLOR FFFFFF00]Your Public IP:[/COLOR]\n{detected_ip}\n"

        if not dns_servers:
            msg += "[COLOR FFFF0000]No DNS Servers detected![/COLOR]\n"
        else:
            msg += f"[COLOR FFFFFF00]Detected DNS ({len(dns_servers)}):[/COLOR]\n"
            msg += "\n".join(dns_servers[:3])
            if len(dns_servers) > 3:
                msg += f" And {len(dns_servers) - 3} more...\n"

        if "is leaking" in conclusion.lower():
            msg += f"[COLOR FFFF0000]Conclusion: {conclusion}[/COLOR]"
        else:
            msg += f"[COLOR FF00FF00]Conclusion: {conclusion}[/COLOR]"

        xbmcgui.Dialog().ok(title, msg)


if __name__ == "__main__":
    main()
