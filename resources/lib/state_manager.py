""" ./resources/lib/state_manager.py """
import os

CONFIG_DIR = os.path.expanduser("~/.config/wireguard")
PROFILE_DIR = os.path.expanduser("~/.kodi/userdata/addon_data/service.wireguard.manager.linux")

FILE_MAP = {
    'active': 'vpn_manager_active.txt',
    'manual': 'vpn_manual_active.txt',
    'reconnect': 'vpn_reconnect_count.txt',
    'reconnect_target': 'vpn_reconnect_target.txt',
    'disconnect': 'vpn_intentional_disconnect.txt',
    'blackout': 'vpn_blackout_active.lock',
    'pia_map': 'pia_name_map.json',
    'pia_cache': 'pia_token_cache.json',
    'pia_cooldown': '.pia_cooldown',
    'pia_sync_history': '.pia_sync_history',
    'mullvad_settings': 'mullvad_settings.ini',
    'mullvad_relays_cache': 'mullvad_relays_cache.json',
    'connector_lock': 'vpn_connector_active.lock',
    'notif_lock': 'vpn_notif_sent.lock',
    'cycle_fail_state': 'vpn_cycle_fail_state.json',
    'last_profile': 'vpn_last_profile.txt'
}


def ensure_directories():
    try:
        os.makedirs(PROFILE_DIR, exist_ok=True)
        os.makedirs(CONFIG_DIR, exist_ok=True)
    except Exception:
        pass


def get_file_path(key):
    if key not in FILE_MAP:
        return None
    ensure_directories()
    return os.path.join(PROFILE_DIR, FILE_MAP[key])


def clear_startup_states():
    ensure_directories()
    startup_keys = ['active', 'reconnect', 'reconnect_target']
    for key in startup_keys:
        path = get_file_path(key)
        if path is not None and os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass


def write_state(key, content):
    path = get_file_path(key)
    if path is None:
        return False
    try:
        with open(path, 'w') as f:
            f.write(str(content))
        return True
    except Exception:
        return False


def read_state(key):
    path = get_file_path(key)
    if path is None or not os.path.exists(path):
        return None
    try:
        with open(path, 'r') as f:
            return f.read().strip()
    except Exception:
        return None


def get_active_vpn():
    path = get_file_path('active')
    if path is not None and os.path.exists(path):
        try:
            with open(path, "r") as f:
                return f.read().strip() or None
        except Exception:
            return None
    return None


def set_active_vpn(name):
    path = get_file_path('active')
    if path is None:
        return
    try:
        if name:
            with open(path, "w") as f:
                f.write(name.strip())
        elif os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


ensure_directories()
