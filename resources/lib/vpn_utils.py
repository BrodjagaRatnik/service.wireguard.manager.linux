""" ./resources/lib/vpn_utils.py """
import kodi_env
import json
import os
import subprocess
import time
import datetime
from logger import log_message
from vpn_config import PROVIDER_MAP
_FNAME_CACHE = {}


def get_addon_path():
    return kodi_env.ADDON_DIR


def get_dynamic_prefixes():
    prefixes = ["wg", "vpn", "tun"]
    try:
        for key in PROVIDER_MAP:
            p_data = PROVIDER_MAP[key]
            if "prefix" in p_data:
                clean_prefix = p_data["prefix"].replace("_", "")
                if clean_prefix not in prefixes:
                    prefixes.append(clean_prefix)
            for extra in p_data.get("extra_prefixes", []):
                if extra not in prefixes:
                    prefixes.append(extra)
    except Exception:
        pass
    return prefixes


def is_interface_active(interface_name=None):
    try:
        if not os.path.exists("/proc/net/dev"):
            return False

        with open("/proc/net/dev", "r") as f:
            lines = f.readlines()

        if interface_name:
            return any(line.split(":")[0].strip() == interface_name for line in lines if ":" in line)

        prefixes = get_dynamic_prefixes()
        for line in lines:
            if ":" in line:
                iface = line.split(":")[0].strip().lower()
                if any(x in iface for x in prefixes):
                    return True
        return False
    except Exception:
        return False


def get_nm_tunnel_device():
    try:
        res = subprocess.run(
            ["nmcli", "-t", "-f", "NAME,DEVICE,TYPE,STATE", "connection",
             "show", "--active"],
            text=True, capture_output=True, check=False, timeout=3.0
        )
        if res.returncode != 0:
            return None, None
        prefixes = get_dynamic_prefixes()
        for line in res.stdout.splitlines():
            fields = line.split(":")
            if len(fields) < 4:
                continue
            state = fields[-1]
            conn_type = fields[-2]
            device = fields[-3]
            name = fields[-4].replace("\\:", ":")
            if state != "activated":
                continue
            if conn_type == "wireguard" or (
                    device and any(p in device.lower() for p in prefixes)):
                return str(name), str(device)
        return None, None
    except Exception:
        return None, None


def get_active_interface():
    prefixes = get_dynamic_prefixes()

    def _matches(name):
        if not name:
            return False
        candidate = name.strip().split("@")[0].lower()
        return any(px in candidate for px in prefixes)

    _, nm_device = get_nm_tunnel_device()
    if nm_device:
        return str(nm_device)

    for attempt in range(3):
        try:
            out = subprocess.check_output(
                ["ip", "route", "show", "default"],
                text=True,
                stderr=subprocess.DEVNULL
            )
            interfaces = []
            for line in out.splitlines():
                parts = line.split()
                if "dev" in parts:
                    dev_idx = parts.index("dev") + 1
                    if dev_idx < len(parts):
                        interfaces.append(parts[dev_idx].strip())

            for iface in interfaces:
                if any(x in iface.lower() for x in prefixes):
                    return str(iface)
        except Exception as e:
            log_message(f"VPN_Utils: Interface lookup error: {e}", 3)

        if attempt < 2:
            time.sleep(0.25)

    try:
        res = subprocess.run(
            ["wg", "show", "interfaces"],
            text=True, capture_output=True, check=False, timeout=3.0
        )
        if res.returncode == 0:
            for iface in res.stdout.split():
                if any(x in iface.lower() for x in prefixes):
                    return str(iface)
    except Exception:
        pass

    try:
        out = subprocess.check_output(
            ["ip", "-o", "link", "show", "up"],
            text=True, stderr=subprocess.DEVNULL
        )
        for line in out.splitlines():
            parts = line.split(":")
            if len(parts) > 1:
                name = parts[1].strip().split("@")[0]
                if any(x in name.lower() for x in prefixes):
                    return str(name)
    except Exception:
        pass

    return None


def get_physical_interface():
    prefixes = get_dynamic_prefixes()

    def _is_tunnel_or_virtual(name):
        if not name:
            return True
        candidate = name.strip().split("@")[0].lower()
        if candidate in ("lo", "docker0"):
            return True
        return any(px in candidate for px in prefixes)

    try:
        out = subprocess.check_output(
            ["ip", "route", "show", "table", "main"],
            text=True,
            stderr=subprocess.DEVNULL
        )
        for line in out.splitlines():
            parts = line.split()
            if "dev" in parts:
                dev = parts[parts.index("dev") + 1].strip()
                if not _is_tunnel_or_virtual(dev):
                    return str(dev)
    except Exception:
        pass

    try:
        for name in sorted(os.listdir("/sys/class/net")):
            if _is_tunnel_or_virtual(name):
                continue
            return str(name)
    except Exception:
        pass

    return None


