""" ./resources/lib/tunnel_checker.py """
import kodi_env
import subprocess
import time

try:
    import xbmcgui
    HAS_GUI = True
except ImportError:
    HAS_GUI = False

try:
    import xbmc
    HAS_KODI = True
except ImportError:
    HAS_KODI = False

from logger import log_message
from vpn_utils import (
    is_interface_active,
    get_active_interface,
    fetch_vpn_metadata,
    get_dynamic_prefixes,
    get_nm_tunnel_device
)
from state_manager import get_active_vpn, write_state
from vpn_config import SANITY_POLL_INTERVAL, SANITY_SETTLE_DELAY
from resources.scripts.killswitch import ZeroHardcodeKillSwitch
from dialog import notify_tunnel_restored, notify_orphaned_tunnel


def _breaker_open_for(target_name):
    try:
        from vpn_connector import _load_cycle_state, CYCLE_FAIL_LIMIT
        state = _load_cycle_state()
        if state["count"] < CYCLE_FAIL_LIMIT:
            return False
        if state["name"] and target_name and state["name"] != str(target_name):
            return False
        return True
    except Exception:
        return False


def run_tunnel_sanity_check(run_update_if_clear=False):
    try:
        addon_obj = kodi_env.get_addon_instance()
        if not addon_obj:
            return

        is_playing_stream = False
        if HAS_KODI and xbmc.Player().isPlaying():
            playing_file = xbmc.Player().getPlayingFile()
            stream_protocols = ["http://", "https://", "rtmp://", "pvr://"]
            is_playing_stream = any(playing_file.startswith(p) for p in stream_protocols)

        if is_playing_stream:
            log_message("Tunnel Check: Active stream detected. Postponing health check.", 0)
            return

        prefixes = get_dynamic_prefixes()
        current_default_iface = get_active_interface()

        def _find_tunnel_iface():
            nm_name, nm_device = get_nm_tunnel_device()
            if nm_device:
                return str(nm_device)
            try:
                res = subprocess.run(
                    ["wg", "show", "interfaces"],
                    text=True, capture_output=True, check=False, timeout=3.0
                )
                if res.returncode == 0:
                    for iface in res.stdout.split():
                        if any(p in iface.lower() for p in prefixes):
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
                        if any(p in name.lower() for p in prefixes):
                            return str(name)
            except Exception:
                pass
            return None

        if not current_default_iface:
            tunnel_iface = _find_tunnel_iface()
            if not tunnel_iface:
                log_message("Tunnel Check: No interface info available. Skipping check.", 0)
                return
            current_default_iface = tunnel_iface
        else:
            is_tunnel_iface = any(p in current_default_iface.lower() for p in prefixes)
            if not is_tunnel_iface:
                tunnel_iface = _find_tunnel_iface()
                if not tunnel_iface:
                    log_message("Tunnel Check: No tunnel interface present. Nothing to verify.", 0)
                    return
                current_default_iface = tunnel_iface

        if not is_interface_active(current_default_iface):
            log_message("Tunnel Check: Tunnel interface exists but is inactive.", 0)
            return

        tunnel_is_broken = False
        try:
            res = subprocess.run(
                ["ping", "-c", "1", "-W", "2", "1.1.1.1"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=3.0
            )
            if res.returncode != 0:
                log_message("Tunnel Check: Interface up but end-to-end routing ping failed.", 0)
                tunnel_is_broken = True
        except subprocess.TimeoutExpired:
            log_message("Tunnel Check: Process execution timed out.", 0)
            tunnel_is_broken = True
        except Exception as ping_err:
            log_message(f"Tunnel Check: Connection verification exception: {ping_err}", 3)
            tunnel_is_broken = True

        if not tunnel_is_broken:
            log_message("Tunnel Check: Link health verification successful. Tunnel is clear.", 0)
            if run_update_if_clear is True:
                try:
                    from vpn_core import check_for_updates
                    check_for_updates("")
                    log_message("Tunnel Check: Deferred update executed on clear tunnel.", 1)
                except Exception as defer_update_err:
                    log_err = f"Tunnel Check: Inline deferred update failure: {defer_update_err}"
                    log_message(log_err, 2)
            return

        boot_target = get_active_vpn()

        if not boot_target:
            log_message(
                "Tunnel Check: Dead link detected but no session state to recover. "
                "Leaving interface untouched.", 2
            )
            notify_orphaned_tunnel(current_default_iface)
            return

        if _breaker_open_for(boot_target):
            log_message(
                "Tunnel Check: Cycle-fail breaker open for [%s]. Taking dead tunnel "
                "down and clearing session state - no reconnect attempt." % boot_target, 2
            )
            recovery_ks_handled = False
            try:
                recovery_ks = ZeroHardcodeKillSwitch(vpn_server_ip="0.0.0.0")
                recovery_ks.enabled = True
                recovery_ks.disable(reason="breaker-teardown")
                recovery_ks_handled = True
            except Exception as fw_purge_err:
                log_message(f"Tunnel Check: Breaker teardown firewall purge exception: {fw_purge_err}", 3)

            import vpn_ops
            vpn_ops.disconnect_vpn(
                silent=True, flush_dns=True, reason="breaker-teardown",
                skip_killswitch_fallback=recovery_ks_handled
            )

            if HAS_GUI:
                try:
                    xbmcgui.Window(10000).setProperty('vpn_manual_session', '')
                except Exception:
                    pass
            return

        log_message("Tunnel Check: Dead link confirmed. Forcing reconnect sequence...", 2)
        recovery_ks_handled = False
        try:
            log_message("Tunnel Check: Dismantling active killswitch rules safely...", 0)
            recovery_ks = ZeroHardcodeKillSwitch(vpn_server_ip="0.0.0.0")
            recovery_ks.enabled = True
            recovery_ks.disable(reason="recovery")
            recovery_ks_handled = True
        except Exception as fw_purge_err:
            log_message(f"Tunnel Check: System firewall purge exception: {fw_purge_err}", 3)

        import vpn_ops
        vpn_ops.disconnect_vpn(
            silent=True, flush_dns=True, reason="recovery",
            skip_killswitch_fallback=recovery_ks_handled
        )

        timeout = 5.0
        poll_interval = SANITY_POLL_INTERVAL / 1000.0

        def _tunnel_still_active():
            nm_name, nm_device = get_nm_tunnel_device()
            if nm_device is not None:
                return True
            return is_interface_active(current_default_iface)

        while timeout > 0:
            if not _tunnel_still_active():
                break
            time.sleep(poll_interval)
            timeout -= poll_interval
        else:
            log_message(
                "Tunnel Check: Recovery wait expired - stale route or interface persists.", 2
            )

        time.sleep(SANITY_SETTLE_DELAY / 1000.0)

        dns_timeout = 4.0
        dns_ready = False
        while dns_timeout > 0:
            try:
                import socket
                socket.gethostbyname("one.one.one.one")
                dns_ready = True
                break
            except socket.error:
                time.sleep(0.2)
                dns_timeout -= 0.2

        if dns_ready:
            try:
                from vpn_core import check_for_updates
                check_for_updates("")
            except Exception as update_err:
                log_message(f"Tunnel Check: Inline update invocation failed: {update_err}", 3)
        else:
            log_message("Tunnel Check: WAN DNS resolution recovery timed out. Skipping update lookups.", 2)

        from service_resolver import resolve_service_id
        sid = resolve_service_id(addon_obj, boot_target)

        if not sid:
            log_message(f"Tunnel Check: Service ID lookup dropped for {boot_target}", 3)
            return

        log_message("Tunnel Check: Registering fallback session state protection.", 0)
        write_state('manual', 'true')
        if HAS_GUI:
            xbmcgui.Window(10000).setProperty('vpn_manual_session', 'true')

        connect_ok = vpn_ops.connect_vpn(str(boot_target), str(sid), silent=True)

        if connect_ok is True:
            meta_iface = get_active_interface() or current_default_iface
            ip, country = fetch_vpn_metadata(meta_iface)
            if ip and ip != "Unknown":
                log_message(
                    f"Tunnel Check: Profile link [{boot_target}] verified and "
                    f"re-established ({ip}).", 1
                )
                if HAS_GUI:
                    xbmcgui.Window(10000).setProperty('vpn_reconnected', boot_target)
                notify_tunnel_restored(boot_target, ip, country)
            else:
                log_message(
                    f"Tunnel Check: Reconnect to [{boot_target}] completed but "
                    f"data path unverified. Deferring verdict to next health cycle.", 2
                )
        else:
            log_message(
                f"Tunnel Check: Reconnect to [{boot_target}] was not completed. "
                f"Further retries governed by the cycle-fail breaker.", 2
            )

    except Exception as e:
        log_message(f"Tunnel Check: Monitoring framework tracking exception: {e}", 3)

    finally:
        kodi_env.clear_script_globals()


if __name__ == "__main__":
    run_tunnel_sanity_check()
