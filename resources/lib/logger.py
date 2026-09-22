""" ./resources/lib/logger.py """
import kodi_env
import builtins
import os
import sys
import time
import xml.etree.ElementTree as ET
import subprocess

try:
    import xbmc
    HAS_KODI_LOGGING = True
except ImportError:
    HAS_KODI_LOGGING = False

_ROTATION_CHECK_INTERVAL_SEC = 60.0
_last_rotation_check = 0.0
_LAST_RESORT_MAX_BYTES = 10485760
_LAST_RESORT_BACKUP_COUNT = 2


def get_addon_metadata():
    if kodi_env.HAS_KODI_IMPORTS:
        addon_obj = kodi_env.get_addon_instance()
        if addon_obj:
            try:
                return addon_obj.getAddonInfo("id"), addon_obj.getAddonInfo("version")
            except Exception:
                pass

    script_path = os.path.dirname(__file__)
    addon_xml_path = os.path.normpath(os.path.join(script_path, "..", "..", "addon.xml"))
    try:
        tree = ET.parse(addon_xml_path)
        root = tree.getroot()
        return root.get("id"), root.get("version")
    except Exception:
        return "service.wireguard.manager.linux", "unknown"


def _standalone_log_path():
    script_path = os.path.dirname(__file__)
    addon_id, _addon_ver = get_addon_metadata()
    data_dir = os.path.normpath(
        os.path.join(script_path, "..", "..", "..", "..", "userdata", "addon_data", addon_id)
    )
    return os.path.join(data_dir, "standalone_wm.log")


def _resolve_rotation_settings():
    enabled = True
    max_bytes = _LAST_RESORT_MAX_BYTES
    backup_count = _LAST_RESORT_BACKUP_COUNT

    env_enabled = os.environ.get("WM_LOG_ROTATION_ENABLED")
    if env_enabled is not None:
        enabled = env_enabled.strip().lower() in ("1", "true", "yes", "on")
    env_max = os.environ.get("WM_LOG_ROTATION_MAX_MB")
    if env_max:
        parsed_max = int(float(env_max) * 1048576)
        if parsed_max > 0:
            max_bytes = parsed_max
    env_count = os.environ.get("WM_LOG_ROTATION_BACKUPS")
    if env_count:
        parsed_count = int(env_count)
        if parsed_count > 0:
            backup_count = parsed_count

    if kodi_env.HAS_KODI_IMPORTS:
        addon_obj = kodi_env.get_addon_instance()
        if addon_obj:
            try:
                enabled = addon_obj.getSettingBool("log_rotation_enabled")
            except Exception:
                pass
            try:
                setting_max = int(addon_obj.getSettingInt("log_rotation_max_mb"))
                if setting_max > 0:
                    max_bytes = setting_max * 1048576
            except Exception:
                pass
            try:
                setting_count = int(addon_obj.getSettingInt("log_rotation_backup_count"))
                if setting_count > 0:
                    backup_count = setting_count
            except Exception:
                pass

    return enabled, max_bytes, backup_count


def rotate_standalone_log(force=False):
    global _last_rotation_check

    now = time.monotonic()
    if force is False and (now - _last_rotation_check) < _ROTATION_CHECK_INTERVAL_SEC:
        return False
    _last_rotation_check = now

    enabled, max_bytes, backup_count = _resolve_rotation_settings()
    if enabled is False:
        return False

    log_path = _standalone_log_path()
    try:
        if os.path.exists(log_path) is False:
            return False
        if force is False and os.path.getsize(log_path) < max_bytes:
            return False

        log_dir = os.path.dirname(log_path)
        log_name = os.path.basename(log_path)

        legacy_old = os.path.join(log_dir, f"{log_name}.old")
        if os.path.exists(legacy_old):
            os.remove(legacy_old)

        stamp = time.strftime("%Y%m%d-%H%M%S")
        rotated_path = os.path.join(log_dir, f"{log_name}.{stamp}")
        if os.path.exists(rotated_path):
            rotated_path = os.path.join(log_dir, f"{log_name}.{stamp}-{os.getpid()}")
        os.rename(log_path, rotated_path)

        prefix = f"{log_name}."
        rotations = []
        for entry in os.listdir(log_dir):
            full_path = os.path.join(log_dir, entry)
            if entry.startswith(prefix) and os.path.isfile(full_path):
                rotations.append(full_path)
        rotations.sort()
        surplus = max(0, len(rotations) - backup_count)
        for stale_path in rotations[:surplus]:
            try:
                os.remove(stale_path)
            except Exception:
                pass
        return True
    except Exception:
        return False


