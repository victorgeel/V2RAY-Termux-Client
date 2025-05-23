import json
import base64
import subprocess
import os
import time
from pathlib import Path
import asyncio
import platform # For checking architecture
import zipfile  # For extracting zip files
import re # For parsing curl timing (not strictly needed if only using time_total)

# --- Textual App Imports ---
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Button, Static, Log, Input, Label, Markdown
from textual.containers import VerticalScroll, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.binding import Binding

# --- Configuration ---
SCRIPT_DIR = Path(__file__).resolve().parent
XRAY_PATH = SCRIPT_DIR / "xray"

CONFIG_STORAGE_DIR = Path.home() / ".v2ray_termux_client"
SUBS_FILE = CONFIG_STORAGE_DIR / "subscriptions.json"
LAST_SELECTED_CONFIG_FILE = CONFIG_STORAGE_DIR / "last_selected_xray_config.json"
TEST_XRAY_CONFIG_FILE_BASE = CONFIG_STORAGE_DIR / "test_xray_config_"
CURRENT_XRAY_PID_FILE = CONFIG_STORAGE_DIR / "xray.pid"

CONFIG_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

# --- Application Information Constants ---
APP_TITLE = "Termux V2Ray/Xray Client"
APP_SUB_TITLE = "Manage & Auto-Test Connections"
APP_VERSION = "0.5.0" # Final version from discussion
DEVELOPER_NAME_CONST = "Developer Victor Geek"
DEVELOPER_EMAIL_CONST = "frussel4@asu.edu"

# --- Testing Configuration ---
TEST_TARGET_URL = "http://www.gstatic.com/generate_204"
TEST_SOCKS_PORT_BASE = 20800
MAX_CONCURRENT_TESTS = 3
CURL_CONNECT_TIMEOUT = 5
CURL_TOTAL_TIMEOUT = 10

# --- Helper Functions ---
def load_subscriptions():
    if SUBS_FILE.exists():
        try:
            with open(SUBS_FILE, "r") as f: return json.load(f)
        except json.JSONDecodeError: return []
        return []

def save_subscriptions(subs):
    with open(SUBS_FILE, "w") as f: json.dump(subs, f, indent=2)

def decode_base64_content(content: str) -> list:
    try:
        return base64.b64decode(content).decode("utf-8").strip().splitlines()
    except Exception:
        return []

def parse_vmess_link(vmess_link: str) -> dict | None:
    if not vmess_link.startswith("vmess://"): return None
    try:
        decoded_json = base64.b64decode(vmess_link[8:] + '=' * (4 - len(vmess_link[8:]) % 4)).decode("utf-8")
        config = json.loads(decoded_json)
        config['add'] = config.get('add', '')
        config['port'] = int(config.get('port', 443))
        config['id'] = config.get('id', '')
        config['aid'] = int(config.get('aid', 0))
        config['net'] = config.get('net', 'tcp')
        config['type'] = config.get('type', 'none')
        config['host'] = config.get('host', '')
        config['path'] = config.get('path', '/')
        config['tls'] = config.get('tls', 'none')
        default_sni = config.get('host') or config.get('add')
        config['sni'] = config.get('sni', default_sni or "")
        default_ps = f"{config.get('add', 'Unknown')}:{config.get('port', 'N/A')}"
        config['ps'] = str(config.get('ps', default_ps)).strip() # Ensure ps is string
        config['_raw_link'] = vmess_link
        return config
    except Exception:
        return None
def generate_xray_config(server_config: dict, local_socks_port: int = 10808, local_http_port: int = 10809) -> dict | None:
    if not server_config:
        return None
    try:
        host_header = server_config.get("host", server_config.get("add"))
        xray_outbound = {
            "protocol": "vmess",
            "settings": {
                "vnext": [{
                    "address": server_config.get("add"),
                    "port": server_config.get("port"),
                    "users": [{
                        "id": server_config.get("id"),
                        "alterId": server_config.get("aid"),
                        "security": "auto"
                    }]
                }]
            },
            "streamSettings": {
                "network": server_config.get("net"),
                "security": server_config.get("tls")
            }
        }
        # ---- Indentation fixed here ----
        if server_config.get("net") == "ws":
            xray_outbound["streamSettings"]["wsSettings"] = {
                "path": server_config.get("path"),
                "headers": {"Host": host_header}
            }
        elif server_config.get("net") == "grpc":
            xray_outbound["streamSettings"]["grpcSettings"] = {
                "serviceName": server_config.get("path")
            }
        if server_config.get("tls") == "tls":
            xray_outbound["streamSettings"]["tlsSettings"] = {
                "serverName": server_config.get("sni", host_header),
                "allowInsecure": server_config.get("allowInsecure", False)
            }
            if fp := server_config.get("fp"):
                xray_outbound["streamSettings"]["tlsSettings"]["fingerprint"] = fp
        return {
            "log": {"loglevel": "none"},
            "inbounds": [
                {"port": local_socks_port, "listen": "127.0.0.1", "protocol": "socks", "settings": {"auth": "noauth", "udp": False, "ip": "127.0.0.1"}},
                {"port": local_http_port, "listen": "127.0.0.1", "protocol": "http", "settings": {}}
            ],
            "outbounds": [xray_outbound, {"protocol": "freedom", "tag": "direct"}],
            "routing": {"rules": [{"type": "field", "ip": ["geoip:private"], "outboundTag": "direct"}]}
        }
    except Exception:
        return None

