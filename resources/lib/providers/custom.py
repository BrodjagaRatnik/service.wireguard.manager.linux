""" ./resources/lib/providers/custom.py """
import os
import subprocess
from logger import log_message

LAST_ERROR = ""


def update(source_path, target_config_dir):
    global LAST_ERROR
    LAST_ERROR = ""

    try:
        if not os.path.exists(source_path):
            LAST_ERROR = f"Source file not found: {source_path}"
            log_message(f"Custom Compiler: {LAST_ERROR}", 3)
            return False

        if not os.path.exists(target_config_dir):
            os.makedirs(target_config_dir, exist_ok=True)

        with open(source_path, "r", encoding="utf-8") as f:
            raw_content = f.read()

        raw_base = os.path.basename(source_path).lower().replace(".config", "").replace(".conf", "")
        clean_words = raw_base.replace("custom_", "").replace("_", " ").replace("-", " ")
        pretty_name = f"Custom {clean_words.strip().title()}"

        b_name = raw_base if raw_base.startswith("custom_") else f"custom_{raw_base}"
        b_name = b_name.replace(" ", "_")[:15]

        dest_filename = f"{b_name}.conf"
        file_path = os.path.join(target_config_dir, dest_filename)

        header = "" if raw_content.lstrip().startswith("#") else f"# FriendlyName = {pretty_name}\n"
        output_content = f"{header}{raw_content}"

        with open(file_path, "w", encoding="utf-8") as target_file:
            target_file.write(output_content)
        os.chmod(file_path, 0o600)

        subprocess.run(
            ["nmcli", "connection", "delete", "id", b_name],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
        )

        import_res = subprocess.run(
            ["nmcli", "connection", "import", "type", "wireguard", "file", str(file_path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, check=False
        )

        if import_res.returncode != 0:
            LAST_ERROR = import_res.stderr.strip() or "nmcli import failed with no error output."
            log_message(f"Custom Compiler: nmcli import failed: {LAST_ERROR}", 3)
            return False

        subprocess.run(
            ["nmcli", "connection", "down", b_name],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
        )
        subprocess.run(
            ["nmcli", "connection", "modify", b_name,
             "ipv4.dns-priority", "100",
             "ipv6.dns-priority", "100",
             "connection.autoconnect", "no",
             "wireguard.ip4-auto-default-route", "true",
             "wireguard.peer-routes", "true"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
        )

        log_message(f"Custom Compiler: Profile {pretty_name} ({b_name}) registered successfully.", 1)
        return True

    except Exception as e:
        LAST_ERROR = str(e)
        log_message(f"Custom Compiler: Runtime failure parsing configuration module: {e}", 3)
        return False
