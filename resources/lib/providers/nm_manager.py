""" ./resources/lib/providers/nm_manager.py """
import subprocess
from logger import log_message


def nm_delete_profile(profile_name):
    result = subprocess.run(
        ["nmcli", "connection", "delete", profile_name],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False
    )
    stderr_decoded = result.returncode and result.stderr.decode().lower()
    is_not_found = stderr_decoded and "not found" in stderr_decoded
    is_rc_10 = result.returncode == 10
    if result.returncode != 0 and not is_not_found and not is_rc_10:
        log_message(f"NM Manager: {profile_name} delete rc={result.returncode}", 0)
    return result.returncode


def nm_import_profile(conf_path, profile_name):
    result = subprocess.run(
        ["nmcli", "connection", "import", "type", "wireguard", "file", conf_path],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
    )
    return result.returncode


def nm_down_profile(profile_name):
    result = subprocess.run(
        ["nmcli", "connection", "down", profile_name],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False
    )
    return result.returncode


def nm_modify_profile(profile_name, key, value):
    result = subprocess.run(
        ["nmcli", "connection", "modify", profile_name, key, value],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False
    )
    return result.returncode


def nm_register_profile(profile_name, conf_path, extra_modify_args=None, autoconnect=False):
    rc_del = nm_delete_profile(profile_name)
    if rc_del == 6:
        log_message(f"NM Manager: profile [{profile_name}] deleted.", 0)
    elif rc_del != 0 and rc_del != 10:
        log_message(f"NM Manager: profile [{profile_name}] delete returned rc={rc_del}.", 0)

    rc_imp = nm_import_profile(conf_path, profile_name)
    if rc_imp != 0:
        log_message(
            f"NM Manager: import failed for [{profile_name}] rc={rc_imp}",
            2
        )
        return False

    autoconnect_value = "yes" if autoconnect else "no"
    rc_mod = nm_modify_profile(profile_name, "connection.autoconnect", autoconnect_value)
    if rc_mod != 0:
        log_message(
            f"NM Manager: modify autoconnect failed rc={rc_mod}",
            1
        )

    if not autoconnect:
        rc_dn = nm_down_profile(profile_name)
        if rc_dn == 0:
            log_message(f"NM Manager: suppressed import-time auto-activation for [{profile_name}].", 0)

    log_message(
        f"NM Manager: profile [{profile_name}] fully registered and hardened.",
        0
    )
    return True


def nm_refresh_profile(profile_name):
    subprocess.run(
        ["nmcli", "connection", "reload"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False
    )
    return 0