def generate_xray_config(server_config: dict, local_socks_port: int = 10808, local_http_port: int = 10809) -> dict | None:
    if not server_config:
        return None
    try:
        host_header = server_config.get("host", server_config.get("add"))
        xray_outbound = {
            "protocol": "vmess",
            "settings": {
                "vnext": [{
                    "address": server_config.get("add"),
                    "port": server_config.get("port"),
                    "users": [{
                        "id": server_config.get("id"),
                        "alterId": server_config.get("aid"),
                        "security": "auto"
                    }]
                }]
            },
            "streamSettings": {
                "network": server_config.get("net"),
                "security": server_config.get("tls")
            }
        }
        if server_config.get("net") == "ws":
            xray_outbound["streamSettings"]["wsSettings"] = {
                "path": server_config.get("path"),
                "headers": {"Host": host_header}
            }
        elif server_config.get("net") == "grpc":
            xray_outbound["streamSettings"]["grpcSettings"] = {
                "serviceName": server_config.get("path")
            }
        if server_config.get("tls") == "tls":
            xray_outbound["streamSettings"]["tlsSettings"] = {
                "serverName": server_config.get("sni", host_header),
                "allowInsecure": server_config.get("allowInsecure", False)
            }
            if fp := server_config.get("fp"):
                xray_outbound["streamSettings"]["tlsSettings"]["fingerprint"] = fp
        return {
            "log": {"loglevel": "none"},
            "inbounds": [
                {"port": local_socks_port, "listen": "127.0.0.1", "protocol": "socks", "settings": {"auth": "noauth", "udp": False, "ip": "127.0.0.1"}},
                {"port": local_http_port, "listen": "127.0.0.1", "protocol": "http", "settings": {}}
            ],
            "outbounds": [xray_outbound, {"protocol": "freedom", "tag": "direct"}],
            "routing": {"rules": [{"type": "field", "ip": ["geoip:private"], "outboundTag": "direct"}]}
        }
    except Exception:
        return None

