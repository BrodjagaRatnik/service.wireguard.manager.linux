""" ./resources/lib/dialog.py """
import os
import kodi_env

try:
    import xbmcgui
    HAS_KODI = True
except ImportError:
    HAS_KODI = False


def _icon_path(filename):
    return os.path.join(kodi_env.ADDON_DIR, "resources", "media", filename)


def _notify_safe(title, msg, icon, duration):
    try:
        xbmcgui.Dialog().notification(title, msg, icon, duration)
    except Exception as dialog_err:
        from logger import log_message
        log_message(f"Dialog: Notification dispatch failed: {dialog_err}", 2)


def notify_killswitch_not_active():
    if not HAS_KODI:
        return
    title = "[B][COLOR FFFF0000][ KILLSWITCH NOT ACTIVE ][/COLOR][/B]"
    msg = (
        "[B][COLOR FFFFFF00]Connected without firewall protection.[/COLOR][/B]\n"
        "Check the Kodi log for the reason."
    )
    _notify_safe(title, msg, _icon_path("error.png"), 6000)


def notify_connection_failed(vpn_name):
    if not HAS_KODI:
        return
    title = "[B][COLOR FFFF0000][ CONNECTION FAILED ][/COLOR][/B]"
    msg = f"[B][COLOR FFFFFF00]{vpn_name}[/COLOR][/B]\n[B]No routing / Tunnel offline[/B]"
    _notify_safe(title, msg, xbmcgui.NOTIFICATION_ERROR, 5000)


def notify_connected(vpn_name, ip, country, context="normal"):
    if not HAS_KODI:
        return

    msg_body = (
        f"[B][COLOR FF32CD32]{vpn_name}[/COLOR][/B]\n"
        f"[B]IP [COLOR FFFFFF00]{ip}[/COLOR] "
        f"[COLOR FFFF8C00]({country})[/COLOR][/B]"
    )

    titles = {
        "tunnel_checker": "[B][COLOR FF00FFFF][ SYSTEM RESTART ][/COLOR][/B]",
        "service_loop": "[B][COLOR FF00FFFF][ MAPPED CONNECT ][/COLOR][/B]",
        "service_launcher": "[B][COLOR FF00FFFF][ SYSTEM RESTARTED ][/COLOR][/B]",
        "normal": "[B][COLOR FF00FF00][ CONNECTED ][/COLOR][/B]",
    }
    title = titles.get(context, titles["normal"])

    _notify_safe(title, msg_body, _icon_path("vpn_connected.png"), 4500)


def notify_tunnel_restored(vpn_name, ip, country):
    if not HAS_KODI:
        return
    title = "[B][COLOR FF00FF00][ TUNNEL RESTORED ][/COLOR][/B]"
    if ip and ip != "Unknown":
        msg = (
            f"[B][COLOR FF32CD32]{vpn_name}[/COLOR][/B]\n"
            f"[B]IP [COLOR FFFFFF00]{ip}[/COLOR] "
            f"[COLOR FFFF8C00]({country})[/COLOR][/B]"
        )
    else:
        msg = f"[B][COLOR FF32CD32]{vpn_name}[/COLOR][/B]"
    _notify_safe(title, msg, _icon_path("vpn_connected.png"), 4500)


def notify_tunnelling(vpn_name):
    if not HAS_KODI:
        return
    title = "[B][COLOR FFFFFF00][ TUNNELLING ][/COLOR][/B]"
    msg = f"[B][COLOR FFFFFF00]{vpn_name}[/COLOR][/B]\n[B]Syncing kernel routing state...[/B]"
    _notify_safe(title, msg, _icon_path("force.png"), 1500)


def notify_vpn_failure(err_msg):
    if not HAS_KODI:
        return
    _notify_safe(
        "[B][COLOR ffff0000][ VPN FAILURE ][/COLOR][/B]",
        err_msg, _icon_path("error.png"), 5000
    )


def notify_action_required(message):
    if not HAS_KODI:
        return
    title = "[B][COLOR ffffff00]ACTION REQUIRED!!![/COLOR][/B]"
    _notify_safe(title, message, _icon_path("icon.png"), 1500)


def notify_regen_success():
    if not HAS_KODI:
        return
    title = "[B][COLOR FFE6E6FA][ WireGuard Manager ][/COLOR][/B]"
    msg = "[COLOR FFFFFF00]Server countries updated.[/COLOR]"
    _notify_safe(title, msg, _icon_path("update_ok.png"), 3000)


def show_credentials_format_error():
    if not HAS_KODI:
        return
    title = "[B]\u2261 ERROR \u2261[/B]"
    msg = "File must have 2 lines:\nUser and Pass"
    xbmcgui.Dialog().ok(title, msg)


def show_custom_import_result(imported_count, last_pretty):
    if not HAS_KODI:
        return
    title = "[B][ WireGuard Manager ][/B]"
    if imported_count == 1:
        msg = f"Successfully imported custom profile:\n\n{last_pretty}"
    else:
        msg = f"Successfully imported {imported_count} custom profiles!"
    xbmcgui.Dialog().ok(title, msg)


def show_custom_import_failure():
    if not HAS_KODI:
        return
    title = "[B][ WireGuard Manager ][/B]"
    msg = "[COLOR FFFFFF00]No valid WireGuard configuration structures found.[/COLOR]"
    xbmcgui.Dialog().ok(title, msg)


