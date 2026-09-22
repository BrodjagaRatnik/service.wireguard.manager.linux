""" ./resources/lib/service_updater.py """
import kodi_env
import os
import sys
from logger import log_message
from state_manager import get_file_path, CONFIG_DIR
from vpn_config import PROVIDER_MAP

_previous_snapshot = None


def inject_lib_path():
    addon_dir = kodi_env.ADDON_DIR
    lib_path = os.path.join(addon_dir, "resources", "lib")
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)


def _collect_watched_settings():
    keys = {"vpn_provider"}
    for provider_data in PROVIDER_MAP.values():
        for setting_attr in ("setting", "user_setting", "countries_setting"):
            setting_key = provider_data.get(setting_attr)
            if setting_key:
                keys.add(setting_key)
    return sorted(keys)


def _read_settings_snapshot(addon, watched_keys):
    return {key: addon.getSetting(key) for key in watched_keys}


def _snapshot_has_changes(previous, current):
    if previous is None:
        return True
    return any(previous[key] != current[key] for key in current)


def handle_settings_update(addon):
    inject_lib_path()
    global _previous_snapshot

    try:
        notif_lock = get_file_path("notif_lock")
        if notif_lock is not None and os.path.exists(notif_lock) is True:
            try:
                os.remove(notif_lock)
            except Exception:
                pass

        if addon.getSettingBool("first_run") is False:
            return

        watched_keys = _collect_watched_settings()
        current_snapshot = _read_settings_snapshot(addon, watched_keys)
        if _snapshot_has_changes(_previous_snapshot, current_snapshot) is False:
            return

        provider_id = addon.getSettingInt("vpn_provider")
        provider_data = PROVIDER_MAP.get(provider_id)

        if provider_data is None:
            log_message(
                f"Service Updater: No PROVIDER_MAP entry for provider id "
                f"[{provider_id}]. Skipping dispatch.",
                2
            )
            _previous_snapshot = current_snapshot
            return

        provider_module = provider_data.get("module")

        if not hasattr(provider_module, "handle_settings_change"):
            _previous_snapshot = current_snapshot
            return

        try:
            provider_module.handle_settings_change(addon, CONFIG_DIR)
        except Exception as dispatch_err:
            log_message(
                f"Service Updater: Provider settings update failed: {dispatch_err}",
                3
            )
        finally:
            _previous_snapshot = _read_settings_snapshot(addon, watched_keys)

    finally:
        kodi_env.clear_script_globals()
