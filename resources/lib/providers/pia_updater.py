""" ./resources/lib/providers/pia_updater.py
https://github.com/pia-foss/manual-connections/
    dns_str = "10.0.0.243, 10.0.0.241, 1.1.1.1, 9.9.9.9"

SERVER_LIST_URL = "https://serverlist.piaservers.net/vpninfo/servers/v6"
"""
import json
import os
import subprocess
import ssl
import time
import socket
import urllib.error
import urllib.parse
import urllib.request
from logger import log_message
from providers import routing
from providers import pia_config

SERVER_LIST_URL = "https://serverlist.piaservers.net/vpninfo/servers/v6"


def _short_interface_name(rid):
    base_name = f"pia_{rid}"
    if len(base_name) > 15:
        log_message(
            f"PIA Updater: generated interface name '{base_name}' exceeds 15 chars, truncating", 2
        )
        base_name = base_name[:15]
    return base_name


def _generate_placeholder_keypair():
    try:
        priv = subprocess.check_output(["wg", "genkey"]).decode().strip()
        pub = subprocess.check_output(["wg", "pubkey"], input=priv.encode()).decode().strip()
        return priv, pub
    except Exception as e:
        log_message(f"PIA Updater: Failed to generate placeholder keypair: {e}", 3)
        return "", ""


