""" ./resources/lib/service_control.py """
import kodi_env
import os
import subprocess
import sys
from logger import log_message
from vpn_config import PROVIDER_MAP
from state_manager import get_file_path
import dialog

try:
    import xbmc
    import xbmcgui
    HAS_KODI_UI = True
except ImportError:
    HAS_KODI_UI = False


def control_service():
    raw_args = "|".join(sys.argv).lower()

    if "restart" in raw_args:
        action = "restart"
    elif "clear" in raw_args:
        action = "clear"
    else:
        action = "status"

    try:
        if action == "restart":
            log_message("Service Control: Resetting local script loop tracking frameworks...", 0)
            reconnect_target = get_file_path("reconnect")
            if reconnect_target is not None and os.path.exists(reconnect_target):
                try:
                    os.remove(reconnect_target)
                except Exception:
                    pass
            if kodi_env.HAS_KODI_IMPORTS and HAS_KODI_UI:
                dialog.notify_watchdog_reset()

        elif action == "status":
            active_target = get_file_path("active")
            if active_target is not None and os.path.exists(active_target):
                real_status = "active"
            else:
                real_status = "idle"

            log_message(f"Service Control: Local monitoring framework is {real_status}", 0)
            if kodi_env.HAS_KODI_IMPORTS and HAS_KODI_UI:
                dialog.notify_watchdog_status(real_status)

        elif action == "clear":
            if kodi_env.HAS_KODI_IMPORTS and HAS_KODI_UI:
                confirmed = xbmcgui.Dialog().yesno("Confirm Reset", "Delete all VPN configurations?")
                if not confirmed:
                    return

            log_message("Service Control: Clearing configs and disconnecting VPN via nmcli...", 0)

            try:
                nm_out = subprocess.check_output(
                    ["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"],
                    text=True
                )
                for line in nm_out.splitlines():
                    if "wireguard" in line.lower() or any(p["name"].lower() in line.lower() for p in PROVIDER_MAP.values()):
                        conn_name = line.split(":")[0]
                        subprocess.run(
                            ["nmcli", "connection", "down", "id", conn_name],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL
                        )
                        subprocess.run(
                            ["nmcli", "connection", "delete", "id", conn_name],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL
                        )
            except Exception as nm_err:
                log_message(f"Service Control: NetworkManager purge pass encountered errors: {nm_err}", 2)

            target_conf_dir = os.path.expanduser("~/.config/wireguard")
            if os.path.exists(target_conf_dir):
                for f_item in os.listdir(target_conf_dir):
                    if f_item.endswith(".config") or f_item.endswith(".conf"):
                        try:
                            os.remove(os.path.join(target_conf_dir, f_item))
                        except Exception:
                            pass

            keys_to_remove = ["active", "disconnect", "manual", "reconnect"]

            for key in keys_to_remove:
                f = get_file_path(key)
                if f is not None and os.path.exists(f) is True:
                    try:
                        os.remove(f)
                    except Exception as e:
                        log_message(f"Service Control: Cleanup failure for {f}: {e}", 3)

            if kodi_env.HAS_KODI_IMPORTS and HAS_KODI_UI:
                dialog.notify_configs_cleared()
                xbmc.executebuiltin("Container.Refresh")

    except Exception as e:
        log_message(f"Service Control: ({action}): {e}", 3)
        if kodi_env.HAS_KODI_IMPORTS and HAS_KODI_UI:
            dialog.notify_action_failed(action)

    finally:
        kodi_env.clear_script_globals()


if __name__ == "__main__":
    control_service()
