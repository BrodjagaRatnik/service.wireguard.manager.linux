""" ./resources/lib/setup_helper.py """
import kodi_env
import os
import shutil
import stat
import subprocess
import sys
from logger import log_message
from vpn_config import PROVIDER_MAP
import dialog

try:
    import xbmc
    import xbmcgui
    import xbmcvfs
    HAS_KODI = True
except ImportError:
    HAS_KODI = False


def _setup_paths():
    try:
        addon_path = kodi_env.ADDON_DIR
        local_lib = os.path.join(addon_path, "resources", "lib")

        if local_lib not in sys.path:
            sys.path.insert(0, local_lib)

    except Exception as e:
        sys.stderr.write(f"Setup Helper: Path setup critical failure: {e}\n")


_setup_paths()


def migrate_legacy_watchdog_unit():
    user_systemd_dir = os.path.expanduser("~/.config/systemd/user/")
    service_file = os.path.join(user_systemd_dir, "vpn-watchdog.service")

    if os.path.exists(service_file) is not True:
        return False

    try:
        subprocess.run(["systemctl", "--user", "stop", "vpn-watchdog.service"], check=False)
        subprocess.run(["systemctl", "--user", "disable", "vpn-watchdog.service"], check=False)
        os.remove(service_file)
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        log_message("Setup Helper: Legacy watchdog user unit removed. Integrated Kodi watchdog takes over.", 1)
        return True
    except Exception as migrate_err:
        log_message(f"Setup Helper: Legacy watchdog unit migration failure: {migrate_err}", 3)
        return False


