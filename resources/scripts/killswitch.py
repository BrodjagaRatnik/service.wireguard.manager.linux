""" ./resources/scripts/killswitch.py """
import os
import shutil
import subprocess
from logger import log_message

CHAIN_NAME = "LINUX_WG_KILLSWITCH"
SUDOERS_PATH = "/etc/sudoers.d/service-wireguard-manager-killswitch"


def _resolve_iptables_path():
    return shutil.which("iptables") or "/usr/sbin/iptables"


def _get_current_user():
    try:
        return subprocess.check_output(["id", "-un"], text=True).strip()
    except Exception:
        return os.environ.get("USER") or os.environ.get("LOGNAME") or ""


def _sudo_already_configured(iptables_path):
    try:
        result = subprocess.run(
            ["sudo", "-n", iptables_path, "-L", "-n"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return result.returncode == 0
    except Exception:
        return False


def ensure_killswitch_privileges():
    iptables_path = _resolve_iptables_path()

    if _sudo_already_configured(iptables_path):
        return True

    missing = []
    if not shutil.which("pkexec"):
        missing.append("pkexec (polkit)")
    if not shutil.which("visudo"):
        missing.append("visudo (sudo package)")
    if not shutil.which("sudo"):
        missing.append("sudo")

    if missing:
        log_message(
            f"KillSwitch: Cannot set up automatic privilege escalation -- missing: "
            f"{', '.join(missing)}.", 3
        )
        return False

    user = _get_current_user()
    if not user:
        log_message("KillSwitch: Could not determine current user, aborting privilege setup.", 3)
        return False

    rule_line = f"{user} ALL=(root) NOPASSWD: {iptables_path}\n"
    tmp_path = "/tmp/service-wireguard-manager-killswitch-sudoers"

    try:
        with open(tmp_path, "w") as f:
            f.write(rule_line)
        os.chmod(tmp_path, 0o440)
    except Exception as e:
        log_message(f"KillSwitch: Failed writing temporary sudoers rule: {e}", 3)
        return False

    try:
        validate = subprocess.run(["visudo", "-c", "-f", tmp_path], capture_output=True, text=True)
        if validate.returncode != 0:
            log_message(f"KillSwitch: Generated sudoers rule failed validation, aborting: {validate.stderr.strip()}", 3)
            os.remove(tmp_path)
            return False
    except Exception as e:
        log_message(f"KillSwitch: Could not validate sudoers rule: {e}", 3)
        try:
            os.remove(tmp_path)
        except Exception:
            pass
        return False

    log_message("KillSwitch: Requesting one-time authorization to enable the killswitch...", 1)

    install_result = subprocess.run(
        ["pkexec", "install", "-m", "0440", "-o", "root", "-g", "root", tmp_path, SUDOERS_PATH],
        capture_output=True, text=True
    )

    try:
        os.remove(tmp_path)
    except Exception:
        pass

    if install_result.returncode != 0:
        log_message(
            f"KillSwitch: One-time privilege setup was cancelled or failed: "
            f"{install_result.stderr.strip()}", 2
        )
        return False

    log_message("KillSwitch: One-time privilege setup complete. No further prompts will appear.", 1)
    return True


def get_live_lan_subnet(vpn_interface=None):
    try:
        from vpn_utils import get_dynamic_prefixes
        prefixes = get_dynamic_prefixes()
    except Exception:
        prefixes = ["wg", "vpn", "tun", "nord", "pia", "mullvad", "custom"]

    try:
        out = subprocess.check_output(["ip", "route", "show", "default"], text=True, stderr=subprocess.DEVNULL)
        interfaces = []
        for line in out.splitlines():
            parts = line.split()
            if "dev" in parts:
                dev_idx = parts.index("dev") + 1
                if dev_idx < len(parts):
                    interfaces.append(parts[dev_idx])

        candidate_iface = None
        for iface in interfaces:
            iface_lower = iface.lower()
            is_tunnel_like = (vpn_interface is not None and iface == vpn_interface) or \
                any(p in iface_lower for p in prefixes)
            if not is_tunnel_like:
                candidate_iface = iface
                break

        if not candidate_iface and interfaces:
            candidate_iface = interfaces[0]
            log_message(
                f"KillSwitch: Could not confidently exclude tunnel interfaces from "
                f"default route list ({interfaces}); falling back to first entry ({candidate_iface})", 2
            )

        if candidate_iface:
            if_out = subprocess.check_output(["ip", "route", "show", "dev", candidate_iface], text=True)
            for line in if_out.splitlines():
                parts = line.split()
                if parts and not line.startswith("default") and "proto" in parts:
                    return parts[0]

    except Exception as e:
        log_message(f"KillSwitch: LAN subnet detection failed: {e}", 2)

    return None


def _run_privileged(cmd_parts):
    return subprocess.run(
        ["sudo"] + cmd_parts, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True
    )


def detect_and_recover_orphan_chain():
    it = _resolve_iptables_path()

    chain_check = _run_privileged([it, "-L", CHAIN_NAME])
    if chain_check.returncode != 0:
        return False

    jump_check = _run_privileged([it, "-C", "OUTPUT", "-j", CHAIN_NAME])
    if jump_check.returncode == 0:
        return False

    log_message(
        f"KillSwitch: Orphan chain {CHAIN_NAME} detected without OUTPUT jump. "
        f"Removing inert leftover rules.", 1
    )
    for cmd in ([it, "-F", CHAIN_NAME], [it, "-X", CHAIN_NAME]):
        result = _run_privileged(cmd)
        stderr_txt = result.stderr.strip().lower()
        if result.returncode != 0 \
                and "no chain" not in stderr_txt \
                and "does not exist" not in stderr_txt:
            log_message(f"KillSwitch: Orphan cleanup failed ({' '.join(cmd)}): {stderr_txt}", 2)
            return False
    return True


class ZeroHardcodeKillSwitch:
    def __init__(self, vpn_server_ip, vpn_interface=None):
        self.vpn_server_ip = vpn_server_ip
        self.vpn_interface = vpn_interface
        self.enabled = False
        self.iptables = _resolve_iptables_path()
        self.last_error = ""

    def enable(self):
        if self.enabled:
            return True

        if not ensure_killswitch_privileges():
            self.last_error = "privilege setup unavailable"
            log_message("KillSwitch: Cannot engage without configured privileges.", 3)
            return False

        live_lan = get_live_lan_subnet(vpn_interface=self.vpn_interface)
        if not live_lan:
            self.last_error = "LAN subnet detection failed"
            log_message(
                "KillSwitch: Could not reliably detect the local LAN subnet. "
                "Refusing to engage the killswitch.", 3
            )
            return False

        log_message(f"KillSwitch: Target local subnet detected as {live_lan}", 0)
        it = self.iptables

        _run_privileged([it, "-D", "OUTPUT", "-j", CHAIN_NAME])
        _run_privileged([it, "-F", CHAIN_NAME])
        _run_privileged([it, "-X", CHAIN_NAME])

        commands = [
            [it, "-N", CHAIN_NAME],
            [it, "-A", CHAIN_NAME, "-o", "lo", "-j", "ACCEPT"],
            [it, "-A", CHAIN_NAME, "-d", live_lan, "-j", "ACCEPT"],
            [it, "-A", CHAIN_NAME, "-d", self.vpn_server_ip, "-j", "ACCEPT"],
        ]

        if self.vpn_interface:
            commands.append([it, "-A", CHAIN_NAME, "-o", self.vpn_interface, "-j", "ACCEPT"])
        else:
            log_message("KillSwitch: No vpn_interface provided -- tunnel traffic has no explicit allow rule.", 2)

        commands += [
            [it, "-A", CHAIN_NAME, "-p", "udp", "--dport", "53", "-j", "DROP"],
            [it, "-A", CHAIN_NAME, "-p", "tcp", "--dport", "53", "-j", "DROP"],
            [it, "-A", CHAIN_NAME, "-m", "owner", "!", "--gid-owner", "root", "-j", "DROP"],
            [it, "-A", CHAIN_NAME, "-j", "DROP"],
            [it, "-I", "OUTPUT", "1", "-j", CHAIN_NAME],
        ]

        all_ok = True
        for cmd in commands:
            result = _run_privileged(cmd)
            if result.returncode != 0:
                stderr_txt = result.stderr.strip().lower()
                if "already exists" in stderr_txt:
                    continue
                log_message(f"KillSwitch: Command failed ({' '.join(cmd)}): {result.stderr.strip()}", 2)
                all_ok = False

        if not all_ok:
            self.last_error = "iptables rule application failed (rolled back)"
            log_message("KillSwitch: One or more rules failed to apply. Rolling back.", 3)
            self._cleanup()
            self.enabled = False
            return False

        self.enabled = True
        log_message("KillSwitch: Firewall killswitch successfully engaged.", 0)
        return True

    def _cleanup(self):
        it = self.iptables
        commands = [
            [it, "-D", "OUTPUT", "-j", CHAIN_NAME],
            [it, "-F", CHAIN_NAME],
            [it, "-X", CHAIN_NAME],
        ]
        for cmd in commands:
            _run_privileged(cmd)

    def disable(self, reason="disengaged"):
        if not self.enabled:
            return
        self._cleanup()
        self.enabled = False
        if reason == "switch":
            log_message("KillSwitch: Firewall rules temporarily opened for connection cycle.", 1)
        elif reason == "recovery":
            log_message("KillSwitch: Purging firewall rules for emergency tunnel recovery.", 1)
        else:
            log_message("KillSwitch: Firewall killswitch successfully deactivated.", 1)


def purge_stale_killswitch():
    it = _resolve_iptables_path()
    commands = [
        [it, "-D", "OUTPUT", "-j", CHAIN_NAME],
        [it, "-F", CHAIN_NAME],
        [it, "-X", CHAIN_NAME],
    ]
    for cmd in commands:
        result = _run_privileged(cmd)
        stderr_txt = result.stderr.strip().lower()
        if result.returncode != 0 \
                and "no chain" not in stderr_txt \
                and "does not exist" not in stderr_txt \
                and "bad rule" not in stderr_txt:
            log_message(f"KillSwitch: Stale purge command failed ({' '.join(cmd)}): {stderr_txt}", 2)
            return
    log_message("KillSwitch: Stale killswitch rules purged for clean startup.", 0)
