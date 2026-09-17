""" ./resources/lib/service_launcher.py """
import kodi_env
import sys
import os
import time
import threading
import dialog
import subprocess
import vpn_ops
from logger import log_message
from vpn_config import PI2, PI3, PI4, PI5, WATCHDOG_HEARTBEAT, WATCHDOG_SETTLE_DELAY
from service import run_watchdog
from service_updater import handle_settings_update
from service_resolver import resolve_service_id
from service_loop import execute_monitor_loop
from vpn_core import check_for_updates
from tunnel_checker import run_tunnel_sanity_check
from state_manager import (
    get_file_path, set_active_vpn, write_state, read_state, CONFIG_DIR,
    get_active_vpn
)
from vpn_utils import get_active_interface, get_dynamic_prefixes

try:
    import xbmc
    import xbmcgui
    HAS_KODI_MONITOR = True
except ImportError:
    HAS_KODI_MONITOR = False

try:
    from setup_helper import ensure_setup, migrate_legacy_watchdog_unit
except ImportError:
    from setup_utils import ensure_setup
    migrate_legacy_watchdog_unit = None


def _match_config_name(token):
    if not token:
        return None
    try:
        configs = [c for c in os.listdir(CONFIG_DIR) if c.endswith(('.conf', '.config'))]
    except Exception:
        return None
    for c in configs:
        stem = c.replace('.config', '').replace('.conf', '')
        if stem == token or token in stem or stem in token:
            return stem
    return None


def _restore_manual_property_from_disk():
    try:
        if read_state('manual') == 'true':
            if HAS_KODI_MONITOR:
                xbmcgui.Window(10000).setProperty('vpn_manual_session', 'true')
            log_message("Service Launcher: Manual session property restored from disk state.", 0)
    except Exception as restore_err:
        log_message(f"Service Launcher: Manual property restore error: {restore_err}", 2)


if HAS_KODI_MONITOR:

    class WGManagerService(xbmc.Monitor):

        def __init__(self, addon, vpn_ops_mod):
            super().__init__()
            self._ADDON = addon
            self.vpn_ops = vpn_ops_mod
            self.last_bg_check_time = time.time()
            self.cleanup_count = 0
            self.last_tunnel_check_time = time.time()
            self._last_profile_seen = None

            if PI5:
                hardware = "Raspberry Pi 5"
            elif PI4:
                hardware = "Raspberry Pi 4"
            elif PI3:
                hardware = "Raspberry Pi 3"
            elif PI2:
                hardware = "Raspberry Pi 2"
            else:
                hardware = "Generic Device"

            log_message(f"Service Launcher: Hardware timings loaded for {hardware}", 1)
            log_message("Service Launcher: Monitor Service Initialized & Ready", 1)

        def onSettingsChanged(self):
            handle_settings_update(self._ADDON)

            try:
                from wm_utils import encrypt_setting_to_base64
                encrypt_setting_to_base64("pia_pass")
                encrypt_setting_to_base64("account_number")

            except Exception as e:
                log_err = f"Service Launcher: Settings encryption helper unavailable: {e}"
                log_message(log_err, 2)

        def get_service_id_by_name(self, name):
            return resolve_service_id(self._ADDON, name)

        def _record_last_profile(self):
            try:
                if self._ADDON.getSettingBool("auto_connect") is False:
                    return
                active_now = get_active_vpn()
                if active_now == self._last_profile_seen:
                    return
                self._last_profile_seen = active_now
                if not active_now:
                    return

                sid = None
                iface = get_active_interface()
                prefixes = tuple(get_dynamic_prefixes())
                if iface and any(px in iface.lower() for px in prefixes):
                    if os.path.exists(os.path.join(CONFIG_DIR, f"{iface}.conf")):
                        sid = iface
                if sid is None:
                    sid = _match_config_name(active_now)

                if sid:
                    write_state('last_profile', sid)
                    log_message(f"Service Launcher: Last used profile recorded [{sid}]", 0)
            except Exception as rec_err:
                log_message(f"Service Launcher: Last-profile tracking error: {rec_err}", 2)

        def run_loop(self):
            execute_monitor_loop(self)
            self._record_last_profile()
            current_time = time.time()
            addon_path = kodi_env.ADDON_DIR
            media_path = os.path.join(addon_path, "resources", "media")

            try:
                hours = float(self._ADDON.getSettingNumber("update_interval_hours"))
                interval_sec = hours * 3600.0
            except Exception:
                try:
                    hours = float(self._ADDON.getSetting("update_interval_hours"))
                    interval_sec = hours * 3600.0
                except Exception:
                    interval_sec = 86400.0

            if (current_time - self.last_bg_check_time) >= interval_sec:
                self.last_bg_check_time = current_time

                has_tunnel = False
                active_iface = get_active_interface()
                if active_iface:
                    prefixes = get_dynamic_prefixes()
                    if any(px in active_iface.lower() for px in prefixes):
                        has_tunnel = True

                if has_tunnel is True:
                    log_message("Service Launcher: Tunnel is active. Deferring update to tunnel sanity check.", 0)
                    try:
                        threading.Thread(
                            target=run_tunnel_sanity_check,
                            args=(True,),
                            daemon=True
                        ).start()
                    except Exception as defer_err:
                        log_err = f"Service Launcher: Deferred update invocation failed: {defer_err}"
                        log_message(log_err, 3)
                else:
                    try:
                        log_message("Service Launcher: No active tunnel. Executing scheduled update.", 0)
                        check_for_updates(media_path)
                    except Exception as e:
                        log_err = f"Service Launcher: Update verification failure: {e}"
                        log_message(log_err, 3)

            if (current_time - self.last_tunnel_check_time) >= 300.0:
                self.last_tunnel_check_time = current_time
                if self._ADDON.getSettingBool("check_tunnel"):
                    try:
                        threading.Thread(target=run_tunnel_sanity_check, daemon=True).start()
                    except Exception as e:
                        log_err = f"Service Launcher: Tunnel health tracking exception: {e}"
                        log_message(log_err, 3)


