""" ./resources/lib/vpn_menu.py """
import kodi_env
import os
import sys
from vpn_config import (
    PROVIDER_MAP,
    UI_BUFFER_DELAY_MENU,
)
from logger import log_message
import vpn_ops
from state_manager import get_file_path, get_active_vpn, CONFIG_DIR

try:
    import xbmc
    import xbmcgui
    HAS_KODI_UI = True
except ImportError:
    HAS_KODI_UI = False


def inject_lib_path():
    addon_path = kodi_env.ADDON_DIR
    lib_path = os.path.join(addon_path, "resources", "lib")
    if lib_path not in sys.path:
        sys.path.append(lib_path)


def show_menu(media_path, provider_index):
    inject_lib_path()

    try:
        if not kodi_env.get_addon_instance() or not HAS_KODI_UI:
            log_message("Menu Launcher: Environment missing Kodi UI abstractions. Execution stopped.", 2)
            return

        raw_state = get_active_vpn()
        active_name = raw_state.lower().replace("_", "").replace(" ", "").strip() if raw_state else None

        menu_items = []
        mapping = []

        if raw_state:
            label_dis = f"[B][COLOR white]DISCONNECT[/COLOR] [COLOR yellow]({raw_state})[/COLOR][/B]"
            item_reset = xbmcgui.ListItem(label_dis)
            item_reset.setArt({"icon": os.path.join(media_path, "reset.png")})
            menu_items.append(item_reset)
            mapping.append("DISCONNECT")

        p_data = PROVIDER_MAP.get(int(provider_index))
        p_name = p_data.get("name", "").lower() if p_data else "unknown"
        file_prefix = p_data["prefix"].lower() if p_data else "nord_"

        if p_name == "mullvad":
            file_prefixes = (file_prefix, "mld_")
        else:
            file_prefixes = (file_prefix,)

        if os.path.exists(CONFIG_DIR):
            for f_name in sorted(os.listdir(CONFIG_DIR)):
                if f_name.startswith(file_prefixes) and f_name.endswith((".conf", ".config")):
                    profile_id = f_name.replace(".conf", "").replace(".config", "")

                    if f_name.startswith("custom_"):
                        clean_name = profile_id.replace("custom_", "").replace("_", " ").replace("-", " ")
                        display_name = f"Custom {clean_name.strip().title()}"
                    else:
                        display_name = profile_id.replace("_", " ").title()

                    file_path = os.path.join(CONFIG_DIR, f_name)
                    friendly_title = None
                    try:
                        with open(file_path, "r", encoding="utf-8") as cf:
                            for line in cf:
                                if line.startswith("# FriendlyName ="):
                                    friendly_title = line.split("=", 1)[-1].strip()
                                    break
                    except Exception:
                        pass

                    if friendly_title:
                        display_name = friendly_title

                    clean_display = display_name.lower().replace(" ", "")
                    is_active = False
                    if active_name:
                        is_active = (clean_display == active_name or profile_id.lower().replace("_", "") == active_name)

                    if is_active is True:
                        label = f"[B][COLOR ff00ff7f][CONNECTED][/COLOR] {display_name}[/B]"
                        icon_file = "vpn_on.png"
                    else:
                        label = f"[B][COLOR white]{display_name}[/COLOR][/B]"
                        icon_file = "vpn_off.png"

                    item = xbmcgui.ListItem(label)
                    item.setArt({"icon": os.path.join(media_path, icon_file)})
                    menu_items.append(item)
                    mapping.append((display_name, profile_id))

        if not raw_state and p_name != "custom":
            item_update = xbmcgui.ListItem("[B]Update, Regenerate [COLOR yellow]VPN Configs[/B][/COLOR]")
            item_update.setArt({"icon": os.path.join(media_path, "update.png")})
            menu_items.append(item_update)
            mapping.append("REGEN")

        title = f"{p_data['name']} Manager" if p_data else "VPN Manager"

        choice = xbmcgui.Dialog().select(title, menu_items, useDetails=True)
        if choice >= 0:
            action = mapping[choice]

            if action == "DISCONNECT":
                vpn_ops.disconnect_vpn(silent=False, flush_dns=True)
                xbmc.sleep(UI_BUFFER_DELAY_MENU)
                show_menu(media_path, provider_index)

            elif action == "REGEN":
                from vpn_core import run_update
                if run_update() is True:
                    show_menu(media_path, provider_index)

            else:
                target_name, target_sid = action
                clean_target = target_name.lower().replace(" ", "")
                if active_name and (clean_target == active_name or target_sid.lower().replace("_", "") == active_name):
                    return

                xbmcgui.Window(10000).setProperty("vpn_manual_session", "true")

                manual_path = get_file_path("manual")
                if manual_path is not None:
                    try:
                        with open(manual_path, "w") as f:
                            f.write(target_name)
                    except Exception as e:
                        log_message(f"Menu: Could not write manual flag: {e}", 2)

                xbmc.sleep(UI_BUFFER_DELAY_MENU)
                log_message(f"Menu: Manual connection requested for {target_name}", 1)
                vpn_ops.connect_vpn(target_name, target_sid)

    except Exception as e:
        err_msg = str(e)
        log_message(f"Menu Error Captured: {err_msg}", 3)

    finally:
        try:
            kodi_env.clear_script_globals()
        except Exception:
            pass
