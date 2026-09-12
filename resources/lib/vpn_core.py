""" ./resources/lib/vpn_core.py """
import kodi_env
import os
import time
from logger import log_message
from vpn_core_upd import run_update as execute_vpn_update
from vpn_config import PROVIDER_MAP
from vpn_utils import get_active_interface, get_dynamic_prefixes
from state_manager import CONFIG_DIR


try:
    import xbmc
    HAS_KODI = True
except ImportError:
    HAS_KODI = False

LAST_RUN_TIMESTAMP = 0


def get_addon_path():
    return kodi_env.ADDON_DIR


def check_for_updates(media_path):
    global LAST_RUN_TIMESTAMP

    try:
        if time.localtime().tm_year < 2026:
            return

        is_playing_stream = False
        if HAS_KODI and xbmc.Player().isPlaying():
            playing_file = xbmc.Player().getPlayingFile()
            stream_protocols = ["http://", "https://", "rtmp://", "pvr://"]
            is_playing_stream = any(playing_file.startswith(p) for p in stream_protocols)

        active_iface = get_active_interface()
        prefixes = get_dynamic_prefixes()
        has_tunnel = bool(active_iface and any(
            px in active_iface.lower() for px in prefixes
        ))

        if has_tunnel or is_playing_stream:
            reason = "WireGuard VPN active" if has_tunnel else "Active stream detected"
            log_message(f"Core: {reason}. Postponing configuration update.", 0)
            return

        addon_obj = kodi_env.get_addon_instance()
        if not addon_obj:
            return

        provider_idx = addon_obj.getSettingInt("vpn_provider")
        p_data = PROVIDER_MAP.get(provider_idx)

        if not p_data or not p_data.get("needs_file_check", False):
            return

        file_prefix = p_data["prefix"]

        if os.path.exists(CONFIG_DIR):
            files = [
                f for f in os.listdir(CONFIG_DIR)
                if f.startswith(file_prefix) and f.endswith(".conf")
            ]

            if not files:
                return

            try:
                slider_val = addon_obj.getSetting("update_interval_hours")
                slider_hours = int(float(slider_val)) if slider_val else 24
                if slider_hours <= 0:
                    slider_hours = 24
            except ValueError:
                slider_hours = 24

            max_age_seconds = slider_hours * 3600
            current_time = int(time.time())

            try:
                last_update_val = addon_obj.getSetting("last_vpn_update_time")
                last_update_time = int(last_update_val) if last_update_val else 0
            except ValueError:
                last_update_time = 0

            if current_time < last_update_time:
                addon_obj.setSetting("last_vpn_update_time", str(current_time))
                return

            first_file_path = os.path.join(CONFIG_DIR, files[0])
            file_age_seconds = current_time - int(os.path.getmtime(first_file_path))

            log_msg = (
                f"Core: current_time={current_time}, "
                f"last_update_time={last_update_time}, "
                f"file_age={file_age_seconds}, "
                f"max_age={max_age_seconds}"
            )
            log_message(log_msg, 0)

            if file_age_seconds <= max_age_seconds:
                log_message("Core: Update skipped. Configurations on disk are still fresh.", 0)
                return

            update_successful = run_update(silent=True)
            addon_obj.setSetting("last_vpn_update_time", str(current_time))

            if update_successful:
                LAST_RUN_TIMESTAMP = current_time
                try:
                    new_age = current_time - int(os.path.getmtime(first_file_path))
                    if new_age < 30:
                        log_message("Core: Update successful. File timestamps updated.", 0)
                    else:
                        log_message("Core: Update completed. Server files identical.", 0)
                except Exception:
                    pass
            else:
                log_message("Core: Remote configuration update failed.", 2)

    except Exception as e:
        log_message(f"Core: Update VPN configurations check failure: {e}", 3)
    finally:
        kodi_env.clear_script_globals()


def run_update(direct_token=None, force_provider=None, silent=False):
    return execute_vpn_update(direct_token=direct_token, force_provider=force_provider, silent=silent)
