""" From: https://github.com/mullvad/wg-tools
    HOST = 'https://api.mullvad.net'
        url = "https://api.mullvad.net/public/relays/wireguard/v1/"
.resources/lib/providers/mullvad.py"""
import configparser
import functools
import gzip
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request
from logger import log_message
from providers.nm_manager import nm_register_profile
from state_manager import get_file_path


class MullvadApi:
    HOST = 'https://api.mullvad.net'
    MAX_RETRIES = 3
    RETRY_DELAY_SECONDS = 2.0

    def __init__(self, account_number):
        self.account_number = account_number

    def new_device(self, public_key, hijack_dns=False):
        body = {
            "pubkey": public_key,
            "hijack_dns": hijack_dns,
        }
        return self._api(f"{MullvadApi.HOST}/accounts/v1/devices", body)

    def list_devices(self):
        return self._api(f"{MullvadApi.HOST}/accounts/v1/devices")

    @functools.cached_property
    def web_token(self) -> str:
        from wm_utils import safe_decrypt_password
        body = {
            "account_number": safe_decrypt_password(self.account_number),
        }
        req = urllib.request.Request(f"{MullvadApi.HOST}/auth/v1/webtoken")
        req.add_header("Content-Type", "application/json")
        req.add_header(
            "User-Agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        try:
            with urllib.request.urlopen(req, json.dumps(body).encode(), timeout=10) as response:
                data = json.load(response)
            return data["access_token"]
        except urllib.error.HTTPError as e:
            error_data = MullvadApi.get_response(e)
            detail = error_data.get("detail", "Unknown authentication error")
            log_message(f"Mullvad API authentication token rejected: {detail}", 3)
            raise
        except Exception as e:
            log_message(f"Unexpected connection error while fetching Mullvad web token: {e}", 3)
            raise

    def _api(self, url, body=None):
        last_err = None
        for attempt in range(self.MAX_RETRIES):
            try:
                req = urllib.request.Request(url)
                req.add_header("Authorization", f"Bearer {self.web_token}")
                req.add_header("Accept-Encoding", "gzip")
                req.add_header(
                    "User-Agent",
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )

                if body:
                    req.add_header("Content-Type", "application/json")

                with urllib.request.urlopen(
                    req, data=json.dumps(body).encode() if body else None, timeout=10
                ) as response:
                    return self.get_response(response)

            except urllib.error.HTTPError:

                raise
            except Exception as e:
                last_err = e
                log_message(
                    f"Mullvad API _api() attempt {attempt + 1}/{self.MAX_RETRIES} "
                    f"failed for {url}: {e}", 2
                )
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.RETRY_DELAY_SECONDS)

        log_message(f"Network backend subsystem failure accessing Mullvad endpoint {url}: {last_err}", 3)
        raise last_err

    @staticmethod
    def default_dns_servers() -> str:
        return "10.64.0.1"

    @staticmethod
    @functools.cache
    def all_wireguard_relays():
        cache_file = get_file_path('mullvad_relays_cache')
        url = f"{MullvadApi.HOST}/public/relays/wireguard/v1/"

        req = urllib.request.Request(url)
        req.add_header("Accept", "application/json")
        req.add_header(
            "User-Agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )

        raw_data = None
        source = "live"
        try:
            with urllib.request.urlopen(req, timeout=4) as response:
                raw_data = json.loads(response.read().decode("utf-8"))

            if raw_data and isinstance(raw_data, dict) and cache_file is not None:
                with open(cache_file, "w") as cf:
                    json.dump(raw_data, cf)

        except Exception as net_err:
            source = "cache"
            if cache_file is not None and os.path.exists(cache_file):
                try:
                    with open(cache_file, "r") as cf:
                        raw_data = json.load(cf)
                    log_message(
                        f"Mullvad API network lookup blocked ({net_err}). "
                        f"Recovered relay list from local storage cache.", 2
                    )
                except Exception as cache_err:
                    log_message(
                        f"Mullvad API storage cache unreadable: {cache_err}", 3
                    )
            else:
                log_message("Mullvad Debug: Recovery failed - No history cache file exists on disk", 0)

            if not raw_data:
                log_message(
                    f"Failed to fetch global WireGuard infrastructure "
                    f"lists from Mullvad servers: {net_err}", 3
                )
                raise net_err

        flat_relays = []
        if isinstance(raw_data, dict) and "countries" in raw_data:
            for country in raw_data["countries"]:
                c_name = country.get("name", "")
                c_code = country.get("code", "")
                if "cities" in country:
                    for city in country["cities"]:
                        city_name = city.get("name", "")
                        if "relays" in city:
                            for r in city["relays"]:
                                if isinstance(r, dict):
                                    r["country_name"] = c_name
                                    r["country_code"] = c_code
                                    r["city_name"] = city_name

                                    h_name = str(r.get("hostname", "")).lower()
                                    srv_p = h_name.split("-")[-1] if "-" in h_name else ""
                                    r["owned"] = srv_p.startswith("0") if srv_p else False

                                    flat_relays.append(r)

        log_message(f"Mullvad: {len(flat_relays)} relays loaded ({source}).", 0)
        return flat_relays

    @staticmethod
    def wireguard_relays(**kwargs):
        try:
            relays = MullvadApi.all_wireguard_relays()
        except Exception as e:
            log_message(f"Mullvad: all_wireguard_relays() raised: {e}", 0)
            return []

        location_prefix = kwargs.get("location_prefix", "")
        if location_prefix:
            target_countries = [c.strip().lower() for c in location_prefix.split(",") if c.strip()]
            if target_countries:
                filtered_relays = []
                for r in relays:
                    host = str(r.get("hostname", "")).lower()
                    country_text = str(r.get("country", "")).lower()
                    match_found = False
                    for tc in target_countries:
                        if host.startswith(f"{tc}-") or tc in country_text:
                            match_found = True
                            break
                    if match_found:
                        filtered_relays.append(r)
                relays = filtered_relays

        if kwargs.get("active", False):
            relays = [r for r in relays if r.get("active", True)]

        if kwargs.get("owned", False):
            relays = [r for r in relays if r.get("owned", False)]

        return relays

    @staticmethod
    def get_response(response):
        try:
            if response.headers.get("Content-Encoding") == "gzip":
                return json.loads(gzip.decompress(response.read()).decode("utf-8"))
            else:
                if hasattr(response, "read"):
                    return json.loads(response.read().decode("utf-8"))
                return json.load(response)
        except Exception as e:
            log_message(f"Failed to decompress or parse JSON payload from API server: {e}", 3)
            raise


class MullvadConfig:
    def __init__(self, output_dir, wg_dns, wg_relay_port, mtu):
        self.output_dir = output_dir
        self.wg_dns = wg_dns
        self.wg_relay_port = wg_relay_port
        self.mtu = mtu

    def create_wg_configs(self, relays, device, privatekey, dns_str, multihop_server, progress=None) -> None:
        try:
            output_dir = pathlib.Path(self.output_dir).expanduser()
            output_dir.mkdir(exist_ok=True, parents=True)
        except Exception as e:
            log_message(f"Failed to instantiate target configuration directory path structural entities: {e}", 3)
            raise

        try:
            for old_file in output_dir.glob("mullvad_*.*"):
                old_file.unlink()
            for old_file in output_dir.glob("mld_*.*"):
                old_file.unlink()
        except Exception as clean_err:
            log_message(f"Failed to purge existing Mullvad platform assets from target layout: {clean_err}", 2)

        successful_profiles = 0
        target_relays = []
        if isinstance(relays, dict) and "countries" in relays:
            for country in relays["countries"]:
                for city in country.get("cities", []):
                    for r in city.get("relays", []):
                        r["country_code"] = country.get("code", "vpn")
                        target_relays.append(r)
        elif isinstance(relays, list):
            target_relays = relays

        total_relays = len(target_relays)
        used_names = {}

        for idx, relay in enumerate(target_relays, start=1):
            if progress and progress.iscanceled():
                log_message("Mullvad Config: Generation cancelled by user.", 2)
                break

            hostname = relay.get("hostname", "")

            if progress:
                pct = 50 + int(((idx - 1) * 50) / total_relays)
                progress.update(pct, "Profile %d of %d: %s" % (idx, total_relays, hostname))

            try:
                self.create_linux_config(
                    output_dir, relay, device, privatekey, dns_str,
                    multihop_server, used_names=used_names
                )
                successful_profiles += 1
            except Exception as e:
                log_message(
                    f"Skipping corrupt configuration block rendering pass for target host "
                    f"{hostname}: {e}", 2
                )

        if successful_profiles == 0:
            log_message("Core Update: Mullvad profile database update FAILED. No valid server profiles could be generated.", 3)
            raise RuntimeError("Mullvad compiler failed: 0 profiles generated.")

        log_message(f"Core Update: Mullvad profile DB updated successfully. Registered {successful_profiles} profiles.", 1)

    def create_linux_config(self, output_dir, relay, device, privatekey, dns_str,
                            multihop_server=None, used_names=None) -> None:
        hostname = relay.get("hostname")
        if not hostname:
            raise ValueError("Mullvad Profile Compiler: Missing hostname in relay definition object.")

        host_parts = hostname.split("-")
        c_code = relay.get("country_code") or host_parts[0].lower()
        city_code = relay.get("city_code") or (host_parts[1].lower() if len(host_parts) > 1 else "")
        srv_num = relay.get("srv_number") or host_parts[-1]

        server_pubkey = (
            relay.get("public_key") or
            relay.get("endpoint_data", {}).get("wireguard", {}).get("public_key") or
            relay.get("wg_public_key") or
            relay.get("pubkey")
        )
        if not server_pubkey:
            log_message(f"CRITICAL DEBUG: Relay dictionary keys for {hostname}: {list(relay.keys())}", 2)
            raise ValueError(f"Mullvad Profile Compiler: Cryptographic public key not found for {hostname}")

        host = relay.get("ipv4_addr_in")
        remote_port = self.wg_relay_port

        if used_names is None:
            used_names = {}
        city_seg = city_code or (host_parts[1].lower() if len(host_parts) > 1 else "")

        if multihop_server:
            raw_name = f"mullvad_{c_code}{city_seg}{srv_num}"
            remote_server = multihop_server
            host = (
                remote_server.get("ipv4_addr_in") or
                remote_server.get("endpoint_data", {}).get("wireguard", {}).get("ipv4_addr_in")
            )
            remote_port = relay.get("multihop_port", self.wg_relay_port)
        else:
            raw_name = f"mullvad_{c_code}{city_seg}{srv_num}"

        if len(raw_name) > 15:
            raw_name = f"mld_{c_code}{city_seg}{srv_num}"

        base_name = raw_name[:15]

        if base_name in used_names and used_names[base_name] != hostname:
            idx = 2
            while True:
                tag = str(idx)
                alt = f"{raw_name[:15 - len(tag)]}{tag}"
                if alt not in used_names or used_names[alt] == hostname:
                    base_name = alt
                    break
                idx += 1
        used_names[base_name] = hostname

        dest_filename = f"{base_name}.conf"
        display_name = base_name

        if not host:
            raise ValueError(f"Mullvad Profile Compiler: No valid IPv4 endpoint address found for {hostname}")

        file_path = output_dir / dest_filename
        file_path.touch(mode=0o600, exist_ok=True)

        raw_address = device.get("ipv4_address")
        if isinstance(raw_address, list) and len(raw_address) > 0:
            raw_address = raw_address[0]
        clean_address = str(raw_address).split("/")[0].strip()
        friendly_city = str(relay.get("city_name", city_code.upper())).strip()
        friendly_country = str(relay.get("country_name", c_code.upper())).strip()

        if multihop_server:
            friendly_name = f"Mullvad {friendly_country} ({friendly_city}) {srv_num} [Multihop]"
        else:
            friendly_name = f"Mullvad {friendly_country} ({friendly_city}) {srv_num}"

        dest_lines = [
            f"# FriendlyName = {friendly_name}",
            "[Interface]",
            f"PrivateKey = {privatekey}",
            f"Address = {clean_address}/32",
            f"DNS = {dns_str}",
            f"MTU = {self.mtu}",
            "\n[Peer]",
            f"PublicKey = {server_pubkey}",
            f"Endpoint = {host}:{remote_port}",
            "AllowedIPs = 0.0.0.0/0, ::/0",
            "PersistentKeepalive = 25"
        ]

        try:
            with file_path.open("w", encoding="utf-8") as target_file:
                target_file.write("\n".join(dest_lines) + "\n")

            extra_modify_args = [
                "ipv4.dns-priority", "0",
                "ipv6.dns-priority", "0",
                "wireguard.ip4-auto-default-route", "true",
                "wireguard.peer-routes", "true"
            ]
            if nm_register_profile(display_name, file_path, extra_modify_args) is False:
                raise RuntimeError(f"NM registration failed for {display_name}")

            log_message(f"Mullvad Compiler: Profile {display_name} successfully registered in NetworkManager.", 0)
        except Exception as e:
            log_message(f"Failed writing or registering local NetworkManager profile to node {file_path}: {e}", 3)
            raise


class Mullvad:
    def __init__(self, args):
        from wm_utils import safe_decrypt_password
        clean_account = safe_decrypt_password(args.account_number)
        self.mullvad_api = MullvadApi(clean_account)
        self.mullvad_config = MullvadConfig(args.output_dir, args.wg_dns, args.wg_relay_port, args.mtu)

        self._settings_file = args.settings_file
        self._wg_multihop_server = args.wg_multihop_server
        self._wg_relays_filter = {
            "location_prefix": args.filter,
            "active": args.wg_active,
            "owned": args.wg_owned,
        }

        self._config = configparser.ConfigParser()
        self._settings_file = pathlib.Path(self._settings_file).expanduser()

    def run(self, progress=None):
        try:
            loc_filter = self._wg_relays_filter.get("location_prefix", "")
            if not loc_filter or not str(loc_filter).strip():
                log_message("Mullvad Core: Aborting operation. Country selection filter string is empty.", 2)
                import xbmcgui
                if xbmcgui:
                    title = "[B][COLOR FFFF0000]No Countries Selected[/COLOR][/B]"
                    msg = (
                        "[COLOR FFE6E6FA]Please go to the add-on settings menu, "
                        "select your target countries, and try again.[/COLOR]"
                    )
                    xbmcgui.Dialog().ok(title, msg)
                return False

            if progress:
                progress.update(20, "Resolving multihop entry...")
            multihop_server = self.get_multihop_server()

            if progress:
                progress.update(30, "Fetching relay list...")
            relays = self.get_relays()

            if progress:
                progress.update(40, "Loading WireGuard key pair...")
            private_key, public_key = self.get_key_pair()

            if progress:
                progress.update(45, "Registering device with Mullvad...")
            device = self.get_device(public_key) or self.create_device(public_key)

            if self.mullvad_config.wg_dns:
                dns_str = ", ".join([str(x) for x in self.mullvad_config.wg_dns])
            else:
                dns_str = "100.64.0.63, 100.64.0.6"

            if device:
                if progress:
                    progress.update(50, "Compiling profiles...")
                self.mullvad_config.create_wg_configs(relays, device, private_key, dns_str, multihop_server, progress=progress)
        except Exception as e:
            log_message(f"Execution runtime failed within the main processing execution block: {e}", 3)
            sys.exit(1)

    def get_privatekey(self) -> str:
        self._config.read(self._settings_file)
        try:
            return self._config.get("Interface", "privatekey")
        except (configparser.NoOptionError, configparser.NoSectionError) as e:
            log_message(
                f"Required configuration parameter 'privatekey' missing from section 'Interface' "
                f"inside {self._settings_file}: {e}", 3
            )
            sys.exit(1)

    def save_privatekey(self, privatekey) -> bool:
        try:
            self._settings_file.parent.mkdir(parents=True, exist_ok=True)
            self._settings_file.touch(mode=0o600, exist_ok=True)
            with self._settings_file.open("w") as _file:
                if not self._config.has_section("Interface"):
                    self._config.add_section("Interface")
                self._config.set("Interface", "privatekey", privatekey)
                self._config.write(_file)
            log_message(f"Mullvad System Registry: Key written to {self._settings_file}", 1)
            return True
        except configparser.DuplicateSectionError as d_err:
            log_message(f"Mullvad Configuration Conflict: Interface sector structurally persistent: {d_err}", 3)
            raise
        except Exception as e:
            log_message(
                f"Failed to record state variables onto permanent local platform registers "
                f"{self._settings_file}: {e}", 3
            )
            raise

    def get_device(self, public_key):
        try:
            for device in self.mullvad_api.list_devices():
                if public_key == device["pubkey"]:
                    return device
            return None
        except urllib.error.HTTPError as e:
            self.handle_mullvad_api_error(e)

    def create_device(self, public_key):
        try:
            response = self.mullvad_api.new_device(public_key=public_key, hijack_dns=False)
            return response
        except urllib.error.HTTPError as e:
            self.handle_mullvad_api_error(e)

    def get_key_pair(self):
        import providers.mullvad_utils as local_utils
        if self._settings_file.is_file():
            private_key = self.get_privatekey()
        else:
            private_key = local_utils.generate_privatekey()
            self.save_privatekey(private_key)

        public_key = local_utils.generate_publickey(private_key)
        return (private_key, public_key)

    def get_multihop_server(self):
        if not self._wg_multihop_server or str(self._wg_multihop_server).strip() == "":
            return None

        try:
            multihop_servers = [
                r for r in MullvadApi.all_wireguard_relays()
                if r["hostname"].startswith(self._wg_multihop_server)
            ]
        except Exception:
            log_message("Aborting multihop node assessment: Could not acquire downstream server directories", 3)
            sys.exit(1)

        if len(multihop_servers) == 1:
            return multihop_servers[0]
        else:
            log_message(
                f"Multihop node selection conflict: Expected exactly 1 match for prefix '{self._wg_multihop_server}', "
                f"found {len(multihop_servers)} matching profiles", 3
            )
            sys.exit(1)

    def get_relays(self):
        relays = MullvadApi.wireguard_relays(**self._wg_relays_filter)
        if not relays:
            log_message("No valid endpoint nodes survived the filtering criteria matrices", 3)
            sys.exit(1)
        return relays

    def handle_mullvad_api_error(self, err):
        try:
            error_message = MullvadApi.get_response(err)
            error_code = error_message.get("code")
            detail_message = error_message.get("detail", "API communication failure")

            if error_code == "MAX_DEVICES_REACHED" or "maximum number of devices" in detail_message.lower():
                log_message("Mullvad: Device account limit reached. Informing user via Kodi UI.", 2)
                import xbmcgui
                title = "[B][COLOR FFFF0000]Mullvad Device Limit Reached[/COLOR][/B]"
                msg = (
                    "[COLOR FFE6E6FA]Your account already has 5 registered keys.\n"
                    "Please log in to your account page on the web at:\n"
                    "[B]mullvad.net/account[/B]\n"
                    "and remove a stale device slot to continue.[/COLOR]"
                )
                xbmcgui.Dialog().ok(title, msg)
                sys.exit(1)

            if error_code == "PUBKEY_IN_USE":
                log_message("Mullvad error: Cryptographic device key is already registered elsewhere", 3)
            elif error_code == "INVALID_ACCOUNT":
                log_message("Mullvad error: Provided account token identification is unrecognized", 3)
            else:
                log_message(f"Mullvad API constraint occurred: {detail_message}", 3)
        except Exception:
            log_message(f"Mullvad service gateway dropped packet transaction with failure code: {err.code}", 3)
        sys.exit(1)
