""" ./resources/lib/vpn_connector.py """
import json
import kodi_env
import os
import subprocess
import time
import re
from logger import log_message
from vpn_config import (
    CONNMAN_SETTLE_DELAY,
    DHCP_RECOVERY_DELAY,
    PROVIDER_MAP,
    ROUTE_PROP_DELAY,
    VPN_CONNECTION_TIMEOUT,
)
from network_utils import (
    set_secure_dns,
    get_default_gateway,
    disable_linux_ipv6,
    find_sibling_profiles,
)
from vpn_utils import (
    is_interface_active,
    fetch_vpn_metadata,
    get_active_interface,
    setup_pia_handshake,
)
from vpn_utils import read_friendly_name as _read_friendly_name
from state_manager import get_file_path, CONFIG_DIR
from providers.routing import setup_vpn_routing
from resources.scripts.killswitch import ZeroHardcodeKillSwitch
import dialog

try:
    import xbmc
    import xbmcgui
    HAS_KODI = True
except ImportError:
    HAS_KODI = False

MAX_CONNECT_ATTEMPTS = 3
CYCLE_FAIL_LIMIT = MAX_CONNECT_ATTEMPTS * 2
CYCLE_FAIL_STALE_S = 3600
_CYCLE_STATE_NAME = "cycle_fail_state"


def _cycle_state_path():
    return get_file_path(_CYCLE_STATE_NAME)


def _load_cycle_state():
    now = time.time()
    fresh = {"count": 0, "ts": now, "name": ""}
    path = _cycle_state_path()
    if path is None or not os.path.exists(path):
        return fresh
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return fresh
        if now - float(data.get("ts", 0)) > CYCLE_FAIL_STALE_S:
            return fresh
        return {
            "count": int(data.get("count", 0)),
            "ts": float(data.get("ts", now)),
            "name": str(data.get("name", "")),
        }
    except Exception:
        return fresh


def _save_cycle_state(state):
    path = _cycle_state_path()
    if path is None:
        return
    try:
        with open(path, "w") as f:
            json.dump(state, f)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        pass


def _reset_cycle_state():
    _save_cycle_state({"count": 0, "ts": time.time(), "name": ""})


def _bump_cycle_state(vpn_name):
    state = _load_cycle_state()
    state = {"count": state["count"] + 1, "ts": time.time(), "name": vpn_name}
    _save_cycle_state(state)
    return state["count"]


def _next_untried_sibling(profile_id, tried_profiles):
    if len(tried_profiles) >= MAX_CONNECT_ATTEMPTS:
        return None
    siblings = find_sibling_profiles(profile_id, CONFIG_DIR)
    for s in siblings:
        if s not in tried_profiles:
            return s
    return None


def _detect_silent_context():
    import sys
    frame_trace = ""
    try:
        curr_frame = sys._getframe()
        while curr_frame:
            f_name = curr_frame.f_code.co_filename
            if f_name:
                frame_trace += f"|{os.path.basename(f_name)}"
            curr_frame = curr_frame.f_back
    except Exception:
        pass

    for key in ("tunnel_checker", "service_loop", "service_launcher"):
        if key in frame_trace:
            return key
    return "normal"


