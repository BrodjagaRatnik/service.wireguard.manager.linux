""" ./resources/lib/main_launcher.py """
import kodi_env
import builtins
import os
import sys
import time
from logger import log_message
from providers import custom
from vpn_config import PROVIDER_MAP
from vpn_core import run_update
from state_manager import get_file_path, CONFIG_DIR
import dialog

try:
    import xbmcgui
    import xbmcvfs
    HAS_GUI_IMPORTS = True
except ImportError:
    HAS_GUI_IMPORTS = False

builtins.log_event = log_message


def _write_notification_lock():
    notification_lock = get_file_path("notif_lock")
    if notification_lock is None or os.path.exists(notification_lock):
        return notification_lock is not None and not os.path.exists(notification_lock)
    try:
        lock_dir = os.path.dirname(notification_lock)
        if not os.path.exists(lock_dir):
            os.makedirs(lock_dir)
        with open(notification_lock, "w") as f:
            f.write("locked")
        return True
    except Exception as e:
        log_message(f"Main Launcher: Failed to create notification lock: {e}", 3)
        return False


def run(argv):
    addon_obj = kodi_env.get_addon_instance()

    if not addon_obj or not HAS_GUI_IMPORTS:
        log_message("Main Launcher: Environment missing Kodi abstractions. Execution stopped.", 2)
        return

    try:
        addon_path = kodi_env.ADDON_DIR
        media_path = os.path.join(addon_path, "resources", "media")

        args_str = "|".join(argv).lower()

        commands = [
            "status", "restart", "clear", "regen",
            "choose_countries", "mode=country_selector", "mode=list_assets",
            "mode=dnsleaktest", "cleanup", "mode=tos", "mode=disclaimer",
            "mode=import_token", "mode=import_creds", "mode=import_custom_browser",
            "show_codes", "mode=net_reset", "mode=import_mullvad"
        ]

        if any(cmd in args_str for cmd in commands):

            provider = addon_obj.getSettingInt("vpn_provider")
            for p_idx in PROVIDER_MAP:
                if f",{p_idx}" in args_str:
                    provider = p_idx
                    break

            if provider == -1:
                provider = 0

            if any(cmd in args_str for cmd in ["status", "restart", "clear"]):
                import service_control
                service_control.control_service()

            elif "regen" in args_str:
                if run_update() is True:
                    dialog.notify_regen_success()

            elif any(cmd in args_str for cmd in ["choose_countries", "mode=country_selector"]):
                scripts_path = os.path.join(addon_path, "resources", "scripts")
                if scripts_path not in sys.path:
                    sys.path.insert(0, scripts_path)
                import country_selector
                country_selector.run()

            elif "mode=list_assets" in args_str:
                scripts_path = os.path.join(addon_path, "resources", "scripts")
                if scripts_path not in sys.path:
                    sys.path.insert(0, scripts_path)
                import list_assets
                list_assets.run_wizard()

            elif "import_token" in args_str:
                p_data = PROVIDER_MAP.get(provider)

                if not p_data or "setting" not in p_data or "user_setting" in p_data:
                    try:
                        time.sleep(0.1)
                    except Exception as e:
                        log_message(f"Main Launcher: Token import pause failure: {e}", 3)
                    dialog.notify_action_required(
                        "Selection cached. You MUST press 'OK' in the main settings menu to apply changes!"
                    )
                else:
                    token_file = xbmcgui.Dialog().browse(1, "Select Token", "local", ".txt|.key")
                    if token_file:
                        f = xbmcvfs.File(token_file, "r")
                        content = f.read()
                        f.close()

                        if isinstance(content, bytes):
                            content = content.decode("utf-8")
                            content = content.strip()

                        addon_obj.setSetting(p_data["setting"], content)
                        log_message("Imported Token", 0)
                        run_update(direct_token=content)

                        if _write_notification_lock():
                            dialog.notify_action_required(
                                "Selection cached. You [B]MUST[/B] press [B]'OK'[/B] in settings menu!"
                            )
                    else:
                        log_message("Main Launcher: Token import cancelled by user", 0)

            elif "import_creds" in args_str:
                p_user_setting = "pia_user"
                p_setting = "pia_pass"

                has_gls = hasattr(addon_obj, "getLocalizedString")
                heading = addon_obj.getLocalizedString(32048) if has_gls else "Select Credentials File"
                token_file = xbmcgui.Dialog().browse(1, heading, "local", ".txt")
                if token_file:
                    f = xbmcvfs.File(token_file, "r")
                    content = f.read()
                    f.close()

                    if isinstance(content, bytes):
                        content = content.decode("utf-8")

                    lines = [line.strip() for line in content.splitlines() if line.strip()]

                    if len(lines) >= 2:
                        import base64
                        user = lines[0]
                        pwd = lines[1]

                        try:
                            base64.b64decode(pwd, validate=True)
                            encoded_pwd = pwd
                        except Exception:
                            enc_bytes = base64.b64encode(pwd.encode("utf-8"))
                            encoded_pwd = enc_bytes.decode("utf-8")

                        addon_obj.setSetting(p_user_setting, user)
                        addon_obj.setSetting(p_setting, encoded_pwd)

                        log_msg = f"Credentials saved for {user}. Starting update..."
                        log_message(log_msg, 1)

                        run_update(direct_token=encoded_pwd)

                        dialog.notify_action_required(
                            "Selection cached. You [B]MUST[/B] press [B]'OK'[/B] in settings menu!"
                        )
                    else:
                        dialog.show_credentials_format_error()
                else:
                    log_message("Main Launcher: Import cancelled by user", 0)

            elif "import_custom_browser" in args_str:
                opts = [
                    "[B]Import Single File (.conf/.config)[/B]",
                    "[B]Import Whole Folder (Bulk Import)[/B]"
                ]
                choice = xbmcgui.Dialog().select("Import Type", opts)

                if choice == 0:
                    selection = xbmcgui.Dialog().browse(1, "Select WireGuard Config", "local", ".conf|.config")
                elif choice == 1:
                    selection = xbmcgui.Dialog().browse(0, "Select Configs Folder", "local")
                else:
                    selection = None

                if selection and os.path.exists(selection):
                    target_config_dir = CONFIG_DIR
                    imported_count = 0
                    last_pretty = "Custom Profile"
                    last_path = ""
                    last_token = ""
                    files_to_process = []

                    if os.path.isdir(selection):
                        try:
                            for f_item in sorted(os.listdir(selection)):
                                if f_item.endswith((".conf", ".config")):
                                    files_to_process.append(os.path.join(selection, f_item))
                        except Exception:
                            pass
                    else:
                        files_to_process.append(selection)

                    for full_path in files_to_process:
                        if custom.update(full_path, target_config_dir) is True:
                            imported_count += 1
                            f_item = os.path.basename(full_path)
                            raw_name = f_item.lower()
                            clean_name = raw_name.replace(".config", "").replace(".conf", "")
                            clean_name = clean_name.replace("_", " ").replace("-", " ")

                            if not clean_name.startswith("custom"):
                                pretty_name = f"Custom {clean_name.strip().title()}"
                            else:
                                pretty_name = clean_name.strip().title()

                            token_id = pretty_name.lower().replace(" ", "_")
                            if len(token_id) > 15:
                                token_id = token_id[:15]

                            last_pretty = pretty_name
                            last_path = full_path
                            last_token = token_id

                    if imported_count > 0:
                        if last_path and last_token:
                            addon_obj.setSetting("custom_path", last_path)
                            addon_obj.setSetting("vpn_token", last_token)

                        dialog.show_custom_import_result(imported_count, last_pretty)
                        dialog.notify_action_required("Selection cached. You MUST press 'OK' in settings!")
                    else:
                        log_message("Main Launcher: No valid WireGuard layouts parsed from selection.", 2)
                        dialog.show_custom_import_failure()

            elif "mode=dnsleaktest" in args_str:
                scripts_path = os.path.join(addon_path, "resources", "scripts")
                if scripts_path not in sys.path:
                    sys.path.insert(0, scripts_path)
                import dnsleaktest
                dnsleaktest.main()

            elif "cleanup" in args_str:
                import setup_helper
                setup_helper.perform_cleanup()

            elif "mode=tos" in args_str:
                scripts_path = os.path.join(addon_path, "resources", "scripts")
                if scripts_path not in sys.path:
                    sys.path.insert(0, scripts_path)
                import show_terms_of_service
                show_terms_of_service.show_tos()

            elif "mode=disclaimer" in args_str:
                scripts_path = os.path.join(addon_path, "resources", "scripts")
                if scripts_path not in sys.path:
                    sys.path.insert(0, scripts_path)
                import show_disclaimer
                show_disclaimer.show_disclaimer()

            elif "mode=show_codes" in args_str:
                scripts_path = os.path.join(addon_path, "resources", "scripts")
                if scripts_path not in sys.path:
                    sys.path.insert(0, scripts_path)
                import show_codes
                show_codes.run_viewer(args_str)

            elif "mode=net_reset" in args_str:
                scripts_path = os.path.join(addon_path, "resources", "scripts")
                if scripts_path not in sys.path:
                    sys.path.insert(0, scripts_path)
                import network
                network.run_network_cleanup()

            elif "import_mullvad" in args_str:
                p_data = None
                for p_idx in PROVIDER_MAP:
                    if PROVIDER_MAP[p_idx].get("name") == "Mullvad":
                        p_data = PROVIDER_MAP[p_idx]
                        break

                if not p_data or "setting" not in p_data:
                    dialog.notify_action_required(
                        "Selection cached. You MUST press 'OK' in the main settings menu to apply changes!"
                    )
                else:
                    account_file = xbmcgui.Dialog().browse(1, "Select Account File", "local", ".txt")
                    if account_file:
                        f = xbmcvfs.File(account_file, "r")
                        content = f.read()
                        f.close()

                        if isinstance(content, bytes):
                            content = content.decode("utf-8")

                        clean_account = "".join(content.split()).strip()

                        if clean_account.isdigit() and len(clean_account) == 16:
                            addon_obj.setSetting(p_data["setting"], clean_account)
                            log_message(f"Imported Mullvad Account to target: {p_data['setting']}", 0)

                            selected_countries = addon_obj.getSetting(
                                p_data.get("countries_setting", "filter")
                            )

                            if not selected_countries:
                                log_message(
                                    "Main Launcher: Mullvad account saved. Country selection "
                                    "empty - update deferred until countries are selected.", 1
                                )
                                dialog.notify_generic(
                                    "[B][COLOR FFBF00FF][ WireGuard Manager ][/COLOR][/B]",
                                    "Account saved. Select countries first - update starts automatically after saving.",
                                    6000
                                )
                            else:
                                owned_val = addon_obj.getSetting("wg_owned").lower() == "true"

                                import providers.mullvad_utils as m_utils
                                m_utils.generate_mullvad_configs(
                                    account_id=clean_account,
                                    country_filter=selected_countries,
                                    mtu_setting=1380,
                                    owned=owned_val
                                )

                                if _write_notification_lock():
                                    dialog.notify_action_required(
                                        "Account loaded. You [B]MUST[/B] press [B]'OK'[/B] in settings menu!"
                                    )
                        else:
                            log_message("Main Launcher: Invalid Mullvad account token format rejected", 2)
                            dialog.show_invalid_mullvad_account()
                    else:
                        log_message("Main Launcher: Mullvad account import cancelled by user", 0)

        else:
            try:
                provider = addon_obj.getSettingInt("vpn_provider")
            except Exception as e:
                log_message(f"Main Launcher: Failed to read vpn_provider setting: {e}", 3)
                provider = 0

            import vpn_menu
            vpn_menu.show_menu(media_path, provider)

    except Exception as master_fault:
        log_message(f"Main Launcher: Fatal routing interception breakdown: {master_fault}", 3)

    finally:
        kodi_env.clear_script_globals()
