""" ./resources/lib/service_loop.py """
import os
import sys
import xbmc
import xbmcgui
from logger import log_message
from vpn_config import WATCHDOG_HEARTBEAT, PROVIDER_MAP, CONNMAN_SETTLE_DELAY
from state_manager import get_file_path, get_active_vpn, set_active_vpn, CONFIG_DIR
from vpn_utils import get_dynamic_prefixes
from service_matcher import MATCHERS
from service_resolver import resolve_service_id
from resources.scripts.killswitch import detect_and_recover_orphan_chain


def execute_monitor_loop(instance):
    if xbmc.Player().isPlayingVideo():
        instance.cleanup_count = 0
        return

    active_now = get_active_vpn()

    if not active_now:
        try:
            if os.path.exists('/sys/class/net/'):
                prefixes = tuple(get_dynamic_prefixes())
                wg_ifs = [i for i in os.listdir('/sys/class/net/') if i.startswith(prefixes)]

                if wg_ifs:
                    active_ifs = []
                    for iface in wg_ifs:
                        try:
                            with open(f'/sys/class/net/{iface}/operstate', 'r') as f:
                                if 'up' in f.read().lower():
                                    active_ifs.append(iface)
                        except Exception:
                            pass

                    if active_ifs:
                        if os.path.exists(CONFIG_DIR):
                            configs = [
                                c.replace('.config', '').replace('.conf', '')
                                for c in os.listdir(CONFIG_DIR)
                                if c.endswith(('.config', '.conf'))
                            ]
                            for c in configs:
                                if any(c in i or i in c for i in active_ifs):
                                    active_now = c
                                    break

                        if not active_now:
                            active_now = str(active_ifs)
        except Exception as e:
            log_message(f"Service Loop: Kernel interface scan failed: {e}", 1)

    manual_path = get_file_path('manual')
    prop_val = str(xbmcgui.Window(10000).getProperty('vpn_manual_session')).strip().lower()
    is_manual = (
        (manual_path is not None and os.path.exists(manual_path) is True)
        or (bool(prop_val) and prop_val != 'false')
    )
    is_home = xbmc.getCondVisibility("Window.IsActive(home) | Window.IsActive(10000)")
    plugin = xbmc.getInfoLabel("Container.PluginName")
    folder = xbmc.getInfoLabel("Container.FolderPath")

    if is_home and is_manual:
        instance.cleanup_count = 0
        return

    match_found = False
    is_addon_active = plugin.startswith("plugin.video.") or (folder and "plugin.video." in folder.lower())

    if not is_home and is_addon_active:
        for i in range(1, 9):
            target = instance._ADDON.getSetting(f"map_{i}_addon")
            vpn_target = instance._ADDON.getSetting(f"vpn_{i}_name")

            if target and (target in folder or target == plugin):
                if not vpn_target or not active_now:
                    is_match = False
                else:
                    try:
                        p_id = int(instance._ADDON.getSettingInt("vpn_provider") or 0)
                    except Exception:
                        p_id = 0

                    p_data = PROVIDER_MAP.get(p_id, {})
                    v_low = str(vpn_target).lower()
                    match_fn = None
                    matcher_key = str(p_data.get("matcher", "")).lower()
                    if matcher_key in MATCHERS:
                        match_fn = MATCHERS[matcher_key]
                    else:
                        for key, fn in MATCHERS.items():
                            if key in v_low:
                                match_fn = fn
                                break
                            if key in str(p_data.get("prefix", "")).lower():
                                match_fn = fn
                                break
                    is_match = match_fn(vpn_target, active_now) if match_fn else False

                if is_match is True:
                    match_found = True
                    break

                fail_count = getattr(instance, "switch_fail_count", 0)
                if fail_count >= 3:
                    log_message(
                        f"Service Loop: Target {vpn_target} failed to resolve "
                        f"{fail_count} times. Blocking further attempts this visit.", 2
                    )
                    match_found = True
                    break

                log_message(f"Service Loop: Switching location map path to target: {vpn_target}.", 1)

                xbmcgui.Window(10000).setProperty('vpn_manual_session', 'false')
                if manual_path is not None and os.path.exists(manual_path) is True:
                    try:
                        os.remove(manual_path)
                    except Exception:
                        pass

                instance.vpn_ops.disconnect_vpn(silent=True, flush_dns=False)

                if CONNMAN_SETTLE_DELAY > 0:
                    xbmc.sleep(CONNMAN_SETTLE_DELAY)

                if "resources.lib.providers.pia_utils" in sys.modules:
                    try:
                        pia_mod = sys.modules["resources.lib.providers.pia_utils"]
                        if hasattr(pia_mod, "pia_token_cache"):
                            pia_mod.pia_token_cache = {}
                    except Exception:
                        pass

                sid = resolve_service_id(instance._ADDON, vpn_target)
                if sid:
                    connect_ok = instance.vpn_ops.connect_vpn(str(vpn_target), str(sid), silent=True)
                    if connect_ok:
                        instance.switch_fail_count = 0
                    else:
                        instance.switch_fail_count = fail_count + 1
                        log_message(
                            f"Service Loop: Profile {vpn_target} resolved to {sid} but the "
                            f"connection failed (switch attempt {instance.switch_fail_count}).",
                            2
                        )
                        try:
                            detect_and_recover_orphan_chain()
                        except Exception:
                            pass
                    match_found = True
                else:
                    instance.switch_fail_count = fail_count + 1
                    err_msg = (
                        f"Service Loop: Target ID for profile {vpn_target} not found "
                        f"(attempt {instance.switch_fail_count})."
                    )
                    log_message(err_msg, 3)
                break

    if not match_found and active_now and not is_manual:
        instance.cleanup_count += 1

        try:
            user_timeout_sec = float(instance._ADDON.getSettingInt("home_timeout_sec") or 5)
        except Exception:
            user_timeout_sec = 5.0

        elapsed_time_sec = instance.cleanup_count * (WATCHDOG_HEARTBEAT / 1000.0)

        if elapsed_time_sec >= user_timeout_sec:
            instance.cleanup_count = 0
            log_msg = f"Service Loop: Home timeout reached. Disconnecting profile [{active_now}]."
            log_message(log_msg, 1)

            xbmcgui.Window(10000).setProperty('vpn_manual_session', 'false')
            if manual_path is not None and os.path.exists(manual_path) is True:
                try:
                    os.remove(manual_path)
                except Exception:
                    pass

            set_active_vpn(None)
            instance.vpn_ops.disconnect_vpn(silent=False, flush_dns=True)
    else:
        instance.cleanup_count = 0
