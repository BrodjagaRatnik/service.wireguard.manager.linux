""" resources/lib/vpn_config.py """
import os
import sys
import kodi_env
from logger import log_message

ADDON_DIR = kodi_env.ADDON_DIR
LIB_PATH = os.path.join(ADDON_DIR, 'resources', 'lib')

if ADDON_DIR not in sys.path:
    sys.path.insert(0, ADDON_DIR)

if LIB_PATH not in sys.path:
    sys.path.insert(0, LIB_PATH)


def get_hardware_model():
    try:
        if os.path.exists('/proc/device-tree/model'):
            with open('/proc/device-tree/model', 'r') as f:
                raw_data = f.read()
                clean_string = raw_data.replace('\x00', '')
                return clean_string.lower().strip()
    except Exception as e:
        log_message(f"Hardware check error: {e}", 3)
    return ""


MODEL_STRING = get_hardware_model()
PI5 = 'pi 5' in MODEL_STRING or 'raspberry pi 5' in MODEL_STRING
PI4 = 'pi 4' in MODEL_STRING or 'raspberry pi 4' in MODEL_STRING
PI3 = 'pi 3' in MODEL_STRING or 'raspberry pi 3' in MODEL_STRING
PI2 = 'pi 2' in MODEL_STRING or 'raspberry pi 2' in MODEL_STRING

PROP_SYNC_DELAY = 100
OS_RELEASE_DELAY = 15 if PI5 else (25 if PI4 else (35 if (PI3 or PI2) else 15))
CONN_POLL_INTERVAL = 500 if PI5 else (600 if PI4 else (400 if (PI3 or PI2) else 250))
ROUTE_PROP_DELAY = 15 if PI5 else (15 if PI4 else (25 if (PI3 or PI2) else 10))
DHCP_RECOVERY_DELAY = 10 if PI5 else (15 if PI4 else (25 if (PI3 or PI2) else 10))
VPN_CONNECTION_TIMEOUT = 500 if PI5 else (500 if PI4 else (500 if (PI3 or PI2) else 500))
WATCHDOG_HEARTBEAT = 1000 if PI5 else (1500 if PI4 else (1200 if (PI3 or PI2) else 500))
WATCHDOG_SETTLE_DELAY = 5000 if PI5 else (6000 if PI4 else (5000 if (PI3 or PI2) else 2500))
WATCHDOG_RECOVERY_DELAY = 2000 if PI5 else (2500 if PI4 else (2000 if (PI3 or PI2) else 1000))
HELPER_MAX_WAIT = 4000 if PI5 else (5000 if PI4 else (4500 if (PI3 or PI2) else 2500))
SHIELD_SLEEP_DELAY = 5000 if PI5 else (5000 if PI4 else (5000 if (PI3 or PI2) else 2500))
SYSTEMD_POLL_DELAY = 300 if PI5 else (400 if PI4 else (300 if (PI3 or PI2) else 150))
SERVICE_INIT_DELAY = 400 if PI5 else (600 if PI4 else (400 if (PI3 or PI2) else 200))
UI_BUFFER_DELAY_MENU = 50 if PI5 else (100 if PI4 else (100 if (PI3 or PI2) else 50))
CONNMAN_RESTART_DELAY = 100 if PI5 else (150 if PI4 else (100 if (PI3 or PI2) else 50))
SANITY_POLL_INTERVAL = 500 if PI5 else (1000 if PI4 else (1500 if PI3 or PI2 else 1000))
SANITY_SETTLE_DELAY = 500 if PI5 else (1000 if PI4 else (1500 if PI3 or PI2 else 1000))
CONNMAN_SETTLE_DELAY = 100 if PI5 else (100 if PI4 else (100 if (PI3 or PI2) else 100))
META_SETTLE_DELAY = 0.5 if PI5 else (0.5 if PI4 else (0.5 if (PI3 or PI2) else 1))
META_HTTP_ATTEMPTS = 2

try:
    import xbmc
    KODI_VERSION = xbmc.getInfoLabel("System.BuildVersion").split(".")
    HAS_KODI = True
except Exception as e:
    HAS_KODI = False
    err_msg = str(e)
    if "No module named 'xbmc'" in err_msg or "No module named 'xbmcaddon'" in err_msg:
        log_message("Background daemon initialization active (Kodi env absent).", 0)
    else:
        log_message(f"CRITICAL: vpn_config initialization failed: {err_msg}", 3)


class LProviderMap(dict):

    def __init__(self, data):
        super().__init__(data)
        self._loaded = False

    def _load_modules(self):
        if not self._loaded and HAS_KODI:
            self._loaded = True
            try:
                from providers import nordvpn, pia, mullvad, custom

                nord_dict = super().__getitem__(0)
                pia_dict = super().__getitem__(1)
                mullvad_dict = super().__getitem__(2)
                custom_dict = super().__getitem__(99)
                nord_dict["module"] = nordvpn
                pia_dict["module"] = pia
                mullvad_dict["module"] = mullvad
                custom_dict["module"] = custom

            except Exception as e:
                self._loaded = False
                log_message(f"Failed to load provider modules dynamically: {e}", 3)

    def __getitem__(self, key):
        self._load_modules()
        return super().__getitem__(key)

    def get(self, key, default=None):
        self._load_modules()
        return super().get(key, default)

    def values(self):
        self._load_modules()
        return super().values()

    def items(self):
        self._load_modules()
        return super().items()


PROVIDER_MAP = LProviderMap({
    0: {
        "name": "NordVPN",
        "api_url": "https://api.nordvpn.com/v1/servers/countries",
        "setting": "vpn_token",
        "countries_setting": "selected_countries",
        "prefix": "nord_",
        "matcher": "nord",
        "label": "Nord Token",
        "needs_file_check": True,
        "requires_endpoint_route": False,
        "ipv6_tunnel": False
    },
    1: {
        "name": "PIA",
        "api_url": "https://serverlist.piaservers.net/vpninfo/servers/v6",
        "setting": "pia_pass",
        "user_setting": "pia_user",
        "countries_setting": "selected_countries_pia",
        "prefix": "pia_",
        "matcher": "pia",
        "label": "PIA Credentials",
        "needs_file_check": True,
        "requires_endpoint_route": True,
        "ipv6_tunnel": False
    },
    2: {
        "name": "Mullvad",
        "api_url": "https://api.mullvad.net/public/relays/wireguard/v1",
        "setting": "account_number",
        "countries_setting": "filter",
        "prefix": "mullvad_",
        "extra_prefixes": ["mld"],
        "matcher": "mullvad",
        "label": "Mullvad Account",
        "needs_file_check": True,
        "requires_endpoint_route": False,
        "ipv6_tunnel": True
    },
    99: {
        "name": "Custom",
        "setting": "custom_path",
        "prefix": "custom_",
        "matcher": "custom",
        "label": "Config File",
        "needs_file_check": False,
        "requires_endpoint_route": False,
        "ipv6_tunnel": False
    }
})
