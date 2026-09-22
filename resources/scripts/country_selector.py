""" ./resources/scripts/country_selector.py """
import os
import sys
import time
import subprocess

try:
    import kodi_env
except ImportError:
    sys.path.append(os.path.join(os.path.dirname(__file__), "..", "lib"))
    import kodi_env

from logger import log_message
from providers.nord_utils import fetch_nord_url
from providers.pia_utils import fetch_pia_url
from providers.mullvad import MullvadApi
from vpn_config import PROVIDER_MAP
from state_manager import CONFIG_DIR
import dialog

try:
    import xbmcgui
    HAS_GUI_IMPORTS = True
except ImportError:
    HAS_GUI_IMPORTS = False


def get_addon_path():
    return kodi_env.ADDON_DIR


def inject_lib_path():
    addon_path = get_addon_path()
    lib_path = os.path.join(addon_path, "resources", "lib")
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)


def _resolve_removed_profiles(removed_ids, data, id_to_name, config_dir):
    removed_profiles = []
    try:
        conf_files = [
            f for f in os.listdir(config_dir)
            if f.endswith((".conf", ".config")) and os.path.isfile(os.path.join(config_dir, f))
        ]
    except Exception:
        return removed_profiles
    country_terms = []
    for rid in removed_ids:
        name = id_to_name.get(rid, rid)
        parts = name.split()
        if len(parts) >= 2:
            country_terms.append(parts[0].lower())
        else:
            country_terms.append(name.lower().replace(" ", "_"))
    for conf_file in conf_files:
        stem = os.path.splitext(conf_file)[0]
        try:
            from vpn_utils import read_friendly_name
            friendly = read_friendly_name(stem)
            if friendly:
                for term in country_terms:
                    if term in friendly.lower():
                        removed_profiles.append({
                            "nm_profile": stem,
                            "conf_file": os.path.join(config_dir, conf_file)
                        })
                        break
        except Exception:
            for term in country_terms:
                if term in stem.lower():
                    removed_profiles.append({
                        "nm_profile": stem,
                        "conf_file": os.path.join(config_dir, conf_file)
                    })
                    break
    return removed_profiles


