""" ./resources/lib/tunnel_checker.py """
import kodi_env
import os
import socket
import subprocess
import time
import traceback

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
from state_manager import get_active_vpn, write_state, get_file_path
from vpn_config import SANITY_POLL_INTERVAL, SANITY_SETTLE_DELAY
from resources.scripts.killswitch import ZeroHardcodeKillSwitch
from dialog import (
    notify_tunnel_restored,
    notify_orphaned_tunnel,
    ask_reconnect_retry,
    notify_breaker_open,
    failure_dialog_allowed,
    mark_failure_dialog_shown,
    clear_failure_dialogs
)


def _breaker_open_for(target_name):
    try:
        from vpn_connector import _load_cycle_state, CYCLE_FAIL_LIMIT
        log_message(f"[BREAKER] Loading cycle state, limit={CYCLE_FAIL_LIMIT}", 1)
        state = _load_cycle_state()
        log_message(
            "[BREAKER] State snapshot - count={}, name={}, target={}".format(
                state.get("count"), state.get("name"), target_name
            ),
            1
        )
        if state["count"] < CYCLE_FAIL_LIMIT:
            log_message(
                "[BREAKER] Count {} below limit {}, breaker CLOSED".format(
                    state["count"], CYCLE_FAIL_LIMIT
                ),
                0
            )
            return False
        if state["name"] and target_name and state["name"] != str(target_name):
            log_message(
                "[BREAKER] Mismatch - state name '{}' != target '{}', breaker CLOSED".format(
                    state["name"], target_name
                ),
                2
            )
            return False
        log_message(f"[BREAKER] ALL CONDITIONS MET - breaker OPEN for [{target_name}]", 2)
        return True
    except Exception as e:
        log_message(
            "Tunnel Check: Breaker state evaluation exception: {}\n{}".format(
                e, traceback.format_exc()
            ),
            3
        )
        return False


def _session_requires_recovery(session_target):
    if not session_target:
        return False
    intentional_path = get_file_path("disconnect")
    if intentional_path is not None and os.path.exists(intentional_path) is True:
        return False
    conn_lock_path = get_file_path("connector_lock")
    if conn_lock_path is not None and os.path.exists(conn_lock_path) is True:
        return False
    return True


