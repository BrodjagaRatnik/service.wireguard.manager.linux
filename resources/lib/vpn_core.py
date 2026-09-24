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


def check_for_updates(media_path, force_despite_tunnel=False):
    global LAST_RUN_TIMESTAMP

    try:
        log_message(
            f"Core: Update check invoked (force_despite_tunnel={force_despite_tunnel}).",
            0
        )

        if time.localtime().tm_year < 2026:
            log_message("Core: Clock guard tripped - system year below 2026. Aborting.", 2)
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

        if has_tunnel and force_despite_tunnel is not True:
            log_message("Core: WireGuard VPN active. Postponing configuration update.", 0)
            return

        if is_playing_stream:
            log_message("Core: Active stream detected. Postponing configuration update.", 0)
            return

        addon_obj = kodi_env.get_addon_instance()
        if not addon_obj:
            log_message("Core: Addon instance unavailable in update context. Aborting.", 2)
            return

        provider_idx = addon_obj.getSettingInt("vpn_provider")
        p_data = PROVIDER_MAP.get(provider_idx)

        if not p_data:
            log_message(
                f"Core: No PROVIDER_MAP entry for provider index {provider_idx!r}. "
                f"Aborting update check.",
                2
            )
            return

        if not p_data.get("needs_file_check", False):
            log_message(
                f"Core: Provider [{p_data.get('prefix')}] needs no file check. Aborting.",
                0
            )
            return

        accepted_prefixes = [p_data["prefix"]]
        for extra_prefix in p_data.get("extra_prefixes", []):
            extra_entry = f"{extra_prefix}_"
            if extra_entry not in accepted_prefixes:
                accepted_prefixes.append(extra_entry)

        if os.path.exists(CONFIG_DIR):
            files = [
                f for f in os.listdir(CONFIG_DIR)
                if f.endswith(".conf") and any(
                    f.startswith(px) for px in accepted_prefixes
                )
            ]

            if not files:
                accepted_str = ", ".join(accepted_prefixes)
                log_message(
                    f"Core: No [{accepted_str}*.conf] files found in {CONFIG_DIR}. "
                    f"Aborting update check.",
                    2
                )
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
                log_message("Core: Clock rewind detected. Resetting update timestamp.", 1)
                addon_obj.setSetting("last_vpn_update_time", str(current_time))
                return

            oldest_mtime = None
            for conf_name in files:
                conf_path = os.path.join(CONFIG_DIR, conf_name)
                try:
                    conf_mtime = int(os.path.getmtime(conf_path))
                except OSError:
                    continue
                if oldest_mtime is None or conf_mtime < oldest_mtime:
                    oldest_mtime = conf_mtime

            if oldest_mtime is None:
                log_message("Core: Could not read any config mtimes. Aborting update check.", 2)
                return

            file_age_seconds = current_time - oldest_mtime

            log_msg = (
                f"Core: current_time={current_time}, "
                f"last_update_time={last_update_time}, "
                f"oldest_file_age={file_age_seconds}, "
                f"max_age={max_age_seconds}"
            )
            log_message(log_msg, 0)

            if file_age_seconds <= max_age_seconds:
                log_message("Core: Update skipped. Configurations on disk are still fresh.", 0)
                return

            cooldown_remaining = last_update_time + max_age_seconds - current_time
            if cooldown_remaining > 0:
                log_msg = (
                    f"Core: Update cooldown active for {cooldown_remaining}s "
                    f"(last run {last_update_time})."
                )
                log_message(log_msg, 1)
                return

            log_message("Core: Configs stale and cooldown expired. Running provider update.", 1)
            update_successful = run_update(silent=True)
            addon_obj.setSetting("last_vpn_update_time", str(current_time))

            if update_successful:
                LAST_RUN_TIMESTAMP = current_time
                try:
                    new_age = current_time - int(
                        os.path.getmtime(os.path.join(CONFIG_DIR, files[0]))
                    )
                    if new_age < 30:
                        log_message("Core: Update successful. File timestamps updated.", 0)
                    else:
                        log_message("Core: Update completed. Server files identical.", 0)
                except Exception:
                    pass
            else:
                log_message("Core: Remote configuration update failed.", 2)

        else:
            log_message(f"Core: CONFIG_DIR [{CONFIG_DIR}] does not exist. Aborting.", 2)

    except Exception as e:
        log_message(f"Core: Update VPN configurations check failure: {e}", 3)
    finally:
        kodi_env.clear_script_globals()


def run_update(direct_token=None, force_provider=None, silent=False):
    return execute_vpn_update(direct_token=direct_token, force_provider=force_provider, silent=silent)