def _kill_active_helper():
    try:
        helper_proc = subprocess.Popen(
            ["pgrep", "-f", "reconnect_helper.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True
        )
        out, _ = helper_proc.communicate()
        if helper_proc.returncode == 0 and out.strip():
            pids = out.strip().splitlines()
            for pid in pids:
                try:
                    proc = subprocess.Popen(
                        ["kill", "-9", pid],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                    proc.wait()
                except Exception:
                    pass
            log_message("Country Selector: Terminated active reconnect helper instance(s).", 1)
    except Exception:
        pass


def _disconnect_active_tunnel_if_in_removed(provider, removed_ids, removed_profiles, id_to_name, config_dir):
    active_vpn_name = None
    try:
        from state_manager import get_active_vpn, set_active_vpn, get_file_path
        from vpn_ops import disconnect_vpn
        active_vpn_name = get_active_vpn()
        if active_vpn_name:
            country_in_removed = False
            if provider == 0:
                for profile_info in removed_profiles:
                    try:
                        from vpn_utils import read_friendly_name
                        friendly = read_friendly_name(profile_info["nm_profile"])
                        if friendly and active_vpn_name.lower() == friendly.lower():
                            country_in_removed = True
                            break
                    except Exception:
                        if active_vpn_name.lower() in profile_info["nm_profile"].lower():
                            country_in_removed = True
                            break
            elif provider == 1:
                for profile_info in removed_profiles:
                    if any(pid.lower() in profile_info["nm_profile"].lower() for pid in removed_ids):
                        country_in_removed = True
                        break
            elif provider == 2:
                for profile_info in removed_profiles:
                    if any(pid.lower() in profile_info["nm_profile"].lower() for pid in removed_ids):
                        country_in_removed = True
                        break
            if country_in_removed:
                log_message("Country Selector: Active VPN belongs to removed country. Triggering teardown.", 1)
                set_active_vpn(None)
                disconnect_vpn(silent=True, flush_dns=True)
                prop_path = get_file_path("manual")
                if prop_path is not None and os.path.exists(prop_path):
                    try:
                        os.remove(prop_path)
                    except Exception:
                        pass
                try:
                    xbmcgui.Window(10000).setProperty("vpn_manual_session", "")
                except Exception:
                    pass
                return True
    except Exception as e:
        log_message(f"Country Selector: Teardown evaluation fault: {e}", 2)
    return False


def _purge_nm_profiles_and_conf(removed_profiles):
    try:
        from providers.nm_manager import nm_delete_profile
        for profile_info in removed_profiles:
            nm_profile = profile_info["nm_profile"]
            conf_file = profile_info["conf_file"]
            nm_rc = nm_delete_profile(nm_profile)
            if nm_rc == 0:
                log_message(f"Country Selector: NM profile [{nm_profile}] deleted successfully.", 1)
            elif nm_rc == 10 or nm_rc == 6:
                log_message(f"Country Selector: NM profile [{nm_profile}] not found (rc={nm_rc}), skipping.", 0)
            else:
                log_message(f"Country Selector: NM profile [{nm_profile}] delete returned rc={nm_rc}.", 2)
            if conf_file and os.path.exists(conf_file):
                try:
                    os.remove(conf_file)
                    log_message(f"Country Selector: Config file [{conf_file}] removed.", 1)
                except Exception as conf_err:
                    log_message(f"Country Selector: Config removal failed for [{conf_file}]: {conf_err}", 2)
    except Exception as purge_err:
        log_message(f"Country Selector: Purge exception: {purge_err}", 2)


def _purge_reconnect_state():
    try:
        from state_manager import get_file_path
        for state_key in ("reconnect", "reconnect_target"):
            state_path = get_file_path(state_key)
            if state_path is not None and os.path.exists(state_path):
                try:
                    os.remove(state_path)
                except Exception:
                    pass
    except Exception:
        pass


def _clear_map_slots_for_removed_countries(removed_ids, removed_profiles, id_to_name):
    try:
        addon_obj = kodi_env.get_addon_instance()
        if not addon_obj:
            return
        country_terms = []
        for rid in removed_ids:
            name = id_to_name.get(rid, rid)
            parts = name.split()
            if len(parts) >= 2:
                country_terms.append(parts[0].lower())
            else:
                country_terms.append(name.lower().replace(" ", "_"))
        cleared_count = 0
        for i in range(1, 8):
            saved_vpn = addon_obj.getSetting(f"vpn_{i}_name")
            if saved_vpn:
                vpn_needs_clear = False
                for profile_info in removed_profiles:
                    nm_profile = profile_info["nm_profile"]
                    saved_is_this_profile = False
                    if saved_vpn.lower() == nm_profile.lower():
                        saved_is_this_profile = True
                    else:
                        try:
                            from vpn_utils import read_friendly_name
                            saved_friendly = read_friendly_name(saved_vpn)
                            nm_friendly = read_friendly_name(nm_profile)
                            if saved_friendly and nm_friendly:
                                if saved_friendly.lower() == nm_friendly.lower():
                                    saved_is_this_profile = True
                        except Exception:
                            pass
                    if saved_is_this_profile:
                        vpn_needs_clear = True
                        break
                if not vpn_needs_clear and country_terms:
                    try:
                        from vpn_utils import read_friendly_name
                        saved_friendly = read_friendly_name(saved_vpn)
                        if saved_friendly:
                            for term in country_terms:
                                if term in saved_friendly.lower():
                                    vpn_needs_clear = True
                                    break
                    except Exception:
                        pass
                if vpn_needs_clear:
                    addon_obj.setSetting(f"vpn_{i}_name", "")
                    addon_obj.setSetting(f"map_{i}_addon", "")
                    cleared_count += 1
        if cleared_count > 0:
            log_message(f"Country Selector: Cleared {cleared_count} map slot(s) targeting removed country.", 1)
    except Exception as e:
        log_message(f"Country Selector: Slot clearing exception: {e}", 2)


def run():
    inject_lib_path()

    try:
        addon_obj = kodi_env.get_addon_instance()

        if not addon_obj or not HAS_GUI_IMPORTS:
            msg = "Country Selector: Environment missing Kodi abstractions. Execution stopped."
            log_message(msg, 2)
            return

        provider = addon_obj.getSettingInt("vpn_provider")
        log_message(f"Country Selector: Active provider ID = {provider}", 0)

        if provider < 0:
            dialog.show_no_provider_selected()
            return

        p_data = PROVIDER_MAP.get(provider)

        if not p_data or "api_url" not in p_data:
            msg = f"Country Selector: Missing valid PROVIDER_MAP configuration for ID {provider}"
            log_message(msg, 3)
            return

        setting_id = p_data.get("countries_setting", "selected_countries")
        raw_saved = addon_obj.getSetting(setting_id)
        saved_ids = [s.strip().lower() for s in raw_saved.split(",") if s.strip()]

        log_message(f"Country Selector: Targeted setting_id = '{setting_id}'", 0)
        log_message(f"Country Selector: Raw saved string content = '{raw_saved}'", 0)
        log_message(f"Country Selector: Normalized saved IDs array = {saved_ids}", 0)

        data = None
        if provider == 0:
            log_message(f"Country Selector: Loading NordVPN API endpoint: {p_data['api_url']}", 0)
            data = fetch_nord_url(p_data["api_url"])
        elif provider == 1:
            log_message(f"Country Selector: Loading PIA API endpoint: {p_data['api_url']}", 0)
            data = fetch_pia_url(p_data["api_url"])
        elif provider == 2:
            log_message(f"Country Selector: Loading Mullvad API database target: {p_data['api_url']}", 0)
            data = MullvadApi.all_wireguard_relays()

        if not data:
            log_message("Country Selector: Target API payload response is completely EMPTY!", 3)
            dialog.show_fetch_failed(p_data['name'])
            return

        names = []
        ids = []

        if provider == 0:
            data.sort(key=lambda x: x["name"])
            names = [c["name"] for c in data]
            ids = [str(c["id"]) for c in data]

        elif provider == 1:
            if isinstance(data, dict):
                raw_regions = data.get("regions", [])
            elif isinstance(data, list):
                raw_regions = data
                if len(raw_regions) == 1 and isinstance(raw_regions[0], dict) and "regions" in raw_regions[0]:
                    raw_regions = raw_regions[0]["regions"]
            else:
                raw_regions = []

            regions = []
            for r in raw_regions:
                if not isinstance(r, dict):
                    continue
                servers_dict = r.get("servers", {})
                if isinstance(servers_dict, dict) and ("wg" in servers_dict or "wireguard" in servers_dict):
                    regions.append(r)
                elif "ports" in r or "dns" in r:
                    regions.append(r)
                elif isinstance(r, dict) and "id" in r and "name" in r:
                    regions.append(r)

            regions.sort(key=lambda x: x["name"])
            names = [r["name"] for r in regions]
            ids = [str(r["id"]).strip() for r in regions]

        elif provider == 2:
            log_message(
                "Country Selector: Parsing Mullvad public v1 countries "
                "array with server-range checks", 0
            )
            mullvad_countries = {}

            if isinstance(data, list):
                for relay in data:
                    if isinstance(relay, dict):
                        code = str(relay.get("country_code", "")).strip().lower()
                        name = str(relay.get("country_name", "")).strip()
                        is_owned = bool(relay.get("owned", False))
                        if code and name:
                            if code not in mullvad_countries:
                                mullvad_countries[code] = {
                                    "name": name,
                                    "has_owned": is_owned
                                }
                            elif is_owned:
                                mullvad_countries[code]["has_owned"] = True

            sorted_mullvad = sorted(
                mullvad_countries.items(),
                key=lambda x: x[1]["name"]
            )
            names = []
            ids = []
            for code, info in sorted_mullvad:
                display_suffix = "" if info["has_owned"] else " (not owned)"
                names.append(f"{info['name']}{display_suffix}")
                ids.append(str(code))

        cleaned_saved_ids = [str(sid).strip().lower() for sid in saved_ids]

        log_message(
            f"Country Selector: First 5 entries available inside raw API "
            f"mapping: {ids[:5]}", 0
        )
        log_message(
            f"Country Selector: Target key comparison values checklist: "
            f"{cleaned_saved_ids}", 0
        )

        preselect = [i for i, val in enumerate(ids) if val in cleaned_saved_ids]
        log_message(
            f"Country Selector: Resulting computed checkbox baseline indices "
            f"= {preselect}", 0
        )

        log_message(
            f"Country Selector: Activating UI multiselect dialog view for "
            f"{len(names)} entries...", 0
        )
        selected = xbmcgui.Dialog().multiselect(
            f"Select {p_data['name']} Regions", names, preselect=preselect
        )

        if selected is None:
            log_message("Country Selector: User interaction loop aborted by closing the interface.", 0)
            return

        t_start = time.perf_counter()
        id_to_name = dict(zip(ids, names))
        selected_ids = [ids[i] for i in selected]
        selection_set = {str(sid).strip().lower() for sid in selected_ids}
        baseline_set = set(cleaned_saved_ids)
        added_ids = sorted(selection_set - baseline_set)
        removed_ids = sorted(baseline_set - selection_set)

        log_message(f"Country Selector: Selection index tracking map register = {selected}", 0)
        log_message(f"Country Selector: Pre-dialog baseline ID set = {sorted(baseline_set)}", 0)
        log_message(f"Country Selector: Post-dialog selection ID set = {sorted(selection_set)}", 0)
        log_message(f"Country Selector: Dirty-diff added IDs = {added_ids}", 0)
        log_message(f"Country Selector: Dirty-diff removed IDs = {removed_ids}", 0)

        if not added_ids and not removed_ids:
            log_message(
                "Country Selector: Selection identical to stored baseline. "
                "No write performed, update pipeline intentionally not triggered.", 0
            )
            return

        added_names = [id_to_name.get(a, a) for a in added_ids]
        removed_names = [id_to_name.get(r, r) for r in removed_ids]
        added_display = ", ".join(added_names) if added_names else "none"
        removed_display = ", ".join(removed_names) if removed_names else "none"
        confirm_body = (
            f"Save this country selection?\n\n"
            f"Added: {added_display}\n"
            f"Removed: {removed_display}"
        )
        confirmed = xbmcgui.Dialog().yesno(f"{p_data['name']} Regions", confirm_body)

        if not confirmed:
            log_message(
                "Country Selector: Dirty selection rejected by user confirmation. "
                "Stored setting left untouched.", 1
            )
            return

        id_string = ",".join(selected_ids)
        log_message(f"Country Selector: Assembled text configuration entry block = '{id_string}'", 0)
        addon_obj.setSetting(setting_id, id_string)
        log_message(f"Country Selector: Dynamic database updated with new countries list = {selected_ids}", 1)

        if removed_ids:
            config_dir = CONFIG_DIR
            log_message(f"Country Selector: Resolving removed IDs to profiles in {config_dir}", 0)
            removed_profiles = _resolve_removed_profiles(removed_ids, data, id_to_name, config_dir)
            log_message(f"Country Selector: Resolved {len(removed_profiles)} profile(s) for removal.", 1)

            if removed_profiles:
                log_message("Country Selector: Killing active helper instances before teardown.", 1)
                _kill_active_helper()

                teardown_triggered = _disconnect_active_tunnel_if_in_removed(
                    provider, removed_ids, removed_profiles, id_to_name, config_dir
                )
                if teardown_triggered:
                    log_message("Country Selector: Active tunnel teardown completed.", 1)
                else:
                    log_message("Country Selector: Active tunnel not in removed set; no teardown needed.", 0)

                log_message("Country Selector: Purging NetworkManager profiles and config files.", 1)
                _purge_nm_profiles_and_conf(removed_profiles)

                log_message("Country Selector: Purging stale reconnect states.", 1)
                _purge_reconnect_state()

                log_message("Country Selector: Clearing map slots targeting removed country.", 1)
                _clear_map_slots_for_removed_countries(removed_ids, removed_profiles, id_to_name)

        if added_ids:
            dialog.notify_action_required(
                "Selection cached. You [B]MUST[/B] press [B]'OK'[/B] in the "
                "main settings menu to apply changes!"
            )
        else:
            dialog.notify_action_required(
                "Removals applied to NetworkManager. Press [B]'OK'[/B] in the "
                "main settings menu to save settings permanently!"
            )

        t_elapsed = (time.perf_counter() - t_start) * 1000.0
        log_msg = f"Country Selector: Country selection took {t_elapsed:.2f}ms"
        log_message(log_msg, 0)

    except Exception as run_fault:
        log_message(f"Country Selector: Interface thread tracking exception: {run_fault}", 3)

    finally:
        kodi_env.clear_script_globals()


if __name__ == "__main__":
    run()
