""" ./resources/lib/service_resolver.py """
import os
from logger import log_message
from state_manager import CONFIG_DIR


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


def resolve_service_id(addon, name):
    try:
        if not name:
            return None

        clean_target = _clean(name)
        if not clean_target:
            return None

        if not os.path.exists(CONFIG_DIR):
            return None

        best_match = None
        best_match_len = -1

        for filename in os.listdir(CONFIG_DIR):
            if not filename.lower().endswith((".conf", ".config")):
                continue

            profile_id = filename.replace(".conf", "").replace(".config", "")
            file_path = os.path.join(CONFIG_DIR, filename)

            clean_profile = _clean(profile_id)
            if clean_profile and (clean_profile == clean_target):
                return profile_id

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
