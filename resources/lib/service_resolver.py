""" ./resources/lib/service_resolver.py """
import os
from logger import log_message
from kodi_env import get_addon_instance
from state_manager import CONFIG_DIR
from vpn_config import PROVIDER_MAP


def _clean(text):
    return (
        str(text).lower()
        .replace('nordvpn', '')
        .replace('mullvad', '')
        .replace('custom', '')
        .replace('pia', '')
        .replace('_', '')
        .replace('-', '')
        .replace(' ', '')
        .strip()
    )


def _active_provider_prefixes(addon):
    try:
        addon_obj = addon or get_addon_instance()
        if addon_obj is None:
            return []

        provider_id = 0
        try:
            provider_id = int(addon_obj.getSettingInt("vpn_provider") or 0)
        except Exception:
            try:
                provider_id = int(addon_obj.getSetting("vpn_provider") or 0)
            except Exception:
                provider_id = 0

        p_data = PROVIDER_MAP.get(provider_id, {})

        prefixes = []
        base_prefix = str(p_data.get("prefix", "") or "")
        if base_prefix not in ("", "unknown_", "_unknown"):
            prefixes.append(base_prefix)

        for extra in p_data.get("extra_prefixes", []):
            extra_str = str(extra or "")
            if extra_str and extra_str not in prefixes:
                prefixes.append(extra_str)

        return prefixes
    except Exception:
        return []


def resolve_service_id(addon, name):
    try:
        if not name:
            return None

        clean_target = _clean(name)
        if not clean_target:
            return None

        if not os.path.exists(CONFIG_DIR):
            return None

        provider_prefixes = _active_provider_prefixes(addon)
        log_message(
            f"Service Resolver: Effective prefixes {provider_prefixes or 'none'} for [{name}]", 0
        )

        for filename in os.listdir(CONFIG_DIR):
            if not filename.lower().endswith((".conf", ".config")):
                continue

            profile_id = filename.replace(".conf", "").replace(".config", "")

            clean_profile = _clean(profile_id)
            if clean_profile and (clean_profile == clean_target):
                return profile_id

        best_match = None
        best_match_len = -1

        for filename in os.listdir(CONFIG_DIR):
            if not filename.lower().endswith((".conf", ".config")):
                continue

            profile_id = filename.replace(".conf", "").replace(".config", "")

            if provider_prefixes and not profile_id.startswith(tuple(provider_prefixes)):
                continue

            file_path = os.path.join(CONFIG_DIR, filename)

            friendly_title = None
            try:
                with open(file_path, "r", encoding="utf-8") as cf:
                    for line in cf:
                        if line.startswith("# FriendlyName ="):
                            friendly_title = line.split("=", 1)[-1].strip()
                            break
            except Exception as read_err:
                log_message(f"Service Resolver: unreadable config [{filename}]: {read_err}", 2)
                continue

            candidate_labels = [profile_id]
            if friendly_title:
                candidate_labels.append(friendly_title)

            for candidate_label in candidate_labels:
                clean_candidate = _clean(candidate_label)

                if clean_candidate and (clean_candidate in clean_target or clean_target in clean_candidate):
                    if len(clean_candidate) > best_match_len:
                        best_match = profile_id
                        best_match_len = len(clean_candidate)

        return best_match

    except Exception as e:
        log_message(f"Service Resolver: lookup error for {name}: {e}", 3)
        return None
