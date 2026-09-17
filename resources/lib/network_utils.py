""" ./resources/lib/network_utils.py """
import os
import re
import subprocess
from logger import log_message
from state_manager import CONFIG_DIR


def get_default_gateway():
    try:
        out = subprocess.check_output(["ip", "route", "show", "default"], text=True).strip()
        if not out:
            return None
        parts = out.split()
        if "via" in parts:
            return parts[parts.index("via") + 1]
        if "dev" in parts:
            dev = parts[parts.index("dev") + 1]
            out_dev = subprocess.check_output(["ip", "route", "show", "dev", dev], text=True)
            for line in out_dev.splitlines():
                line_parts = line.split()
                if "via" in line_parts:
                    return line_parts[line_parts.index("via") + 1]
    except Exception as e:
        log_message(f"Network Utils: Failed to resolve default gateway: {e}", 3)
    return None


def resolve_server_ip(sid):
    if not sid:
        return None

    profile_id = sid.replace(".conf", "")
    config_path = os.path.join(CONFIG_DIR, f"{profile_id}.conf")

    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                for line in f:
                    if "endpoint" in line.lower() and "=" in line:
                        ep = line.split("=")[-1].strip()
                        ip_m = re.search(r"([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})", ep)
                        if ip_m:
                            return ip_m.group(1)
        except Exception:
            pass

    try:
        if "vpn_" in sid:
            parts = sid.split('_')
            if len(parts) >= 5 and all(p.isdigit() for p in parts[1:5]):
                return f"{parts[1]}.{parts[2]}.{parts[3]}.{parts[4]}"
    except Exception:
        pass

    return None


def find_sibling_profiles(profile_id, config_dir=None):
    config_dir = config_dir or CONFIG_DIR
    base = re.sub(r'_?\d+$', '', profile_id)
    siblings = []

    if not base or not os.path.exists(config_dir):
        return siblings

    try:
        for f_name in os.listdir(config_dir):
            if not f_name.lower().endswith(('.conf', '.config')):
                continue
            stem = os.path.splitext(f_name)[0]
            if stem != profile_id and stem.startswith(base):
                siblings.append(stem)
    except Exception as e:
        log_message(f"Network Utils: find_sibling_profiles failed for {profile_id}: {e}", 3)
        return []

    return sorted(siblings)


def get_dns_from_config(vpn_name):
    dns_list = []
    if not vpn_name:
        return dns_list

    search_terms = [w.strip().lower() for w in vpn_name.replace('-', '_').split('_') if len(w.strip()) > 1]
    if not search_terms:
        return dns_list

    target_path = None
    if os.path.exists(CONFIG_DIR):
        best_match_count = 0
        for f_name in os.listdir(CONFIG_DIR):
            f_lower = f_name.lower()
            if f_lower.endswith(('.config', '.conf')):
                match_count = 0
                for term in search_terms:
                    if term in f_lower:
                        match_count += 1
                if match_count > best_match_count:
                    best_match_count = match_count
                    target_path = os.path.join(CONFIG_DIR, f_name)

    if not target_path and os.path.exists(CONFIG_DIR):
        files = [f for f in os.listdir(CONFIG_DIR) if f.lower().endswith(('.config', '.conf'))]
        if files:
            target_path = os.path.join(CONFIG_DIR, files[0])

    if target_path:
        try:
            with open(target_path, 'r') as f:
                content = f.read()
                match = re.search(r"(?:WireGuard\.)?DNS\s*=\s*(.*)", content, re.IGNORECASE)
                if match:
                    dns_list = [d.strip() for d in match.group(1).split(",")]
                    log_message(f"Network Utils: Dynamically extracted DNS from resolved path: {target_path}", 0)
        except Exception as e:
            log_message(f"Network Utils: Error parsing file {target_path}: {e}", 3)

    return dns_list