def _find_tunnel_iface():
    prefixes = get_dynamic_prefixes()
    log_message(f"[IFACE-SEARCH] Using prefixes: {prefixes}", 0)

    log_message("[IFACE-SEARCH] Attempting NM device discovery...", 0)
    nm_name, nm_device = get_nm_tunnel_device()
    log_message(f"[IFACE-SEARCH] NM result - name={nm_name}, device={nm_device}", 0)
    if nm_device:
        log_message(f"[IFACE-SEARCH] SUCCESS via NM: {nm_device}", 0)
        return str(nm_device)

    log_message("[IFACE-SEARCH] Attempting wg show discovery...", 0)
    try:
        res = subprocess.run(
            ["wg", "show", "interfaces"],
            text=True, capture_output=True, check=False, timeout=3.0
        )
        log_message(
            "[IFACE-SEARCH] wg show output: '{}' (rc={})".format(
                res.stdout.strip(), res.returncode
            ),
            0
        )
        if res.returncode == 0:
            for iface in res.stdout.split():
                if any(p in iface.lower() for p in prefixes):
                    log_message(f"[IFACE-SEARCH] MATCH via wg: {iface}", 0)
                    return str(iface)
    except subprocess.TimeoutExpired:
        log_message("[IFACE-SEARCH] wg show timed out", 2)
    except Exception as wg_err:
        log_message(
            "Tunnel Check: wg show discovery exception: {}\n{}".format(
                wg_err, traceback.format_exc()
            ),
            3
        )

    log_message("[IFACE-SEARCH] Attempting ip link discovery...", 0)
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
                    log_message(f"[IFACE-SEARCH] MATCH via ip link: {name}", 0)
                    return str(name)
        log_message("[IFACE-SEARCH] ip link found no prefix matches", 0)
    except subprocess.TimeoutExpired:
        log_message("[IFACE-SEARCH] ip link discovery timed out", 2)
    except Exception as ip_err:
        log_message(
            "Tunnel Check: ip link discovery exception: {}\n{}".format(
                ip_err, traceback.format_exc()
            ),
            3
        )

    log_message("[IFACE-SEARCH] All discovery methods exhausted, returning None", 0)
    return None


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
        log_message(f"[IFACE-STATE] Default interface reported: {current_default_iface}", 0)

        tunnel_missing_recovery = False
        if not current_default_iface:
            tunnel_iface = _find_tunnel_iface()
            if not tunnel_iface:
                session_target = get_active_vpn()
                if _session_requires_recovery(session_target):
                    log_message(
                        "Tunnel Check: Session state active but no tunnel interface present. "
                        "Entering recovery sequence.",
                        2
                    )
                    tunnel_missing_recovery = True
                    current_default_iface = None
                else:
                    log_message("Tunnel Check: No interface info available. Skipping check.", 0)
                    return
            else:
                current_default_iface = tunnel_iface
        else:
            is_tunnel_iface = any(p in current_default_iface.lower() for p in prefixes)
            if not is_tunnel_iface:
                tunnel_iface = _find_tunnel_iface()
                if not tunnel_iface:
                    session_target = get_active_vpn()
                    if _session_requires_recovery(session_target):
                        log_message(
                            "Tunnel Check: Session state active but no tunnel interface present. "
                            "Entering recovery sequence.",
                            2
                        )
                        tunnel_missing_recovery = True
                        current_default_iface = None
                    else:
                        log_message(
                            "Tunnel Check: No tunnel interface present. Nothing to verify.",
                            0
                        )
                        return
                else:
                    current_default_iface = tunnel_iface

        if tunnel_missing_recovery:
            tunnel_is_broken = True
        else:
            if not is_interface_active(current_default_iface):
                log_message("Tunnel Check: Tunnel interface exists but is inactive.", 0)
                return

            log_message(f"[PING] Testing connectivity to 1.1.1.1 via {current_default_iface}...", 0)
            tunnel_is_broken = False
            try:
                start_time = time.time()
                res = subprocess.run(
                    ["ping", "-c", "1", "-W", "2", "1.1.1.1"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                    timeout=3.0
                )
                elapsed = time.time() - start_time
                ping_out = res.stdout.decode("utf-8", errors="ignore").strip()[:200]
                ping_err = res.stderr.decode("utf-8", errors="ignore").strip()[:200]
                log_message(
                    "[PING] Result: rc={}, time={:.2f}s, out='{}', err='{}'".format(
                        res.returncode, elapsed, ping_out, ping_err
                    ),
                    0
                )
                if res.returncode != 0:
                    log_message(f"[PING] FAIL - non-zero exit code {res.returncode}", 2)
                    tunnel_is_broken = True
                else:
                    log_message(f"[PING] SUCCESS - received response in {elapsed:.2f}s", 0)
            except subprocess.TimeoutExpired:
                log_message("[PING] TIMEOUT - process execution exceeded 3s", 2)
                tunnel_is_broken = True
            except Exception as ping_err:
                log_message(
                    "Tunnel Check: Connection verification exception: {}\n{}".format(
                        ping_err, traceback.format_exc()
                    ),
                    3
                )
                tunnel_is_broken = True

        if not tunnel_is_broken:
            log_message("Tunnel Check: Link health verification successful. Tunnel is clear.", 0)
            if run_update_if_clear is True:
                log_message(
                    "Tunnel Check: Tunnel healthy - deferred update parked until "
                    "next broken-tunnel recovery cycle.",
                    0
                )
            return

        boot_target = get_active_vpn()
        log_message(f"[RECOVERY] Boot target from session state: {boot_target}", 1)

        if not boot_target:
            log_message(
                "Tunnel Check: Dead link detected but no session state to recover. "
                "Leaving interface untouched.",
                2
            )
            if not tunnel_missing_recovery:
                notify_orphaned_tunnel(current_default_iface)
            return

        if _breaker_open_for(boot_target):
            log_message(
                "Tunnel Check: Cycle-fail breaker open for [%s]. Taking dead tunnel "
                "down and clearing session state - no reconnect attempt." % boot_target, 2
            )
            if failure_dialog_allowed("breaker_open"):
                notify_breaker_open(boot_target)
                mark_failure_dialog_shown("breaker_open")
            recovery_ks_handled = False
            try:
                recovery_ks = ZeroHardcodeKillSwitch(vpn_server_ip="0.0.0.0")
                recovery_ks.enabled = True
                recovery_ks.disable(reason="breaker-teardown")
                recovery_ks_handled = True
            except Exception as fw_purge_err:
                log_message(
                    f"Tunnel Check: Breaker teardown firewall purge exception: {fw_purge_err}",
                    3
                )

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
            if current_default_iface is None:
                return is_interface_active(None)
            return is_interface_active(current_default_iface)

        while timeout > 0:
            if not _tunnel_still_active():
                break
            time.sleep(poll_interval)
            timeout -= poll_interval
        else:
            log_message(
                "Tunnel Check: Recovery wait expired - stale route or interface persists.",
                2
            )

        time.sleep(SANITY_SETTLE_DELAY / 1000.0)

        dns_timeout = 4.0
        dns_ready = False
        dns_attempts = 0
        log_message(f"[DNS] Verifying WAN DNS recovery, timeout={dns_timeout}s...", 0)
        while dns_timeout > 0:
            dns_attempts += 1
            try:
                start_dns = time.time()
                result = socket.gethostbyname("one.one.one.one")
                elapsed_dns = time.time() - start_dns
                log_message(
                    "[DNS] RESOLVED to {} in {:.2f}s (attempt {})".format(
                        result, elapsed_dns, dns_attempts
                    ),
                    0
                )
                dns_ready = True
                break
            except socket.gaierror as gai_err:
                log_message(f"[DNS] Gai error on attempt {dns_attempts}: {gai_err}", 3)
                time.sleep(0.2)
                dns_timeout -= 0.2
            except Exception as dns_err:
                log_message(
                    "Tunnel Check: DNS recovery exception: {}\n{}".format(
                        dns_err, traceback.format_exc()
                    ),
                    3
                )
                time.sleep(0.2)
                dns_timeout -= 0.2

        if not dns_ready:
            log_message(
                "[DNS] FAILED - all resolution attempts exhausted ({} attempts)".format(
                    dns_attempts
                ),
                2
            )

        if dns_ready:
            try:
                from vpn_core import check_for_updates
                check_for_updates("", force_despite_tunnel=True)
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

        def _report_reconnect(profile_label):
            meta_iface = get_active_interface()
            if meta_iface is None and current_default_iface is not None:
                meta_iface = current_default_iface
            log_message(f"[RECONNECT] Active interface post-connect: {meta_iface}", 0)
            ip, country = fetch_vpn_metadata(meta_iface)
            log_message(f"[RECONNECT] Metadata result - IP={ip}, Country={country}", 0)
            if ip and ip != "Unknown":
                log_message(
                    f"Tunnel Check: Profile link [{profile_label}] verified and "
                    f"re-established ({ip}).",
                    1
                )
                if HAS_GUI:
                    xbmcgui.Window(10000).setProperty('vpn_reconnected', profile_label)
                notify_tunnel_restored(profile_label, ip, country)
                clear_failure_dialogs()
            else:
                log_message(
                    f"Tunnel Check: Reconnect to [{profile_label}] completed but "
                    f"data path unverified. Deferring verdict to next health cycle.",
                    2
                )

        log_message(
            "[RECONNECT] Invoking connect_vpn for target={} sid={}".format(boot_target, sid),
            0
        )
        connect_ok = vpn_ops.connect_vpn(str(boot_target), str(sid), silent=True)

        if connect_ok is True:
            log_message("[RECONNECT] Connect returned OK, verifying metadata...", 0)
            _report_reconnect(boot_target)
        else:
            log_message(
                "[RECONNECT] FAILED - connect_vpn returned {}. State preserved for "
                "cycle-fail breaker evaluation.".format(connect_ok),
                2
            )
            retry_requested = False
            if failure_dialog_allowed("reconnect_failed"):
                retry_requested = ask_reconnect_retry(boot_target) is True
                mark_failure_dialog_shown("reconnect_failed")
            if retry_requested is True:
                log_message(
                    f"Tunnel Check: User requested immediate reconnect retry for "
                    f"[{boot_target}].",
                    1
                )
                retry_ok = vpn_ops.connect_vpn(str(boot_target), str(sid), silent=True)
                if retry_ok is True:
                    log_message("[RECONNECT] User-requested retry returned OK, verifying...", 0)
                    _report_reconnect(boot_target)
                else:
                    log_message(
                        "[RECONNECT] User-requested retry failed. Further retries governed "
                        "by the cycle-fail breaker.",
                        2
                    )
                    log_message(
                        f"Tunnel Check: Reconnect to [{boot_target}] was not completed. "
                        f"Further retries governed by the cycle-fail breaker.",
                        2
                    )
            else:
                log_message(
                    f"Tunnel Check: Reconnect to [{boot_target}] was not completed. "
                    f"Further retries governed by the cycle-fail breaker.",
                    2
                )

    except Exception as e:
        log_message(
            "Tunnel Check: Monitoring framework tracking exception: {}\n{}".format(
                e, traceback.format_exc()
            ),
            3
        )

    finally:
        kodi_env.clear_script_globals()


if __name__ == "__main__":
    run_tunnel_sanity_check()