def check_interface_status():
    try:
        if not os.path.exists("/proc/net/dev"):
            return False, False
        with open("/proc/net/dev", "r") as f:
            lines = f.readlines()

        eth = False
        wifi = False
        prefixes = get_dynamic_prefixes()
        prefixes.extend(["wireguard", "lo"])

        for line in lines:
            if ":" in line:
                iface = line.split(":")[0].strip()
                if not any(x in iface.lower() for x in prefixes):
                    if iface.startswith(("eth", "en")):
                        eth = True
                    elif iface.startswith(("wlan", "wl")):
                        wifi = True
        return eth, wifi
    except Exception as e:
        log_message(f"VPN_Utils: Interface status validation check failure: {e}", 3)
        return False, False


def fetch_vpn_metadata(interface_name):
    t_stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    if interface_name:
        try:
            ping_res = subprocess.run(
                ["ping", "-c", "1", "-W", "1", "-I", interface_name, "1.1.1.1"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            if ping_res.returncode != 0:
                log_message(
                    f"VPN_Utils: ICMP probe unavailable on {interface_name}, "
                    "continuing to TCP metadata verification",
                    1
                )
        except Exception as e:
            log_message(f"VPN_Utils: Ping check threw {e}", 2)
            return None, None

    import socket
    dns_budget = 1.5
    dns_deadline = time.time() + dns_budget
    dns_ready = False
    while True:
        try:
            socket.gethostbyname("ipinfo.io")
            dns_ready = True
            break
        except Exception:
            if time.time() >= dns_deadline:
                break
            time.sleep(0.2)
    if not dns_ready:
        log_message(
            "VPN_Utils: Tunnel DNS not settled before metadata lookup - "
            "provider probes may fail cold",
            2
        )

    providers = [
        ("ipinfo.io", "Ipinfo provider"),
        ("ipapi.co", "Ipapi provider")
    ]

    for idx, (provider_url, log_msg) in enumerate(providers):
        cmd = ["curl", "-s", "--connect-timeout", "1", "--max-time", "2"]
        if interface_name:
            cmd.extend(["--interface", interface_name])
        cmd.append(f"https://{provider_url}")

        try:
            res = subprocess.run(
                cmd,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False
            )
            body = (res.stdout or "").strip()
            if res.returncode == 0 and body:
                data = json.loads(body)
                if "ip" in data:
                    log_message(f"VPN_Utils: {log_msg} selected at {t_stamp}", 1)
                    return data.get("ip", "Unknown"), data.get("country", "??")
            err_detail = (res.stderr or "").strip().replace("\n", " ")[:120]
            if err_detail:
                log_message(
                    f"VPN_Utils: {log_msg} probe failed (rc={res.returncode}): {err_detail}",
                    2
                )
            else:
                log_message(
                    f"VPN_Utils: {log_msg} probe failed (rc={res.returncode}, empty response)",
                    2
                )
        except Exception as probe_err:
            log_message(f"VPN_Utils: {log_msg} probe exception: {probe_err}", 2)
            if idx < len(providers) - 1:
                continue
            else:
                log_message("VPN_Utils: Both metadata providers failed", 2)

    return "Unknown", "??"


def setup_pia_handshake(sid, provider_data, addon_obj, has_kodi):
    from providers.pia_utils import setup_pia_handshake as resolve_pia_handshake
    return resolve_pia_handshake(sid, provider_data, addon_obj, has_kodi)


def read_friendly_name(profile_id, config_dir=None):
    from state_manager import CONFIG_DIR
    if profile_id in _FNAME_CACHE:
        return _FNAME_CACHE[profile_id]
    if config_dir is None:
        config_dir = CONFIG_DIR
    path = os.path.join(config_dir, f"{profile_id}.conf")
    name = profile_id
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("# FriendlyName ="):
                    name = line.split("=", 1)[-1].strip()
                    break
    except Exception:
        pass
    if len(_FNAME_CACHE) < 256:
        _FNAME_CACHE[profile_id] = name
    return name