def _process_leftover_tunnel(addon_obj, boot_target):
    try:
        scripts_path = os.path.join(kodi_env.ADDON_DIR, "resources", "scripts")
        if scripts_path not in sys.path:
            sys.path.insert(0, scripts_path)
        from killswitch import purge_stale_killswitch
        purge_stale_killswitch()
    except Exception as ks_err:
        log_message(f"Service Launcher: Killswitch purge skipped: {ks_err}", 2)

    leftover_iface = get_active_interface()

    if leftover_iface is None:
        return (None, None)

    disconnect_on_start = True
    try:
        disconnect_on_start = addon_obj.getSettingBool("disconnect_on_start")
    except Exception:
        pass

    if disconnect_on_start is False:
        session = boot_target or leftover_iface
        try:
            set_active_vpn(session)
            write_state('idle', 'false')
        except Exception:
            pass
        _restore_manual_property_from_disk()
        log_message(
            f"Service Launcher: disconnect_on_start disabled. Previous tunnel "
            f"[{session}] kept active at startup.", 1
        )
        return ("kept", session)

    try:
        subprocess.run(
            ["nmcli", "connection", "down", leftover_iface],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
        )
    except Exception:
        pass

    try:
        set_active_vpn("")
        write_state('idle', 'false')
    except Exception:
        pass

    log_message(
        f"Service Launcher: disconnect_on_start enabled. Leftover tunnel "
        f"[{leftover_iface}] torn down for clean startup.", 1
    )
    return ("disconnected", leftover_iface)


def _maybe_auto_connect(addon_obj, action):
    try:
        if addon_obj.getSettingBool("auto_connect") is False:
            return
        if action == "kept":
            log_message(
                "Service Launcher: auto_connect enabled. Previous tunnel kept "
                "active at startup - no reconnect needed.", 1
            )
            return

        sid = read_state('last_profile')
        if not sid:
            log_message(
                "Service Launcher: auto_connect enabled but no last used "
                "profile recorded yet.", 1
            )
            return
        if not os.path.exists(os.path.join(CONFIG_DIR, f"{sid}.conf")):
            log_message(
                f"Service Launcher: auto_connect profile [{sid}] no longer "
                f"exists. Skipping.", 2
            )
            return

        vpn_name = None
        try:
            from vpn_utils import read_friendly_name
            vpn_name = read_friendly_name(sid)
        except Exception:
            vpn_name = None
        if not vpn_name:
            vpn_name = sid

        log_message(
            f"Service Launcher: auto_connect reconnecting last used "
            f"profile [{sid}]", 1
        )
        connected = vpn_ops.connect_vpn(vpn_name, sid, silent=False)
        if connected is True:
            write_state('manual', 'true')
            try:
                if HAS_KODI_MONITOR:
                    xbmcgui.Window(10000).setProperty('vpn_manual_session', 'true')
            except Exception:
                pass
            log_message(
                f"Service Launcher: auto_connect session [{sid}] registered "
                f"as manual to protect it from mapped-session timeouts.", 1
            )
    except Exception as ac_err:
        log_message(f"Service Launcher: auto_connect failed: {ac_err}", 2)


