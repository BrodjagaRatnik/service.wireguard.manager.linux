""" ./resources/lib/providers/routing.py """
import os
import subprocess
from logger import log_message
from network_utils import get_default_gateway, resolve_server_ip


def get_allowed_ips(
    lan_bypass: bool = False,
    custom_bypass_subnets: list = None,
    use_split_default: bool = False,
    provider_requires_split: bool = False
) -> str:
    if use_split_default is True or provider_requires_split is True:
        return "0.0.0.0/1, 128.0.0.0/1"
    return "0.0.0.0/0"


def get_optimal_mtu() -> str:
    chosen_mtu = "1380"
    try:
        from vpn_utils import get_active_interface
        target_iface = get_active_interface()
        if not target_iface:
            out_route = subprocess.check_output(["ip", "route", "show", "default"], text=True)
            for line in out_route.splitlines():
                if "dev" in line:
                    parts = line.split()
                    idx = parts.index("dev")
                    if idx + 1 < len(parts):
                        target_iface = parts[idx + 1]
                        break
        if target_iface and (os.path.exists(f"/sys/class/net/{target_iface}/mtu") is True):
            with open(f"/sys/class/net/{target_iface}/mtu", "r") as f:
                phys_mtu = int(f.read().strip())
            calculated_wg_mtu = phys_mtu - 80
            if calculated_wg_mtu >= 1420:
                chosen_mtu = "1420"
            elif calculated_wg_mtu >= 1400:
                chosen_mtu = "1400"
            elif calculated_wg_mtu >= 1380:
                chosen_mtu = "1380"
            else:
                chosen_mtu = "1280"
    except Exception as mtu_err:
        log_message(f"Routing: Kernel MTU calculation failure: {mtu_err}", 2)
    return chosen_mtu


def setup_vpn_routing(sid: str, requires_endpoint_route: bool) -> None:
    """
    Routing for regular (non-split) profiles is handled by
    NetworkManager's native WireGuard integration (see
    network_utils.set_secure_dns / custom.py, which set
    wireguard.ip4-auto-default-route=true and wireguard.peer-routes=true
    on import) — NetworkManager avoids the "traffic to your own VPN
    server gets routed through the tunnel" loop internally, the same
    way wg-quick's Table=off mechanism does.

    Providers using split-tunneling AllowedIPs (0.0.0.0/1, 128.0.0.0/1
    instead of 0.0.0.0/0) bypass that automatic default-route handling,
    so for those (requires_endpoint_route=True, currently only PIA) we
    still add an explicit route to the VPN server itself via the
    original gateway, so server traffic doesn't loop back into the
    tunnel. If this ever misbehaves for a given provider, set
    requires_endpoint_route back to False for it in PROVIDER_MAP to
    fall back to full NetworkManager automatic routing.
    """
    if requires_endpoint_route is not True:
        log_message(
            f"Routing: Delegating route setup for '{sid}' to NetworkManager "
            f"(ip4-auto-default-route/peer-routes)", 0
        )
        return

    try:
        server_ip = resolve_server_ip(sid)

        if server_ip:
            gw_out = subprocess.check_output(["ip", "route", "show", "default"], text=True)
            local_gw = get_default_gateway()
            local_dev = None
            for line in gw_out.splitlines():
                if "dev" in line and sid not in line:
                    parts = line.split("dev")[-1].strip().split()
                    if parts:
                        local_dev = parts[0]
                        break

            if local_gw is not None and local_dev is not None:
                subprocess.run(
                    ["ip", "route", "add", server_ip, "via", local_gw, "dev", local_dev],
                    check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                log_message(
                    f"Routing: Added endpoint bypass route for {sid} -> {server_ip} via {local_gw} dev {local_dev}", 0
                )
            else:
                log_message(f"Routing: Could not resolve local gateway/device for endpoint route ({sid})", 2)
        else:
            log_message(f"Routing: Could not resolve server IP for endpoint route ({sid})", 2)

    except Exception as e:
        log_message(f"Routing: Endpoint bypass route setup failed for {sid}: {e}", 3)