def perform_cleanup(silent=False):
    addon = kodi_env.get_addon_instance()
    home_dir = os.path.expanduser("~")
    desktop_dir = os.path.join(home_dir, "Desktop")
    wg_config_path = os.path.expanduser("~/.config/wireguard/")
    recovery_script = os.path.join(home_dir, "vpn_recovery.sh")
    recovery_desktop = os.path.join(desktop_dir, "vpn_recovery.desktop")

    try:
        log_message("Setup Helper: Cleanup Starting factory reset...", 1)

        try:
            from vpn_utils import get_dynamic_prefixes
            prefixes = get_dynamic_prefixes()
            out = subprocess.check_output(
                ["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"],
                text=True
            )
            for line in out.splitlines():
                if ":" in line:
                    c_name, c_type = line.split(":", 1)
                    c_name_low = c_name.lower()
                    if "wireguard" in c_type.lower() or any(p in c_name_low for p in prefixes):
                        subprocess.run(
                            ["nmcli", "connection", "down", "id", c_name],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
                        )
                        subprocess.run(
                            ["nmcli", "connection", "delete", "id", c_name],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
                        )
            subprocess.run(
                ["nmcli", "general", "reload", "dns"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
            )
            log_message("Setup Helper: Purged registered profiles and reloaded NetworkManager DNS configuration.", 1)
        except Exception as nm_err:
            log_message(f"Setup Helper: NetworkManager registration drop failure: {nm_err}", 2)

        if os.path.exists(recovery_script) is True:
            os.remove(recovery_script)

        if os.path.exists(recovery_desktop) is True:
            os.remove(recovery_desktop)

        if os.path.exists(wg_config_path) is True:
            for item in os.listdir(wg_config_path):
                if "_" in item and (item.endswith(".config") or item.endswith(".conf")):
                    try:
                        os.remove(os.path.join(wg_config_path, item))
                    except Exception:
                        pass
            log_message("Setup Helper: Cleanup WireGuard configs wiped.", 1)

        if addon:
            addon.setSetting("selected_countries", "")
            addon.setSetting("selected_countries_pia", "")
            addon.setSetting("first_run", "false")

        keymap_file = xbmcvfs.translatePath("special://userdata/keymaps/wireguard_manager_key.xml")
        if os.path.exists(keymap_file) is True:
            os.remove(keymap_file)

        from state_manager import FILE_MAP, get_file_path
        for key in FILE_MAP:
            tf = get_file_path(key)
            if tf is not None and os.path.exists(tf) is True:
                try:
                    os.remove(tf)
                except Exception as e:
                    log_message(f"Setup Helper: Reset error removing {tf}: {e}", 3)

        log_message("Setup Helper: Cleanup Reset complete.", 1)
        if silent is False and HAS_KODI:
            xbmc.executebuiltin("Dialog.Close(all, true)")
            xbmc.sleep(200)
            dialog.show_cleanup_complete()

    except Exception as e:
        log_message(f"Setup Helper: Cleanup Error: {e}", 3)

    finally:
        kodi_env.clear_script_globals()


def ensure_setup(addon_path, silent=False):
    try:
        ADDON = kodi_env.get_addon_instance()

        if not ADDON or not HAS_KODI:
            log_message("Setup Helper: Abstractions missing. Skipping interface orchestration.", 2)
            return

        home_dir = os.path.expanduser("~")
        desktop_dir = os.path.join(home_dir, "Desktop")
        keymap_dest = xbmcvfs.translatePath("special://userdata/keymaps/wireguard_manager_key.xml")
        keymap_source = os.path.join(addon_path, "resources", "keymaps", "wireguard_manager_key.xml")
        wg_config_path = os.path.expanduser("~/.config/wireguard/")
        cert_source = os.path.join(addon_path, "resources", "data", "ca.rsa.4096.txt")
        cert_dest = os.path.join(addon_path, "resources", "lib", "providers", "ca.rsa.4096.crt")
        recovery_source = os.path.join(addon_path, "resources", "data", "vpn-recovery.sh.txt")
        recovery_dest = os.path.join(home_dir, "vpn_recovery.sh")
        shortcut_dest = os.path.join(desktop_dir, "vpn_recovery.desktop")
        setup_updated = False
        progress = xbmcgui.DialogProgress()
        progress.create("WireGuard Manager", "Starting system check...")
        progress.update(20, "Checking Keymaps...")

        if not os.path.exists(keymap_dest):
            try:
                os.makedirs(os.path.dirname(keymap_dest), exist_ok=True)
                shutil.copy2(keymap_source, keymap_dest)
                log_message("Setup Helper: Keymap installed.", 1)
                xbmc.executebuiltin("Action(ReloadKeymaps)")
                log_message("Setup Helper: Keymaps reloaded in Kodi.", 1)
                setup_updated = True
            except Exception as e:
                log_message(f"Setup Helper: Setup Error (Keymap): {e}", 3)

        progress.update(40, "Migrating watchdog integration...")
        if migrate_legacy_watchdog_unit() is True:
            setup_updated = True

        progress.update(60, "Deploying PIA provider certificates...")
        if not os.path.exists(cert_dest):
            try:
                os.makedirs(os.path.dirname(cert_dest), exist_ok=True)
                shutil.copy2(cert_source, cert_dest)
                log_message("Setup Helper: Secure verification certificate deployed.", 1)
                setup_updated = True
            except Exception as e:
                log_message(f"Setup Helper: Setup Error (Certificate Copy): {e}", 3)

        progress.update(80, "Deploying desktop emergency recovery hooks...")
        if not os.path.exists(recovery_dest):
            try:
                shutil.copy2(recovery_source, recovery_dest)
                os.chmod(recovery_dest, os.stat(recovery_dest).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
                if os.path.exists(desktop_dir):
                    shortcut_lines = [
                        "[Desktop Entry]",
                        "Version=1.0",
                        "Type=Application",
                        "Name=VPN Recovery Hook",
                        "Comment=Fixes stuck routing tables and killswitches after Kodi crashes",
                        f"Exec=pkexec {recovery_dest}",
                        "Icon=network-error",
                        "Terminal=true",
                        "Categories=System;Network;",
                        "StartupNotify=true"
                    ]
                    with open(shortcut_dest, "w") as df:
                        df.write("\n".join(shortcut_lines) + "\n")
                    os.chmod(shortcut_dest, os.stat(shortcut_dest).st_mode | stat.S_IEXEC)
                log_message("Setup Helper: Emergency desktop recovery shortcut generated successfully.", 1)
                setup_updated = True
            except Exception as e:
                log_message(f"Setup Helper: Setup Error (Recovery Deployment): {e}", 3)

        progress.update(90, "Verifying VPN credentials...")
        current_p_id = ADDON.getSettingInt("vpn_provider")
        has_creds = False
        if current_p_id == -1:
            log_message("Setup Helper: No VPN provider selected yet. Skipping credential check.", 1)
        else:
            p_data = PROVIDER_MAP.get(current_p_id, {"name": "Unknown", "prefix": "unknown_"})
            token_setting = p_data.get("setting")
            if token_setting:
                has_creds = bool(ADDON.getSetting(token_setting).strip())
            if current_p_id == 99 or not has_creds:
                prefix = p_data["prefix"]
                if os.path.exists(wg_config_path):
                    has_files = any(f.startswith((prefix, "custom_")) for f in os.listdir(wg_config_path))
                    has_creds = has_creds or has_files

        progress.update(100, "Setup Complete.")
        if setup_updated:
            log_message("Setup Helper: All system checks completed successfully.", 0)
        progress.close()

        if setup_updated:
            log_message("Setup Helper: Success! Background tracking engines active.", 1)
            dialog.notify_setup_success()

    except Exception as major_err:
        log_message(f"Setup Helper: Orchestration master failure: {major_err}", 3)

    finally:
        kodi_env.clear_script_globals()


if __name__ == "__main__":
    if len(sys.argv) > 1 and "cleanup" in sys.argv:
        perform_cleanup()