def connect_vpn(vpn_name, sid, instance, silent=False, tried_profiles=None):
    tried_profiles = tried_profiles if tried_profiles is not None else set()
    lock_path = get_file_path("connector_lock")
    killswitch = None

    try:
        if lock_path is not None and os.path.exists(lock_path):
            try:
                with open(lock_path, "r") as f:
                    prev_pid = int(f.read().strip() or "0")
                if prev_pid == os.getpid():
                    log_message(
                        "VPN Connector: Lock held by own retry chain (pid %d), continuing." % prev_pid, 0
                    )
                elif os.path.exists("/proc/%d" % prev_pid):
                    log_message(
                        "VPN Connector: connect already in progress (pid %d), "
                        "debouncing this invocation" % prev_pid, 0
                    )
                    return False
                else:
                    log_message(
                        "VPN Connector: removing stale connector lock (dead pid %d)" % prev_pid, 0
                    )
            except (ValueError, OSError):
                pass

        try:
            if lock_path is not None:
                with open(lock_path, "w") as f:
                    f.write(str(os.getpid()))
                    f.flush()
                    os.fsync(f.fileno())
        except Exception:
            pass

        cycle_state = _load_cycle_state()
        if silent is True and cycle_state["count"] >= CYCLE_FAIL_LIMIT:
            if cycle_state["name"] and vpn_name and cycle_state["name"] != vpn_name:
                _reset_cycle_state()
            else:
                log_message(
                    "VPN Connector: Cycle-fail breaker open (%d consecutive failures on "
                    "'%s'). Deferring silent retry until manual reconnect or profile "
                    "switch." % (cycle_state["count"], cycle_state["name"]), 2
                )
                return False
        elif silent is False:
            _reset_cycle_state()
            dialog.clear_failure_dialogs()

        addon_obj = kodi_env.get_addon_instance()
        provider_id = addon_obj.getSettingInt("vpn_provider") if (HAS_KODI and addon_obj) else 0
        p_data = PROVIDER_MAP.get(provider_id, {})
        p_name = p_data.get("name", "").lower()

        if p_name == "pia":
            log_message("VPN Connector: PIA route detected. Triggering API handshake...", 0)
            if setup_pia_handshake(sid, p_data, addon_obj, HAS_KODI) is False:
                return False

        log_message(f"VPN Connector: Connecting to {vpn_name}", 0)
        profile_id = sid.replace(".conf", "") if sid.endswith(".conf") else sid
        tried_profiles.add(profile_id)

        server_ip = None
        target_conf = os.path.join(CONFIG_DIR, f"{profile_id}.conf")
        if os.path.exists(target_conf):
            try:
                with open(target_conf, "r") as f:
                    for line in f:
                        if "endpoint" in line.lower() and "=" in line:
                            ep = line.split("=")[-1].strip()
                            ip_m = re.search(r"([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})", ep)
                            if ip_m:
                                server_ip = ip_m.group(1)
                                break
            except Exception:
                pass

        ks_enabled = addon_obj.getSettingBool("enable_killswitch") if (HAS_KODI and addon_obj) else False

        pbg = None
        if silent is False and HAS_KODI is True:
            pbg = xbmcgui.DialogProgressBG()
            pbg.create("VPN Manager", f"Connecting to {vpn_name}...")

        try:
            active_devs = subprocess.check_output(["nmcli", "-t", "-f", "DEVICE,STATE", "device"], text=True)
            vpn_markers = ["wg", "wireguard", "nord", "pia", "tun"]
            for dev_line in active_devs.splitlines():
                is_vpn_iface = any(x in dev_line.lower() for x in vpn_markers)
                if ":connected" in dev_line and not is_vpn_iface:
                    phys_dev = dev_line.split(":")[0].strip()
                    subprocess.run(
                        ["nmcli", "device", "modify", phys_dev, "ipv6.method", "disabled"],
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
        except Exception:
            pass

        subprocess.run(
            ["nmcli", "connection", "modify", profile_id, "ipv6.method", "disabled"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        subprocess.run(
            ["nmcli", "connection", "up", profile_id],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        if CONNMAN_SETTLE_DELAY > 0:
            if HAS_KODI is True:
                xbmc.sleep(CONNMAN_SETTLE_DELAY)
            else:
                time.sleep(CONNMAN_SETTLE_DELAY / 1000.0)

        connected = False
        max_steps = int(VPN_CONNECTION_TIMEOUT / DHCP_RECOVERY_DELAY)
        step_percent = 100.0 / max_steps

        for i in range(1, max_steps + 1):
            if pbg and HAS_KODI:
                msg_str = f"Verifying... ({int((i * DHCP_RECOVERY_DELAY) / 1000)}s)"
                pbg.update(int(i * step_percent), message=msg_str)

            if is_interface_active(profile_id) is True or is_interface_active() is True:
                connected = True
                break

            if HAS_KODI is True:
                xbmc.sleep(DHCP_RECOVERY_DELAY)
            else:
                time.sleep(DHCP_RECOVERY_DELAY / 1000.0)

        if pbg and HAS_KODI:
            pbg.close()

        if connected is True:
            log_message(f"VPN Connector: Successfully connected to {vpn_name}", 1)
            setup_vpn_routing(profile_id, bool(p_data.get("requires_endpoint_route")))
            subprocess.run(["ip", "route", "flush", "cache"], check=False)
            instance.set_active_vpn(vpn_name)

            try:
                disable_linux_ipv6()
            except Exception:
                pass

            if ks_enabled and server_ip:
                try:
                    killswitch = ZeroHardcodeKillSwitch(vpn_server_ip=server_ip, vpn_interface=profile_id)
                    if killswitch.enable():
                        log_message(f"VPN Connector: Killswitch Firewall engaged for IP {server_ip}", 1)
                    else:
                        reason = getattr(killswitch, "last_error", "") or "unknown cause"
                        log_message(
                            f"VPN Connector: Killswitch could not be engaged ({reason})", 3
                        )
                        killswitch = None
                        dialog.notify_killswitch_not_active()
                except Exception as ks_err:
                    log_message(f"VPN Connector: Firewall deployment exception bypassed: {ks_err}", 2)
                    killswitch = None
                    dialog.notify_killswitch_not_active()

            if HAS_KODI is True:
                xbmc.sleep(ROUTE_PROP_DELAY)
            else:
                time.sleep(ROUTE_PROP_DELAY / 1000.0)

            try:
                set_secure_dns(profile_id, vpn_active=True)
            except Exception:
                pass

            if HAS_KODI is True:
                time.sleep(0.2)
                meta_iface = get_active_interface() or profile_id
                ip, country = fetch_vpn_metadata(meta_iface)

                if ip is None:
                    log_message(
                        f"VPN Connector: {profile_id} tunnel up but data path "
                        f"verification failed. Treating as failed connection.", 2
                    )
                else:
                    if not ip or ip == "Unknown":
                        try:
                            route_test = subprocess.check_output(["ip", "route", "get", "1.1.1.1"], text=True)
                            if profile_id in route_test:
                                ip = "Tunnel Active (Protected)"
                                country = "Unknown"
                        except Exception:
                            pass

                    if ip and ip != "Unknown":
                        context = _detect_silent_context() if silent is True else "normal"
                        log_message(f"VPN Connector: Dispatching connected toast for {vpn_name} ({ip})", 0)
                        dialog.notify_connected(vpn_name, ip, country, context=context)
                        log_message("VPN Connector: Connected toast dispatch returned", 0)
                        _reset_cycle_state()
                        return True

                if killswitch:
                    killswitch.disable()

                subprocess.run(
                    ["nmcli", "connection", "down", profile_id],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False
                )

                next_profile = _next_untried_sibling(profile_id, tried_profiles)
                if next_profile:
                    resolved_name = _read_friendly_name(next_profile)
                    log_message(
                        f"VPN Connector: {profile_id} connected but data path verification failed, "
                        f"trying alternate candidate {next_profile} ({resolved_name}) "
                        f"(attempt {len(tried_profiles) + 1}/{MAX_CONNECT_ATTEMPTS})", 2
                    )
                    return connect_vpn(resolved_name, next_profile, instance, silent=silent, tried_profiles=tried_profiles)

                if silent is True:
                    fail_count = _bump_cycle_state(vpn_name)
                    if fail_count >= CYCLE_FAIL_LIMIT:
                        log_message(
                            "VPN Connector: Repeated data-path failure (%d consecutive attempts on "
                            "'%s'). Opening breaker and executing full teardown." % (fail_count, vpn_name), 2
                        )
                        dialog.notify_connection_failed(vpn_name)
                        instance.disconnect_vpn(silent=True, flush_dns=True, skip_killswitch_fallback=False)
                        return False
                    log_message(
                        "VPN Connector: Tunnel up but not passing traffic. Retrying... "
                        "(%d/%d)" % (fail_count, CYCLE_FAIL_LIMIT), 1
                    )
                    dialog.notify_tunnelling(vpn_name)
                else:
                    dialog.notify_connection_failed(vpn_name)

                instance.disconnect_vpn(silent=True, flush_dns=False, skip_killswitch_fallback=bool(killswitch))
                return False

            return True

        if killswitch:
            killswitch.disable()

        subprocess.run(
            ["nmcli", "connection", "down", profile_id],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        next_profile = _next_untried_sibling(profile_id, tried_profiles)
        if next_profile:
            resolved_name = _read_friendly_name(next_profile)
            log_message(
                f"VPN Connector: {profile_id} failed to connect, trying alternate candidate "
                f"{next_profile} ({resolved_name}) "
                f"(attempt {len(tried_profiles) + 1}/{MAX_CONNECT_ATTEMPTS})", 2
            )
            return connect_vpn(resolved_name, next_profile, instance, silent=silent, tried_profiles=tried_profiles)

        err_msg = "Internet lost."
        if get_default_gateway():
            err_msg = "Handshake failed. Refused, rate-limited, or unreachable."

        if silent is True:
            fail_count = _bump_cycle_state(vpn_name)
            if fail_count >= CYCLE_FAIL_LIMIT:
                log_message(
                    "VPN Connector: Repeated map-cycle failure (%d consecutive attempts on "
                    "'%s'). Opening breaker and executing full teardown." % (fail_count, vpn_name), 2
                )
                dialog.notify_connection_failed(vpn_name)
                instance.disconnect_vpn(silent=True, flush_dns=True, skip_killswitch_fallback=False)
                return False
            log_message(
                "VPN Connector: Routing profile transition in progress. Retrying step... "
                "(%d/%d)" % (fail_count, CYCLE_FAIL_LIMIT), 1
            )
            dialog.notify_tunnelling(vpn_name)
        else:
            log_message(f"VPN Connector: {err_msg}", 3)

        if silent is False:
            dialog.notify_vpn_failure(err_msg)

        instance.disconnect_vpn(silent=True, flush_dns=False, skip_killswitch_fallback=bool(killswitch))
        return False

    except Exception as connector_fault:
        log_message(f"VPN Connector: Critical framework core failure: {connector_fault}", 3)
        if killswitch:
            killswitch.disable()
        return False

    finally:
        if lock_path is not None and os.path.exists(lock_path) is True:
            try:
                os.remove(lock_path)
            except Exception:
                pass
        try:
            kodi_env.clear_script_globals()
        except Exception:
            pass