def show_invalid_mullvad_account():
    if not HAS_KODI:
        return
    title = "[B][ WireGuard MANAGER ERROR ][/B]"
    msg = "[COLOR FFFFFF00]File does not contain a valid 16-digit Mullvad account.[/COLOR]"
    xbmcgui.Dialog().ok(title, msg)


def notify_generic(title, msg, duration=3000):
    if not HAS_KODI:
        return
    _notify_safe(title, msg, _icon_path("icon.png"), duration)


def show_error(msg, title="[B]\u2261 ERROR \u2261[/B]"):
    if not HAS_KODI:
        return
    xbmcgui.Dialog().ok(title, msg)


def show_update_failed(provider_name, detail=""):
    if not HAS_KODI:
        return
    title = "[B][ WireGuard Manager ][/B]"
    detail_block = f"\n\n[COLOR FFAAAAAA]{detail}[/COLOR]" if detail else ""
    msg = f"[COLOR FFFFFF00]Error. Failed to update {provider_name}.[/COLOR]{detail_block}"
    xbmcgui.Dialog().ok(title, msg)


def show_fetch_failed(provider_name):
    if not HAS_KODI:
        return
    title = "[B]\u2261 [ WireGuard MANAGER ERROR ] \u2261[/B]"
    msg = (
        "[COLOR FFFFFF00]Could not fetch server list for [/COLOR]"
        f"[COLOR FFE6E6FA]{provider_name}[/COLOR]"
    )
    xbmcgui.Dialog().ok(title, msg)


def show_no_provider_selected():
    if not HAS_KODI:
        return
    title = "[B]\u2261 [ ACTION REQUIRED!!! ] \u2261[/B]"
    msg = (
        "[COLOR FFFFFF00]Please save settings after selecting a VPN "
        "Provider in settings.\nAnd fill in, import credentials for "
        "that VPN Provider.[/COLOR]"
    )
    xbmcgui.Dialog().ok(title, msg)


def notify_watchdog_reset():
    if not HAS_KODI:
        return
    title = "[B][COLOR FFBF00FF][ WATCHDOG ][/COLOR][/B]"
    msg = "[COLOR FFFFFF00]Service Reset Complete[/COLOR]"
    _notify_safe(title, msg, _icon_path("update_ok.png"), 3000)


def notify_watchdog_status(status):
    if not HAS_KODI:
        return
    title = "[B][COLOR FFBF00FF][ WATCHDOG ][/COLOR][/B]"
    msg = f"[COLOR FFFFFF00]Status: [/COLOR][COLOR FFE6E6FA]{status}[/COLOR]"
    _notify_safe(title, msg, _icon_path("icon.png"), 3000)


def notify_configs_cleared():
    if not HAS_KODI:
        return
    title = "[B][COLOR FFBF00FF][ WG MANAGER ][/COLOR][/B]"
    msg = "[COLOR FFFFFF00]All configs cleared[/COLOR]"
    _notify_safe(title, msg, _icon_path("update_ok.png"), 4000)


def notify_action_failed(action):
    if not HAS_KODI:
        return
    title = "[B][COLOR FFBF00FF]ERROR[/COLOR][/B]"
    msg = f"[COLOR FFFFFF00]{action.capitalize()} failed[/COLOR]"
    _notify_safe(title, msg, _icon_path("error.png"), 5000)


def show_cleanup_complete():
    if not HAS_KODI:
        return
    title = "[B][ CLEANUP COMPLETE ][/B]"
    msg = (
        "[COLOR FFFFFF00]Cleanup successful.[/COLOR]\n"
        "All local client configurations and user services are removed from your device. "
        "You can now safely uninstall WireGuard VPN Manager."
    )
    xbmcgui.Dialog().ok(title, msg)


def notify_setup_success():
    if not HAS_KODI:
        return
    title = "[B][COLOR FFEEFFEE][ SETUP SUCCESS ][/COLOR][/B]"
    msg = "[COLOR FFFFFF00]WireGuard manager service is now active in the background.[/COLOR]"
    _notify_safe(title, msg, _icon_path("icon.png"), 6000)


def notify_orphaned_tunnel(iface_name):
    if not HAS_KODI:
        return
    title = "[B][COLOR FFFFFF00][ ORPHANED TUNNEL ][/COLOR][/B]"
    msg = (
        f"[B][COLOR FF32CD32]{iface_name}[/COLOR][/B]\n"
        "[B]Active tunnel without session state. "
        "Previous Kodi session may have crashed.[/B]"
    )
    _notify_safe(title, msg, xbmcgui.NOTIFICATION_WARNING, 6000)


def notify_session_available(friendly_name):
    if not HAS_KODI:
        return
    title = "[B][COLOR FFBF00FF][ WireGuard Manager ][/COLOR][/B]"
    msg = (
        f"[B][COLOR FF32CD32]{friendly_name}[/COLOR][/B]\n"
        "[B]Previous session not reconnected. Connect manually when ready.[/B]"
    )
    _notify_safe(title, msg, _icon_path("icon.png"), 5000)


def notify_startup_disconnected(friendly_name):
    if not HAS_KODI:
        return
    title = "[B][COLOR FFFFFF00][ DISCONNECTED ON START ][/COLOR][/B]"
    msg = (
        f"[B][COLOR FF32CD32]{friendly_name}[/COLOR][/B]\n"
        "[B]Tunnel closed for clean startup. Connect when ready.[/B]"
    )
    _notify_safe(title, msg, _icon_path("icon.png"), 5000)
