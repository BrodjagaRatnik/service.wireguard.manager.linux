""" ./resources/lib/vpn_ops.py """
import kodi_env
import os
import subprocess
import time
from logger import log_message
from vpn_config import (
    OS_RELEASE_DELAY,
    PROP_SYNC_DELAY,
    PROVIDER_MAP,
)
from network_utils import (
    set_secure_dns,
    enable_linux_ipv6,
    get_default_gateway,
)
from vpn_utils import get_active_interface, get_dynamic_prefixes
from state_manager import get_file_path, set_active_vpn
from resources.scripts.killswitch import ZeroHardcodeKillSwitch

try:
    import xbmc
    import xbmcgui
    HAS_KODI = True
except ImportError:
    HAS_KODI = False


def get_addon_path():
    return kodi_env.ADDON_DIR


def disconnect_vpn(silent=False, flush_dns=True, reason="disengaged", skip_killswitch_fallback=False):
    intentional_path = get_file_path("disconnect")
    if not skip_killswitch_fallback:
        try:
            fallback_ks = ZeroHardcodeKillSwitch(vpn_server_ip="0.0.0.0")
            fallback_ks.enabled = True
            fallback_ks.disable(reason=reason)
        except Exception:
            log_message("VPN Ops: Killswitch manual disengage wrapper error logged", 3)
    try:
        if silent is False and HAS_KODI is True:
            xbmcgui.Window(10000).setProperty("vpn_manual_session", "")

        paths_to_clean = []
        manual_path = get_file_path("manual")
        if manual_path is not None:
            if silent is False or reason == "breaker-teardown":
                paths_to_clean.append(manual_path)

        for path in paths_to_clean:
            if os.path.exists(path) is True:
                try:
                    os.remove(path)
                except Exception:
                    log_message("VPN Ops: Disconnect error removing runtime target file path", 3)

        if intentional_path is not None:
            try:
                open(intentional_path, "w").close()
            except Exception:
                log_message("VPN Ops: Disconnect error creating intentional flag file path", 3)

        if HAS_KODI is True:
            xbmcgui.Window(10000).setProperty("vpn_intentional_disconnect", "true")
            xbmcgui.Window(10000).setProperty("vpn_manual_session", "")
            xbmc.sleep(PROP_SYNC_DELAY)
        else:
            time.sleep(PROP_SYNC_DELAY / 1000.0)

        try:
            out = subprocess.check_output(
                ["nmcli", "-t", "-f", "NAME,TYPE,STATE", "connection", "show"],
                text=True
            )
            p_names = [p["name"].lower() for p in PROVIDER_MAP.values()] + ["wireguard", "custom"]
            for line in out.splitlines():
                if ":" in line:
                    c_name, c_type, c_state = line.split(":", 2)
                    c_name_low = c_name.lower()
                    if "activated" in c_state.lower():
                        if any(p in c_name_low or p in c_type.lower() for p in p_names):
                            subprocess.run(
                                ["nmcli", "connection", "down", "id", c_name],
                                check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                            )
        except Exception:
            log_message("VPN Ops: Disconnect service interface operational error", 3)

        try:
            local_gw = get_default_gateway()
            gw_out = subprocess.check_output(["ip", "route", "show", "default"], text=True)
            local_dev = None
            prefixes = get_dynamic_prefixes()
            for line in gw_out.splitlines():
                if "dev" in line:
                    dev_parts = line.split("dev")
                    if len(dev_parts) > 1:
                        tokens = dev_parts[1].split()
                        if tokens and not any(p in tokens[0].lower() for p in prefixes):
                            local_dev = tokens[0]
                            break

            if local_gw is not None and local_dev is not None:
                current_routes = subprocess.check_output(["ip", "route", "show"], text=True)
                for line in current_routes.splitlines():
                    if f"via {local_gw}" in line and f"dev {local_dev}" in line:
                        parts = line.split()
                        if parts and parts[0] != "default":
                            subprocess.run(
                                ["ip", "route", "del", parts[0], "via", local_gw, "dev", local_dev],
                                check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                            )
        except Exception:
            log_message("VPN Ops: Teardown routing resolution error tracked", 0)

        set_secure_dns(vpn_active=False)
        set_active_vpn(None)

        try:
            subprocess.run(
                ["nmcli", "general", "reload", "dns"],
                check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            log_message("VPN Ops: Triggered NetworkManager live DNS configuration reload", 0)
        except Exception:
            pass

        if silent is False:
            if HAS_KODI is True:
                xbmc.sleep(OS_RELEASE_DELAY)
            else:
                time.sleep(OS_RELEASE_DELAY / 1000.0)
        try:
            enable_linux_ipv6()
        except Exception:
            log_message("VPN Ops: Post-disconnect IPv6 restoration failed internally", 3)

        if silent is False and HAS_KODI is True:
            addon_path = get_addon_path()
            icon_dis = os.path.join(addon_path, "resources", "media", "vpn_disconnected.png")
            title = "[B][COLOR FFDF00FF][ VPN Network ][/COLOR][/B]"
            msg = "[B][COLOR FFDF00FF][ DISCONNECTED ][/COLOR][/B]"
            xbmcgui.Dialog().notification(title, msg, icon_dis, 4500)

        gw = None
        try:
            gw = get_default_gateway()
        except Exception:
            pass

        if not gw:
            try:
                route_output = subprocess.check_output(["ip", "route", "show"]).decode("utf-8")
                for route_line in route_output.splitlines():
                    if "scope link" in route_line and "src" in route_line:
                        tokens = route_line.split()
                        raw_ip = tokens[0].split("/")[0]
                        octets = raw_ip.split(".")
                        if len(octets) == 4:
                            gw = f"{octets[0]}.{octets[1]}.{octets[2]}.1"
                            break
            except Exception:
                pass

        if gw:
            try:
                out_route = subprocess.check_output(["ip", "route", "show", "default"], text=True)
                if "default" not in out_route:
                    target_dev = get_active_interface()
                    prefixes = get_dynamic_prefixes()
                    if not target_dev or any(p in target_dev.lower() for p in prefixes):
                        try:
                            dev_out = subprocess.check_output(["ip", "-o", "link", "show"], text=True)
                            for d_line in dev_out.splitlines():
                                d_parts = d_line.split(": ")
                                if len(d_parts) > 1:
                                    d_name = d_parts[1].strip()
                                    if d_name.startswith(("en", "eth", "wl")):
                                        target_dev = d_name
                                        break
                        except Exception:
                            target_dev = "eth0"

                    if not target_dev:
                        target_dev = "eth0"

                    subprocess.run(["ip", "route", "replace", "default", "via", gw, "dev", target_dev], check=False)
                    log_message(f"VPN Ops: Route restored via {gw} on {target_dev}", 0)
            except Exception:
                log_message("VPN Ops: Route Restore Core Error occurred", 3)

        if HAS_KODI is True:
            xbmcgui.Window(10000).setProperty("vpn_intentional_disconnect", "")

    except Exception:
        log_message("VPN Ops: Disconnection core failure tracked", 3)

    finally:
        if intentional_path is not None and os.path.exists(intentional_path) is True:
            try:
                os.remove(intentional_path)
            except Exception:
                log_message("VPN Ops: Error removing intentional disconnect file resource", 3)
        kodi_env.clear_script_globals()


def connect_vpn(vpn_name, sid, silent=False):
    if not HAS_KODI:
        try:
            log_message(f"VPN Ops: Daemon connecting sequence initiated for {vpn_name}", 1)
            res = subprocess.run(
                ["nmcli", "connection", "up", "id", str(sid)],
                check=False, capture_output=True, text=True
            )
            if res.returncode == 0 or "already active" in res.stderr.lower() or "already active" in res.stdout.lower():
                set_active_vpn(vpn_name)
                return True
            log_message(f"VPN Ops: Shell connection failure stdout: {res.stdout} stderr: {res.stderr}", 3)
            return False
        except Exception as shell_err:
            log_message(f"VPN Ops: Fallback connector critical exception: {shell_err}", 3)
            return False
        finally:
            kodi_env.clear_script_globals()

    import vpn_connector
    import sys
    instance = sys.modules[__name__]
    try:
        return vpn_connector.connect_vpn(vpn_name, sid, instance, silent=silent)
    finally:
        pass