def run_logged_command(command_list, timeout=None, log_prefix=None):
    prefix = log_prefix if log_prefix else " ".join(command_list[:2])
    try:
        process = subprocess.Popen(
            command_list,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
    except Exception as spawn_err:
        log_message(f"{prefix}: command spawn failed: {spawn_err}", 2)
        return -1

    try:
        for raw_line in iter(process.stdout.readline, ""):
            stripped = raw_line.strip()
            if stripped:
                log_message(f"{prefix}: {stripped}", 0)
    except Exception as read_err:
        log_message(f"{prefix}: output capture failed: {read_err}", 2)
    finally:
        try:
            process.stdout.close()
        except Exception:
            pass

    try:
        return_code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        return_code = process.wait()
        log_message(f"{prefix}: command timed out", 2)
    except Exception as wait_err:
        log_message(f"{prefix}: wait failure: {wait_err}", 2)
        return_code = -1
    return return_code


def log_message(msg, level=1):
    if level is None:
        level = 1

    addon_id, addon_ver = get_addon_metadata()
    formatted_msg = f"{addon_id} v{addon_ver}: {msg}"

    if HAS_KODI_LOGGING and kodi_env.HAS_KODI_IMPORTS:
        xbmc.log(formatted_msg, level)
    else:
        lvl_name = {0: "Debug", 1: "Info", 2: "Warning", 3: "Error"}.get(level, "Info")

        try:
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            file_line = f"{stamp} T:{os.getpid()} [{lvl_name}] {formatted_msg}\n"
            with open(_standalone_log_path(), "a") as standalone_handle:
                standalone_handle.write(file_line)
        except Exception:
            pass

        rotate_standalone_log(False)
        is_debug_active = False
        script_path = os.path.dirname(__file__)
        gui_xml = os.path.normpath(
            os.path.join(script_path, "..", "..", "..", "..", "userdata", "guisettings.xml")
        )
        try:
            if os.path.exists(gui_xml):
                tree = ET.parse(gui_xml)
                setting = tree.find(".//setting[@id='core.logging.enabledebug']")
                if setting is not None and setting.text:
                    is_debug_active = setting.text.lower() == "true"
        except Exception:
            pass

        if level == 0 and not is_debug_active:
            return

        console_msg = f"[{lvl_name}] {formatted_msg}\n"

        if level in (2, 3):
            sys.stderr.write(console_msg)
            sys.stderr.flush()
        else:
            sys.stdout.write(console_msg)
            sys.stdout.flush()


if HAS_KODI_LOGGING and kodi_env.HAS_KODI_IMPORTS:
    builtins.log_event = lambda msg, lvl=0: xbmc.log(
        f"service.wireguard.manager.linux fallback: {msg}",
        level=xbmc.LOGERROR if lvl >= 2 else xbmc.LOGINFO
    )
else:
    builtins.log_event = lambda msg, lvl=0: (
        sys.stderr.write(f"service.wireguard.manager.linux fallback: {msg}\n") if lvl >= 2
        else sys.stdout.write(f"service.wireguard.manager.linux fallback: {msg}\n")
    )

if not HAS_KODI_LOGGING or not kodi_env.HAS_KODI_IMPORTS:
    import types

    mock_xbmc = types.ModuleType("xbmc")

    mock_xbmc.LOGDEBUG = 0
    mock_xbmc.LOGINFO = 1
    mock_xbmc.LOGWARNING = 2
    mock_xbmc.LOGERROR = 3

    mock_xbmc.log = log_message

    mock_xbmc.getCondVisibility = lambda cond: False
    mock_xbmc.executebuiltin = lambda cmd: sys.stderr.write(f"EXEC: {cmd}\n") or sys.stderr.flush()
    mock_xbmc.getInfoLabel = lambda infotag: ""

    sys.modules["xbmc"] = mock_xbmc