def _rotate_standalone_log():
    script_path = os.path.dirname(__file__)
    addon_id, _addon_ver = __import__('logger').get_addon_metadata()
    data_dir = os.path.normpath(
        os.path.join(script_path, "..", "..", "..", "..", "userdata", "addon_data", addon_id)
    )
    current_log = os.path.join(data_dir, "standalone_wm.log")
    old_log = os.path.join(data_dir, "standalone_wm.log.old")

    try:
        if os.path.exists(old_log):
            os.remove(old_log)
        if os.path.exists(current_log):
            os.rename(current_log, old_log)
    except Exception:
        pass


def start():
    addon_obj = kodi_env.get_addon_instance()
    if not addon_obj or not HAS_KODI_MONITOR:
        log_message("Service Launcher: Abstractions missing. Background monitoring disabled.", 2)
        kodi_env.clear_script_globals()
        return

    _rotate_standalone_log()

    path = kodi_env.ADDON_DIR

    if addon_obj.getSettingBool("first_run") is False:
        if ensure_setup(path, silent=True) is True:
            addon_obj.setSettingBool("first_run", True)
            xbmc.executebuiltin("Container.Refresh")

    try:
        monitor = WGManagerService(addon_obj, vpn_ops)
    except Exception as e:
        log_message(f"Service Launcher: Monitor failed to start: {e}", 3)
        return

    boot_target = None
    state_file = get_file_path("active")

    if state_file is not None and os.path.exists(state_file) is True:
        try:
            with open(state_file, 'r') as f:
                boot_target = f.read().strip() or None
            if boot_target:
                log_message(f"Service Launcher: Discovered active file target: {boot_target}", 0)
        except Exception:
            boot_target = None

    action, session = _process_leftover_tunnel(addon_obj, boot_target)

    try:
        from vpn_utils import read_friendly_name

        if action == "disconnected":
            if boot_target:
                dialog.notify_startup_disconnected(read_friendly_name(boot_target))
            else:
                dialog.notify_generic(
                    "WireGuard Manager",
                    "Leftover tunnel closed for clean startup.",
                    5000
                )
        elif action == "kept":
            dialog.notify_session_available(read_friendly_name(session))
        elif boot_target:
            log_message(
                f"Service Launcher: Previous session [{boot_target}] found. "
                "No tunnels at startup - waiting for user action.", 1
            )
            dialog.notify_session_available(read_friendly_name(boot_target))

    except Exception:
        pass

    _maybe_auto_connect(addon_obj, action)

    if migrate_legacy_watchdog_unit is not None:
        migrate_legacy_watchdog_unit()

    watchdog_thread = None
    try:
        watchdog_thread = threading.Thread(
            target=run_watchdog,
            args=(monitor.abortRequested,),
            daemon=True,
            name="wg-manager-watchdog"
        )
        watchdog_thread.start()
        log_message("Service Launcher: Integrated watchdog thread started.", 1)
    except Exception as wd_err:
        log_message(f"Service Launcher: Integrated watchdog start failure: {wd_err}", 3)

    try:
        hb = WATCHDOG_HEARTBEAT / 1000.0
    except Exception:
        hb = 1.0

    try:
        while monitor.abortRequested() is False:
            monitor.run_loop()
            if monitor.waitForAbort(hb) is True:
                break
    finally:
        if watchdog_thread is not None and watchdog_thread.is_alive():
            join_window = (WATCHDOG_HEARTBEAT + WATCHDOG_SETTLE_DELAY) / 1000.0 + 2.0
            watchdog_thread.join(timeout=join_window)
        del monitor
        kodi_env.clear_script_globals()


if __name__ == '__main__':
    start()