def set_secure_dns(vpn_name=None, vpn_active=True):
    if vpn_active is True and vpn_name:
        try:
            from vpn_utils import get_dynamic_prefixes
            sid_target = str(vpn_name).strip().replace(" ", "_").replace(".conf", "").lower()

            if any(sid_target.startswith(x) for x in ["eth", "en", "wlan", "wl", "lo"]):
                log_message(f"Network Utils: Aborting hardening - Target '{sid_target}' is a physical adapter.", 2)
                return False

            prefixes = get_dynamic_prefixes()
            if not any(x in sid_target for x in prefixes):
                log_message(f"Network Utils: Aborting hardening - Target '{sid_target}' does not match vpn prefix.", 2)
                return False

            subprocess.run(
                ["nmcli", "connection", "modify", sid_target,
                 "ipv6.method", "disabled",
                 "ipv4.dns-priority", "-100",
                 "ipv4.never-default", "no"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
            )
            log_message(f"Network Utils: NetworkManager central hardening enforced for {sid_target}.", 1)
        except Exception as e:
            log_message(f"Network Utils: Handshake hardening bypass captured: {e}", 2)

    return True


def toggle_sysctl_ipv6(disable=True):
    val_disable = "1" if disable else "0"
    val_ra_auto = "0" if disable else "1"
    targets = ["all", "default"]
    proc_path = "/proc/sys/net/ipv6/conf/"
    if os.path.exists(proc_path):
        try:
            active_adapters = [
                d for d in os.listdir(proc_path)
                if not any(x in d.lower() for x in ["lo", "wg", "wireguard", "mullvad", "mld", "nord", "pia", "tun"])
            ]
            targets.extend(active_adapters)
        except Exception:
            pass
    for interface in targets:
        try:
            subprocess.run(
                ["sysctl", "-w", f"net.ipv6.conf.{interface}.disable_ipv6={val_disable}"],
                check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            subprocess.run(
                ["sysctl", "-w", f"net.ipv6.conf.{interface}.accept_ra={val_ra_auto}"],
                check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            subprocess.run(
                ["sysctl", "-w", f"net.ipv6.conf.{interface}.autoconf={val_ra_auto}"],
                check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception:
            continue


def manage_networkmanager_services(ipv6_mode="disabled"):
    modified_count = 0
    physical_types = ("ethernet", "802-3-ethernet", "wireless", "802-11-wireless")
    try:
        result = subprocess.check_output(
            ["nmcli", "-t", "-f", "UUID,TYPE", "connection", "show"],
            text=True
        )
        for line in result.splitlines():
            if ":" in line:
                uuid, c_type = line.split(":", 1)
                if uuid and c_type.strip().lower() in physical_types:
                    subprocess.run(
                        ["nmcli", "connection", "modify", uuid, "ipv6.method", ipv6_mode],
                        check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                    )
                    modified_count += 1
        log_message(f"Network Utils: IPv6 [{ipv6_mode}] applied to {modified_count} physical connections.", 0)
    except Exception:
        pass


def disable_linux_ipv6():
    try:
        toggle_sysctl_ipv6(disable=True)
        manage_networkmanager_services(ipv6_mode="disabled")
        gw_out = subprocess.check_output(["ip", "route", "show", "default"], text=True)
        local_dev = None
        for line in gw_out.splitlines():
            if "dev" in line and not any(x in line.lower() for x in ["wg", "wireguard", "mullvad", "mld", "tun"]):
                tokens = line.split("dev")[-1].strip().split()
                if tokens:
                    local_dev = tokens[0]
                    break
        if local_dev:
            subprocess.run(
                ["sysctl", "-w", f"net.ipv6.conf.{local_dev}.disable_ipv6=1"],
                check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            subprocess.run(
                ["sysctl", "-w", f"net.ipv6.conf.{local_dev}.accept_ra=0"],
                check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            subprocess.run(
                ["ip", "-6", "addr", "flush", "dev", local_dev],
                check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
    except Exception:
        pass


def enable_linux_ipv6():
    toggle_sysctl_ipv6(disable=False)
    manage_networkmanager_services(ipv6_mode="auto")


def is_physically_connected(interface):
    carrier_path = f"/sys/class/net/{interface}/carrier"
    operstate_path = f"/sys/class/net/{interface}/operstate"
    try:
        if interface.startswith("wlan") or interface.startswith("wl"):
            if os.path.exists(operstate_path):
                with open(operstate_path, 'r') as f:
                    return f.read().strip().lower() in ['up', 'dormant']
            return False
        if os.path.exists(carrier_path):
            try:
                with open(carrier_path, 'r') as f:
                    return f.read().strip() == '1'
            except OSError as e:
                if e.errno == 22 and os.path.exists(operstate_path):
                    with open(operstate_path, 'r') as f:
                        return f.read().strip().lower() == 'up'
                return False
        return False
    except Exception as e:
        log_message(f"Network Utils: Carrier status check failed for {interface}: {e}", 3)
        return False


def get_profile_allowed_ips(sid):
    try:
        config_path = os.path.join(CONFIG_DIR, f"{sid}.conf")
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                for line in f:
                    if "allowedips" in line.lower() and "=" in line:
                        return line.split("=")[-1].strip()
    except Exception:
        pass
    return ""