async def setup_xray_core(log_fn, show_modal_fn) -> bool:
    log_fn("Xray core not found. Attempting download setup...")
    arch_map = {"aarch64": "linux-arm64-v8a", "armv7l": "linux-arm32-v7a", "armv8l": "linux-arm64-v8a", "x86_64": "linux-64", "i686": "linux-32"}
    current_arch = platform.machine().lower()
    xray_arch_name = arch_map.get(current_arch)
    if not xray_arch_name:
        msg = f"Unsupported arch: {current_arch}. Install Xray manually."; log_fn(msg, True); await show_modal_fn(msg); return False
        latest_release_url = "https://api.github.com/repos/XTLS/Xray-core/releases/latest"
        download_url_template = "https://github.com/XTLS/Xray-core/releases/download/{tag}/Xray-{arch}.zip"
        try:
            log_fn("Fetching latest Xray release version..."); curl_cmd_tag = f"curl -sL {latest_release_url}"
            p_tag = await asyncio.create_subprocess_shell(curl_cmd_tag, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            s_tag, e_tag = await p_tag.communicate()
            if p_tag.returncode != 0:
                msg = f"Failed to fetch release info: {e_tag.decode(errors='ignore')[:100]}"; log_fn(msg, True); await show_modal_fn(msg + "\nInstall manually."); return False
                latest_tag = json.loads(s_tag.decode(errors='ignore')).get("tag_name")
                if not latest_tag:
                    msg = "Could not get latest Xray tag."; log_fn(msg, True); await show_modal_fn(msg + "\nInstall manually."); return False
                    log_fn(f"Latest Xray: {latest_tag}"); xray_zip_url = download_url_template.format(tag=latest_tag, arch=xray_arch_name)
                    xray_zip_path = SCRIPT_DIR / f"Xray-{xray_arch_name}.zip"
                    log_fn(f"Downloading: {xray_zip_url}"); curl_cmd_dl = f"curl -L -o \"{str(xray_zip_path)}\" \"{xray_zip_url}\""
                    p_dl = await asyncio.create_subprocess_shell(curl_cmd_dl, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                    _, e_dl = await p_dl.communicate()
                    if p_dl.returncode != 0:
                        msg = f"Download failed: {e_dl.decode(errors='ignore')[:100]}"; log_fn(msg,True);
                        if xray_zip_path.exists(): xray_zip_path.unlink(); await show_modal_fn(msg + "\nInstall manually."); return False
                        log_fn("Extracting Xray...");
                        with zipfile.ZipFile(xray_zip_path, 'r') as z_ref:
                            xray_exe_in_zip = next((m for m in z_ref.namelist() if m.lower().endswith("xray") and not m.endswith(".sig") and not m.endswith(".dgst")), None)
                            if not xray_exe_in_zip:
                                msg = "No 'xray' exe in zip."; log_fn(msg,True); await show_modal_fn(msg); xray_zip_path.unlink(); return False
                                with z_ref.open(xray_exe_in_zip) as src, open(XRAY_PATH, "wb") as tgt: tgt.write(src.read())
                                log_fn(f"Extracted 'xray' to {XRAY_PATH}"); os.chmod(XRAY_PATH, 0o755); log_fn("Set Xray executable.")
                                if xray_zip_path.exists(): xray_zip_path.unlink()
                                msg_ok = "Xray core setup ok! Press 'c' or restart."; log_fn(msg_ok); await show_modal_fn(msg_ok); return True
                            except Exception as e:
                                msg = f"Error Xray setup: {e}"; log_fn(msg,True);
                                if 'xray_zip_path' in locals() and xray_zip_path.exists(): xray_zip_path.unlink()
                                await show_modal_fn(msg + "\nInstall Xray manually."); return False

                                # --- Textual Screens ---
                                class AddSubScreen(ModalScreen):
                                    BINDINGS = [Binding("escape", "pop_screen", "Back", show=False)]
                                    def compose(self) -> ComposeResult: yield Vertical(Label("Subscription URL:"), Input(id="sub_url_input"), Horizontal(Button("Add",variant="primary",id="add_sub_button"), Button("Cancel",id="cancel_add_sub_button"), classes="modal_buttons"),id="add_sub_dialog")
                                    async def on_button_pressed(self, event: Button.Pressed) -> None: self.dismiss(self.query_one(Input).value.strip() if event.button.id == "add_sub_button" else None)

                                    class MessageScreen(ModalScreen):
                                        BINDINGS = [Binding("escape", "pop_screen", "OK", show=False)]
                                        def __init__(self, message: str) -> None: super().__init__(); self.message = message
                                        def compose(self) -> ComposeResult: yield Vertical(Markdown(self.message), Button("OK",variant="primary",id="ok_button"),id="message_dialog")
                                        def on_button_pressed(self, event: Button.Pressed) -> None: self.dismiss()

                                        class AboutScreen(ModalScreen):
                                            BINDINGS = [Binding("escape", "pop_screen", "Back", show=False)]
                                            def compose(self) -> ComposeResult: yield Vertical(Markdown(f"# {APP_TITLE} v{APP_VERSION}\n{APP_SUB_TITLE}\n\n---\nDev: **{DEVELOPER_NAME_CONST}** ({DEVELOPER_EMAIL_CONST})\n\nPowered by Textual & Xray."),Button("OK",id="ok_about_button"),id="about_dialog", classes="about_content")
                                            def on_button_pressed(self, event: Button.Pressed) -> None: self.dismiss()

                                            # --- Main Application ---
                                            class VpnApp(App[None]): # Added type hint for exit value
                                            CSS_PATH = "vpn_style.tcss"
                                            TITLE = APP_TITLE
                                            SUB_TITLE = APP_SUB_TITLE

                                            BINDINGS = [
                                            Binding("q", "quit_app", "Quit"), Binding("a", "add_subscription_action", "Add Sub"),
                                            Binding("u", "update_and_test_subs_action", "Update & Test All"),
                                            Binding("s", "stop_xray_action", "Stop Xray"), Binding("c", "check_xray_path_action", "Check Xray"),
                                            Binding("f1", "show_about_screen", "About"),
                                            ]

                                            subscriptions = reactive(load_subscriptions)
                                            active_servers = reactive([]) # Stores list of dicts: {"config": server_conf, "latency_ms": ms, "ps": name}
                                            active_log_message = reactive("App Started.")
                                            is_testing_servers = reactive(False)

                                            def on_mount(self) -> None:
                                                self.log_to_widget(f"Welcome to {self.TITLE} v{APP_VERSION}!");
                                                self.call_later(self.check_xray_path_and_setup, silent=True)
                                                if self.subscriptions: self.call_later(self.action_update_and_test_subs_action)

                                                def log_to_widget(self, message: str, is_error: bool = False):
                                                    try:
                                                        log_w = self.query_one("#main_log", Log); time_str = time.strftime("%H:%M:%S")
                                                        log_w.write_line(f"[{time_str}] {'[b red]' if is_error else ''}{message}{'[/b red]' if is_error else ''}")
                                                    except: pass
                                                    if not is_error or "Xray NOT found" in message : self.active_log_message = message # Update status bar for important errors too

                                                    async def show_message_modal(self, message: str):
                                                        if self.is_running: await self.push_screen(MessageScreen(message))

                                                        async def check_xray_path_and_setup(self, silent: bool = False) -> bool:
                                                            status_w = self.query_one("#xray_path_status", Static)
                                                            if not XRAY_PATH.exists() or not os.access(XRAY_PATH, os.X_OK):
                                                                msg = f"Xray NOT found/exec: {XRAY_PATH}"; status_w.update(f"[b red]{msg}[/b red]")
                                                                if not silent:
                                                                    tip = f"\nAuto-setup will try. Else, download Xray, place in '{SCRIPT_DIR}', then `chmod +x xray`."
                                                                    self.log_to_widget(msg + tip, True); await self.show_message_modal(msg + tip + "\n\nStarting auto-setup...")
                                                                    if await setup_xray_core(self.log_to_widget, self.show_message_modal):
                                                                        return await self.check_xray_path_and_setup(silent=True) # Re-check after setup
else: return False # Setup failed
else: self.log_to_widget(msg, True); return False
ok_msg = f"Xray OK: {XRAY_PATH}"; status_w.update(f"[b green]{ok_msg}[/b green]")
if not silent: self.log_to_widget(ok_msg)
return True

async def action_check_xray_path_action(self) -> None: await self.check_xray_path_and_setup(silent=False)
async def action_show_about_screen(self) -> None: await self.push_screen(AboutScreen())

def start_xray(self, server_config: dict) -> bool:
    if not asyncio.run(self.check_xray_path_and_setup(silent=True)): return False # Ensure Xray is ready (run async check synchronously for this action)
    self.stop_xray()
    xray_json = generate_xray_config(server_config)
    if not xray_json: self.log_to_widget("Fail gen main Xray cfg.", True); return False
    try:
        with open(LAST_SELECTED_CONFIG_FILE, "w") as f: json.dump(xray_json, f, indent=2)
        ps_name = server_config.get('ps', 'Unknown')
        self.log_to_widget(f"Starting Xray with '{ps_name}'.")
        proc = subprocess.Popen([str(XRAY_PATH),"run","-c",str(LAST_SELECTED_CONFIG_FILE)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        time.sleep(1.5)
        if proc.poll() is None:
            with open(CURRENT_XRAY_PID_FILE, "w") as pf: pf.write(str(proc.pid))
            self.log_to_widget(f"Xray started (PID:{proc.pid}). SOCKS:10808 HTTP:10809")
            self.query_one("#xray_path_status", Static).update(f"[b cyan]Xray Active: {ps_name}[/b cyan]")
            return True
else:
    err = proc.stderr.read().decode(errors="ignore")[:200] if proc.stderr else "N/A"
    self.log_to_widget(f"Fail start Xray. RC:{proc.returncode}. E:{err}", True)
    if LAST_SELECTED_CONFIG_FILE.exists(): LAST_SELECTED_CONFIG_FILE.unlink(True); return False
except Exception as e:
    self.log_to_widget(f"Ex start Xray: {e}", True)
    if LAST_SELECTED_CONFIG_FILE.exists(): LAST_SELECTED_CONFIG_FILE.unlink(True); return False
    return False # Fallback

def stop_xray(self) -> bool:
    pid = None
    if CURRENT_XRAY_PID_FILE.exists():
        try: pid = int(open(CURRENT_XRAY_PID_FILE).read().strip())
    except: CURRENT_XRAY_PID_FILE.unlink(True) # missing_ok=True for Pathlib
    if pid:
        try:
            os.kill(pid, subprocess.signal.SIGTERM); time.sleep(0.3)
            os.kill(pid, 0); time.sleep(0.3); os.kill(pid, subprocess.signal.SIGKILL)
            self.log_to_widget(f"Force stopped Xray (PID:{pid}).")
        except OSError: self.log_to_widget(f"Xray (PID:{pid}) exited.")
    except Exception as e: self.log_to_widget(f"Err stop Xray PID {pid}: {e}", True)
finally: CURRENT_XRAY_PID_FILE.unlink(True); self.query_one("#xray_path_status", Static).update("Xray Inactive"); return True
self.query_one("#xray_path_status", Static).update("Xray Inactive (no PID)")
return False

async def action_stop_xray_action(self) -> None:
    if self.stop_xray(): await self.show_message_modal("Main Xray stopped.")
else: await self.show_message_modal("Main Xray not running/PID missing.")

async def action_add_subscription_action(self) -> None:
    if self.is_testing_servers: await self.show_message_modal("Server testing in progress."); return
    new_url = await self.push_screen(AddSubScreen())
    if new_url:
        if any(s.get('url')==new_url for s in self.subscriptions):
            msg=f"URL '{new_url[:30]}...' exists."; self.log_to_widget(msg); await self.show_message_modal(msg); return
            idx = 1; new_name = f"Sub_{idx}"
            while new_name in {s.get("name") for s in self.subscriptions}: idx+=1; new_name=f"Sub_{idx}"
            self.subscriptions = self.subscriptions + [{"name":new_name, "url":new_url, "last_update":"Never"}]
            save_subscriptions(self.subscriptions); self.log_to_widget(f"Added: {new_name}");
            self.call_later(self.action_update_and_test_subs_action)
        else: self.log_to_widget("Add sub cancelled.")

        async def action_update_and_test_subs_action(self) -> None:
            if self.is_testing_servers: await self.show_message_modal("Test already in progress."); return
            if not self.subscriptions: await self.show_message_modal("No subs. Add with 'a'."); return
            self.is_testing_servers = True; self.active_servers = []
            self.query_one("#active_server_count", Static).update("[b yellow]Updating & Testing...[/b yellow]")
            self.log_to_widget("Updating subs & testing servers...")

            all_raw, updated_s_list = [], list(self.subscriptions)
            f_tasks = [self.fetch_single_sub(s, i) for i,s in enumerate(updated_s_list)]
            results = await asyncio.gather(*f_tasks, return_exceptions=True)
            for i, res in enumerate(results):
                if isinstance(res, tuple): idx, links = res; all_raw.extend(links); updated_s_list[idx]["last_update"] = time.strftime('%y-%m-%d %H:%M',time.localtime())
            else: self.log_to_widget(f"Err fetch sub {updated_s_list[i]['name']}: {res}", True)
            self.subscriptions=updated_s_list; save_subscriptions(self.subscriptions); self.log_to_widget(f"Total raw links: {len(all_raw)}")

            parsed_confs = []; unique_raw = set()
            for link in all_raw:
                if link not in unique_raw:
                    if p_c:=parse_vmess_link(link): parsed_confs.append(p_c)
                    unique_raw.add(link)
                    self.log_to_widget(f"Parsed {len(parsed_confs)} unique configs. Starting tests (max {MAX_CONCURRENT_TESTS} concurrent)...")
                    if not parsed_confs:
                        self.query_one("#active_server_count", Static).update("[b red]No servers to test.[/b red]")
                        self.is_testing_servers = False; return

                        test_results, semaphore = [], asyncio.Semaphore(MAX_CONCURRENT_TESTS)
                        test_tasks = [self.perform_test_with_sem(c, i, semaphore) for i, c in enumerate(parsed_confs)]
                        test_run_results = await asyncio.gather(*test_tasks, return_exceptions=True)

                        active_ones = []
                        for r_idx, res in enumerate(test_run_results):
                            server_ps = parsed_confs[r_idx].get('ps', f'Server {r_idx+1}') # Get PS for logging
                            if isinstance(res, dict) and res.get("alive"): active_ones.append(res)
                        elif isinstance(res, dict) and not res.get("alive"): self.log_to_widget(f"Test fail: {server_ps} - {res.get('message')}") # Log failed tests
                    elif isinstance(res, Exception): self.log_to_widget(f"Ex during test for {server_ps}: {res}", True)

                    active_ones.sort(key=lambda x: x.get("latency_ms", float('inf')))
                    self.active_servers = active_ones
                    self.log_to_widget(f"Testing complete. Active servers: {len(self.active_servers)}")
                    self.is_testing_servers = False # This will trigger watch_is_testing_servers if needed

                    async def fetch_single_sub(self, sub_entry: dict, index: int) -> tuple[int, list] | Exception:
                        url, name = sub_entry.get("url"), sub_entry.get("name", f"S_{index+1}")
                        self.log_to_widget(f"Fetching: {name}...");
                        try:
                            p = await asyncio.create_subprocess_shell(f"curl -L -s --connect-timeout {CURL_CONNECT_TIMEOUT} --max-time {CURL_TOTAL_TIMEOUT*2} '{url}'",stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
                            out, err = await p.communicate()
                            if p.returncode==0 and out: links=decode_base64_content(out.decode(errors="ignore")); self.log_to_widget(f"Decoded {len(links)} from {name}."); return index, links
                        else: return ConnectionError(f"Fetch {name}(RC:{p.returncode}):{err.decode(errors='ignore')[:100].strip() or 'N/A'}")
                    except Exception as e: return e

                    async def perform_test_with_sem(self, server_config: dict, test_idx: int, semaphore: asyncio.Semaphore) -> dict:
                        async with semaphore:
                        port = TEST_SOCKS_PORT_BASE + (test_idx % MAX_CONCURRENT_TESTS)
                        # self.log_to_widget(f"Testing {server_config.get('ps','?')} on port {port}...") # Can be too verbose
                        alive, latency, msg = await self.check_single_server_conn(server_config, port)
                        return {"config":server_config, "alive":alive, "latency_ms":latency, "message":msg, "ps":server_config.get("ps")}

async def check_single_server_conn(self, s_conf: dict, test_port: int) -> tuple[bool, float | None, str]:
    s_name = s_conf.get('ps', f"Unknown_{test_port}") # Give a unique fallback name
    tmp_cfg_file = TEST_XRAY_CONFIG_FILE_BASE.with_name(f"{TEST_XRAY_CONFIG_FILE_BASE.name}{test_port}.json")

    x_json = generate_xray_config(s_conf, local_socks_port=test_port, local_http_port=test_port + 1)
    if not x_json:
        return False, None, f"GenTestCfgFail:{s_name}"

# Ensure temp config file is written before try block
try:
    with open(tmp_cfg_file, "w") as f:
        json.dump(x_json, f, indent=2)
    except Exception as e:
        return False, None, f"WriteTestCfgFail:{s_name}:{str(e)[:30]}"

p = None  # Initialize Xray process variable
try:
    # Launch Xray for test
    p = await asyncio.create_subprocess_exec(
    str(XRAY_PATH), "run", "-c", str(tmp_cfg_file),
    stdout=asyncio.subprocess.DEVNULL, # Suppress Xray's stdout for tests
    stderr=asyncio.subprocess.DEVNULL  # Suppress Xray's stderr for tests unless debugging
    )
    await asyncio.sleep(1.5)  # Give Xray some time to start or fail

    if p.returncode is not None:  # Xray process exited prematurely
    return False, None, f"XrayTestStartFail:{s_name}(RC:{p.returncode})"

# Xray seems to be running, now attempt curl test
curl_cmd = f"curl -w '%{{time_total}}' -o /dev/null -s --connect-timeout {CURL_CONNECT_TIMEOUT} --max-time {CURL_TOTAL_TIMEOUT} --proxy socks5h://127.0.0.1:{test_port} {TEST_TARGET_URL}"

cp = await asyncio.create_subprocess_shell(
curl_cmd,
stdout=asyncio.subprocess.PIPE,
stderr=asyncio.subprocess.PIPE
)
cout, cerr = await cp.communicate()  # Wait for curl to complete

latency_ms: float | None = None # Explicitly type for clarity
alive: bool = False
message_detail: str = ""

if cp.returncode == 0 and cout:
    try:
        time_total_str = cout.decode().strip()
        latency_ms = float(time_total_str) * 1000  # Convert to ms
        alive = True
        message_detail = f"{int(latency_ms)}ms"
    except ValueError:  # Failed to parse time_total
    alive = False
    message_detail = f"CurlTimeParseFail:{s_name}"
else:  # Curl failed
alive = False
# cerr_msg = cerr.decode(errors='ignore').strip()[:50] if cerr else "N/A" # Can be too verbose
message_detail = f"Fail(CurlRC:{cp.returncode})"

return alive, latency_ms, message_detail

except Exception as e:
    # General exception during the try block
    return False, None, f"ExTest:{s_name}:{str(e)[:30]}"

finally:
# Cleanup logic for Xray process 'p'
if p and p.returncode is None:  # Check if process was started and might still be running
try:
    p.terminate()
    await asyncio.wait_for(p.wait(), timeout=1.0) # Wait for graceful termination
except (ProcessLookupError, asyncio.TimeoutError, Exception):
    # If terminate failed, timed out, or process already gone, try to kill
    try:
        if p.returncode is None:  # Check again before killing
        p.kill()
        await p.wait()  # Wait for kill to complete
    except (ProcessLookupError, Exception):
        pass  # Process already gone or other issue during kill

# Cleanup for the temporary config file
if tmp_cfg_file.exists():
    try:
        tmp_cfg_file.unlink(missing_ok=True)
    except Exception:
        pass # Ignore errors during cleanup of temp file if any


def compose(self) -> ComposeResult:
    yield Header();
    with Vertical(id="main_layout"):
        with Horizontal(id="status_bar"):
            yield Static("Xray status...",id="xray_path_status",classes="status_item")
            yield Static("",id="active_server_count",classes="status_item status_count")
            yield Static(self.active_log_message,id="active_log_display",classes="status_item status_log")
            yield Label("Subscriptions:",classes="section_header")
            yield VerticalScroll(id="subscriptions_list_container",classes="list_container_subs")
            yield Label("Active Servers (Sorted by Ping):",classes="section_header")
            yield VerticalScroll(id="server_list_display_container",classes="list_container_servers")
            yield Label("Log:",classes="section_header")
            yield Log(id="main_log",auto_scroll=True,max_lines=250,markup=True,highlight=True)
            yield Footer(); self.call_later(self.update_subscription_list_ui); self.call_later(self.update_active_server_list_ui)

            async def watch_subscriptions(self, _:list, new_s:list) -> None: self.update_subscription_list_ui()
            def update_subscription_list_ui(self):
                c = self.query_one("#subscriptions_list_container",VerticalScroll); c.remove_children()
                if not self.subscriptions: c.mount(Static("No subs. 'a' to add.",classes="placeholder_text"))
            else:
                for i,s in enumerate(self.subscriptions):
                    n,u,t = s.get("name",f"S_{i+1}"),s.get("url","N/A"),s.get("last_update","Never")
                    u_s = u[:35]+"..." if len(u)>38 else u; c.mount(Markdown(f"**{n}**: `{u_s}` (Upd: {t})",classes="sub_entry"))

                    async def watch_active_servers(self, _:list, new_a_s:list) -> None:
                        self.update_active_server_list_ui()
                        cnt_str = f"[b #00FF00]Active: {len(new_a_s)}[/]" if not self.is_testing_servers else "[b #FFFF00]Testing...[/]"
                        if not new_a_s and not self.is_testing_servers: cnt_str = "[b #FF0000]No active servers.[/]"
                        self.query_one("#active_server_count",Static).update(cnt_str)

                        async def watch_is_testing_servers(self, old_val: bool, new_val: bool) -> None:
                            # This watcher ensures the count string is updated once testing is complete
                            if old_val == True and new_val == False: # Testing just finished
                            cnt_str = f"[b #00FF00]Active: {len(self.active_servers)}[/]"
                            if not self.active_servers : cnt_str = "[b #FF0000]No active servers.[/]"
                            self.query_one("#active_server_count",Static).update(cnt_str)


                            def update_active_server_list_ui(self):
                                c = self.query_one("#server_list_display_container",VerticalScroll); c.remove_children()
                                if self.is_testing_servers and not self.active_servers: c.mount(Static("Testing servers...",classes="placeholder_text")); return
                                if not self.active_servers: c.mount(Static("No active servers. Update/Test with 'u'.",classes="placeholder_text")); return

                                c.mount(Static(f"Showing {len(self.active_servers)} active server(s):")) # Info line
                                for i,s_info in enumerate(self.active_servers):
                                    conf,lat = s_info["config"],s_info.get("latency_ms")
                                    ps,addr,net,tls = conf.get("ps",f"S_{i+1}"),conf.get("add","?"),conf.get("net","?"),"TLS" if conf.get("tls")=="tls" else "NoTLS"
                                    lat_s = f"{int(lat)}ms" if lat is not None else "N/A"
                                    # Using fixed-width like approach for latency for alignment
                                    display_md = f"[[b yellow]{idx+1:2}[/b yellow]] ([b #00CF00]{lat_s:>7}[/]) **{ps}** (`{addr} | {net}/{tls}`)"
                                    c.mount(Markdown(display_md, classes="server_entry"))
                                    if self.active_servers:
                                        f_active_conf, f_name = self.active_servers[0]["config"], self.active_servers[0]["config"].get("ps","1st Active")
                                        con_btn = Button(f"Connect: {f_name}",variant="success",id="connect_first_active_server_button")
                                        btn_c = Horizontal(con_btn, classes="action_buttons_container"); c.mount(btn_c)

                                        async def watch_active_log_message(self, _:str, new_msg:str)->None:
                                            try: self.query_one("#active_log_display",Static).update(new_msg[:65])
                                        except: pass

                                        async def on_button_pressed(self, event:Button.Pressed) -> None:
                                            btn_id = event.button.id
                                            if btn_id == "connect_first_active_server_button":
                                                if self.is_testing_servers: await self.show_message_modal("Testing servers. Cannot connect."); return
                                                if self.active_servers:
                                                    s_to_conn = self.active_servers[0]["config"]
                                                    self.log_to_widget(f"Connect btn for: {s_to_conn.get('ps')}")
                                                    if self.start_xray(s_to_conn): await self.show_message_modal(f"Xray started with: '{s_to_conn.get('ps')}'")
                                                else: await self.show_message_modal("Failed to start Xray.")
                                            else: await self.show_message_modal("No active servers to connect.")

                                            async def action_quit_app(self) -> None:
                                                self.log_to_widget("Quit requested. Stopping Xray..."); self.stop_xray()
                                                self.log_to_widget("Exiting application."); self.exit()

                                                VPN_APP_CSS_FALLBACK = """
                                                Screen { background: $surface; color: $text; layout: vertical; overflow-y: auto; }
                                                Header { dock: top; background: $primary; color: $text; height: 1; text-style: bold; }
                                                Footer { dock: bottom; background: $primary-darken-2; color: $text-muted; height: 1; }
                                                #main_layout { padding: 0 1; height: 1fr; }
                                                #status_bar { height: 1; background: $surface-darken-1; padding: 0 1; dock: top; grid-size: 3; grid-columns: 1fr auto 2fr; column-spacing: 1;}
                                                #xray_path_status { width: 100%; content-align: left middle; color: $text-muted; overflow: hidden; text-overflow: ellipsis;}
                                                #active_server_count { width: auto; content-align: center middle; padding: 0 1; } /* Auto width for count */
                                                #active_log_display { width: 100%; content-align: right middle; color: $text-muted; overflow: hidden; text-overflow: ellipsis;}
                                                .section_header { padding: 1 0 0 0; text-style: bold underline; color: $secondary; }
                                                .list_container_subs { border: round $primary-background-darken-2; padding: 0 1; height: auto; max-height: 5; overflow-y: auto; margin-bottom: 1; }
                                                .list_container_servers { border: round $primary-background-darken-2; padding: 0 1; height: 1fr; overflow-y: auto; margin-bottom: 1; }
                                                .sub_entry { padding: 1 0; background: $boost; border-bottom: thin dashed $primary-background-darken-3; font-size: 90%;}
                                                .server_entry { padding: 0 0; margin-bottom: 1; font-size: 85%; } /* Smaller text for servers */
                                                .server_entry Markdown > Paragraph { margin: 0; padding: 0 0 0 1;} /* Reduce markdown paragraph margin */
                                                .action_buttons_container { padding-top:1; align: center middle; height: auto; }
                                                .action_buttons_container Button { margin: 0 1; width: 1fr; }
                                                #main_log { border: panel $primary-background-darken-2; height: 7; margin-top: 1; }
                                                .placeholder_text { color: $text-muted; padding: 1; text-align: center; }
                                                #add_sub_dialog, #message_dialog, #about_dialog { padding:0 1; width:80%; max-width:60; height:auto; border:thick $secondary; background:$panel; }
                                                .modal_label { padding: 1 0; }
                                                .modal_buttons { padding-top: 1; align-horizontal: right; } .modal_buttons Button { margin-left: 1; }
                                                .about_content Markdown { padding: 1 2; }
                                                """

                                                if __name__ == "__main__":
                                                    css_f = SCRIPT_DIR / VpnApp.CSS_PATH
                                                    if not css_f.exists():
                                                        with open(css_f, "w") as f: f.write(VPN_APP_CSS_FALLBACK)
                                                        print(f"Created CSS: {css_f} with fallback.")
                                                        VpnApp().run()