def update(user, password, country_ids, config_dir):
    selected_list = [i.strip().lower() for i in country_ids.split(',') if i.strip()]

    from state_manager import get_active_vpn

    if os.path.exists(config_dir) is True:
        for filename in os.listdir(config_dir):
            if filename.startswith("pia_") and filename.endswith(".conf"):
                file_id = filename.replace("pia_", "").replace(".conf", "")
                if file_id not in selected_list:
                    try:
                        conn_profile_name = filename.replace(".conf", "")
                        subprocess.run(
                            ["nmcli", "connection", "delete", "id", conn_profile_name],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
                        )
                        os.remove(os.path.join(config_dir, filename))
                    except Exception as r_err:
                        log_message(f"PIA Updater: Server array tracking error skipped {r_err}", 3)

    raw_data = None
    for attempt in range(3):
        try:
            ctx = ssl._create_unverified_context()
            req = urllib.request.Request(SERVER_LIST_URL, headers={'User-Agent': 'PIA-VPN/3.5.0 (Linux)'})

            with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                raw_payload = resp.read().decode('utf-8').strip()
                if "\n" in raw_payload:
                    raw_data = raw_payload.splitlines()[0].strip()
                else:
                    raw_data = raw_payload
            break
        except urllib.error.URLError as url_err:
            if "101" in str(url_err) or "unreachable" in str(url_err).lower():
                if attempt == 0:
                    time.sleep(3.0)
                    continue
            log_message(f"PIA Updater: URL Error: {url_err}", 3)
            return False
        except Exception as fetch_err:
            log_message(f"PIA Updater: Fetch Error: {fetch_err}", 3)
            return False

    if raw_data is None:
        return False

    try:
        data = json.loads(raw_data)
        name_mapping = {}
        compiled_files_count = 0
        total_nodes_count = 0

        config_latency = getattr(pia_config, "MAX_LATENCY", 0.05)
        latency_tiers = [config_latency, 0.15, 0.30, 0.60, 1.00]

        for rid in selected_list:
            region_node = None
            for r in data.get('regions', []):
                if r['id'].lower() == rid:
                    region_node = r
                    break

            if not region_node or region_node.get('offline', False):
                continue

            servers_dict = region_node.get('servers', {})
            if not isinstance(servers_dict, dict):
                continue

            wg_servers = servers_dict.get('wg', [])
            if not wg_servers or not isinstance(wg_servers, list):
                continue

            valid_candidates = []
            for srv in wg_servers:
                if isinstance(srv, dict) and srv.get('ip') and srv.get('cn'):
                    valid_candidates.append(srv)

            if not valid_candidates:
                continue

            log_message(f"PIA Speed Profiler: Evaluating nodes for region profile ID: {rid}", 0)
            verified_servers = []

            for max_latency in latency_tiers:
                log_message(f"PIA Speed Profiler: Scanning nodes under threshold tier: {max_latency * 1000:.0f}ms", 0)
                for srv in valid_candidates:
                    srv_ip = str(srv.get('ip'))
                    start_t = time.time()
                    try:
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        s.settimeout(max_latency)
                        s.connect((srv_ip, 443))
                        s.close()
                        elapsed = time.time() - start_t
                        verified_servers.append((elapsed, srv))
                    except (socket.timeout, ConnectionRefusedError, OSError):
                        continue
                if verified_servers:
                    break

            if verified_servers:
                verified_servers.sort(key=lambda x: x[0])
                final_servers = [item[1] for item in verified_servers]
                fastest_ms = float(verified_servers[0][0]) * 1000.0
                log_message(f"PIA Speed Profiler: Fastest server discovered responding in {fastest_ms:.1f}ms", 0)
                log_message("PIA Speed Profiler: Sorting array. Placing optimal node at index zero.", 0)
            else:
                log_message("PIA Speed Profiler: No targets cleared latency ceiling. Using raw payload metrics.", 2)
                final_servers = valid_candidates

            server_ips = [str(x.get('ip')) for x in final_servers]
            server_cns = [str(x.get('cn')) for x in final_servers]

            region_name = str(region_node.get('name', rid))
            safe_key = f"PIA_{region_name.replace(' ', '_')}".lower()
            name_mapping[safe_key] = rid

            v_temp = region_name.replace('Optimized', 'Optimize')
            clean_region_name = v_temp.replace('optimized', 'Optimize')
            friendly_name = f"PIA {clean_region_name}"

            base_name = _short_interface_name(rid)
            placeholder_priv, placeholder_pub = _generate_placeholder_keypair()

            os.makedirs(config_dir, exist_ok=True)
            file_path = os.path.join(config_dir, f"{base_name}.conf")
            config_text = (
                f"# FriendlyName = {friendly_name}\n"
                f"# WireGuard.Pool = {','.join(server_ips)}\n"
                f"# WireGuard.CN_Pool = {','.join(server_cns)}\n"
                "[Interface]\n"
                f"PrivateKey = {placeholder_priv}\n"
                "Address = 10.0.0.1/32\n"
                "MTU = 1380\n"
                "\n[Peer]\n"
                f"PublicKey = {placeholder_pub}\n"
                f"Endpoint = {server_ips[0]}:1337\n"
                "AllowedIPs = 0.0.0.0/0\n"
                "PersistentKeepalive = 25\n"
            )

            with open(file_path, 'w') as f:
                f.write(config_text)
            os.chmod(file_path, 0o600)

            try:
                subprocess.run(
                    ["nmcli", "connection", "delete", "id", base_name],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
                )
                import_result = subprocess.run(
                    ["nmcli", "connection", "import", "type", "wireguard", "file", file_path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, check=False
                )
                if import_result.returncode != 0:
                    log_message(
                        f"PIA Updater: nmcli import failed for {base_name}: {import_result.stderr.strip()}", 2
                    )
                else:
                    subprocess.run(
                        ["nmcli", "connection", "down", base_name],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
                    )
                    subprocess.run(
                        ["nmcli", "connection", "modify", base_name,
                         "connection.autoconnect", "no"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
                    )
            except Exception as nm_err:
                log_message(f"PIA Updater: NetworkManager profile registration failed for {base_name}: {nm_err}", 2)

            compiled_files_count += 1
            total_nodes_count += len(server_ips)

        from state_manager import get_file_path
        map_path = get_file_path('pia_map')
        if map_path is not None:
            try:
                with open(map_path, 'w') as mf:
                    json.dump(name_mapping, mf)
            except Exception:
                pass

        from state_manager import write_state
        from vpn_utils import get_dynamic_prefixes
        has_active_iface = False
        _prefixes = get_dynamic_prefixes()
        if os.path.exists('/sys/class/net/'):
            for _iface in os.listdir('/sys/class/net/'):
                if any(p in _iface.lower() for p in _prefixes):
                    has_active_iface = True
                    break

        if has_active_iface is True:
            log_message("PIA Updater: Active interface detected. Scheduling deferred reconnect.", 1)
            boot_target = get_active_vpn()
            if boot_target:
                write_state('reconnect', str(boot_target))

        return True

    except Exception as e:
        log_message(f"PIA Updater: {e}", 3)
        return False


def build_final_config(wg_data, pk, server_ip, region_id, region_name=None, raw_cn_str="", allowed_ips_mode=1):
    dns_str = "10.0.0.243, 10.0.0.241"
    if not region_name:
        region_name = region_id
    port_str = str(wg_data.get('server_port', '1337'))
    allowed_ips = routing.get_allowed_ips(use_split_default=True)
    dynamic_mtu = routing.get_optimal_mtu()

    return (
        f"# FriendlyName = PIA {region_name}\n"
        f"# WireGuard.CN_Pool = {raw_cn_str}\n"
        "[Interface]\n"
        f"PrivateKey = {pk}\n"
        f"Address = {wg_data['peer_ip']}/32\n"
        f"DNS = {dns_str}\n"
        f"MTU = {dynamic_mtu}\n"
        "\n[Peer]\n"
        f"PublicKey = {wg_data['server_key']}\n"
        f"Endpoint = {server_ip}:{port_str}\n"
        f"AllowedIPs = {allowed_ips}\n"
        "PersistentKeepalive = 25\n"
    )
