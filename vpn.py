import json
import base64
import subprocess
import os
import time
from pathlib import Path
import asyncio
import re # For parsing curl timing

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
TEST_XRAY_CONFIG_FILE_BASE = CONFIG_STORAGE_DIR / "test_xray_config_" # For concurrent tests
CURRENT_XRAY_PID_FILE = CONFIG_STORAGE_DIR / "xray.pid"

CONFIG_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

# --- Application Information Constants ---
APP_TITLE = "Termux V2Ray/Xray Client"
APP_SUB_TITLE = "Manage & Test Connections"
APP_VERSION = "0.4.0" # Enhanced version
DEVELOPER_NAME_CONST = "Developer Victor Geek"
DEVELOPER_EMAIL_CONST = "frussel4@asu.edu"

# --- Testing Configuration ---
TEST_TARGET_URL = "http://www.gstatic.com/generate_204" # Google's No Content page
TEST_SOCKS_PORT_BASE = 20800 # Base port for testing Xray instances
MAX_CONCURRENT_TESTS = 3 # Limit simultaneous tests to avoid overwhelming system
CURL_CONNECT_TIMEOUT = 5 # Seconds for curl connection phase
CURL_TOTAL_TIMEOUT = 10  # Seconds for total curl operation

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
    except Exception: return []

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
        config['ps'] = config.get('ps', default_ps).strip()
        config['_raw_link'] = vmess_link
        return config
    except Exception: return None

def generate_xray_config(server_config: dict, local_socks_port: int = 10808, local_http_port: int = 10809) -> dict | None:
    if not server_config: return None
    try:
        host_header = server_config.get("host", server_config.get("add"))
        xray_outbound = {
            "protocol": "vmess", "settings": {"vnext": [{"address": server_config.get("add"), "port": server_config.get("port"), "users": [{"id": server_config.get("id"), "alterId": server_config.get("aid"), "security": server_config.get("scy", "auto")}]}]},
            "streamSettings": {"network": server_config.get("net"), "security": server_config.get("tls")} }
        if server_config.get("net") == "ws": xray_outbound["streamSettings"]["wsSettings"] = {"path": server_config.get("path"), "headers": {"Host": host_header}}
        elif server_config.get("net") == "grpc": xray_outbound["streamSettings"]["grpcSettings"] = {"serviceName": server_config.get("path")}
        if server_config.get("tls") == "tls":
            xray_outbound["streamSettings"]["tlsSettings"] = {"serverName": server_config.get("sni", host_header), "allowInsecure": server_config.get("allowInsecure", False)}
            if fp := server_config.get("fp"): xray_outbound["streamSettings"]["tlsSettings"]["fingerprint"] = fp
        return {
            "log": {"loglevel": "none"}, # Quieter logs for test/main instances
            "inbounds": [
                {"port": local_socks_port, "listen": "127.0.0.1", "protocol": "socks", "settings": {"auth": "noauth", "udp": False, "ip": "127.0.0.1"}}, # UDP false for simpler testing
                {"port": local_http_port, "listen": "127.0.0.1", "protocol": "http", "settings": {}} ],
            "outbounds": [xray_outbound, {"protocol": "freedom", "tag": "direct"}],
            "routing": {"rules": [{"type": "field", "ip": ["geoip:private"], "outboundTag": "direct"}]} }
    except Exception: return None

# --- Textual Screens ---
class AddSubScreen(ModalScreen):
    BINDINGS = [Binding("escape", "pop_screen", "Back", show=False)]
    def compose(self) -> ComposeResult:
        yield Vertical(Label("Enter Subscription URL:", classes="modal_label"), Input(placeholder="https://example.com/sub", id="sub_url_input"), Horizontal(Button("Add", variant="primary", id="add_sub_button"), Button("Cancel", id="cancel_add_sub_button"), classes="modal_buttons"), id="add_sub_dialog")
    async def on_button_pressed(self, event: Button.Pressed) -> None: self.dismiss(self.query_one(Input).value.strip() if event.button.id == "add_sub_button" else None)

class MessageScreen(ModalScreen):
    BINDINGS = [Binding("escape", "pop_screen", "OK", show=False)]
    def __init__(self, message: str) -> None: super().__init__(); self.message = message
    def compose(self) -> ComposeResult: yield Vertical(Markdown(self.message), Button("OK", variant="primary", id="ok_button"), id="message_dialog")
    def on_button_pressed(self, event: Button.Pressed) -> None: self.dismiss()

class AboutScreen(ModalScreen):
    BINDINGS = [Binding("escape", "pop_screen", "Back", show=False)]
    def compose(self) -> ComposeResult:
        yield Vertical(Markdown(f"# {APP_TITLE}\nVersion: {APP_VERSION}\n\n{APP_SUB_TITLE}\n\n---\nDeveloped by:\n**{DEVELOPER_NAME_CONST}**\n({DEVELOPER_EMAIL_CONST})\n\nPowered by Textual and Xray."), Button("OK", variant="primary", id="ok_about_button"), id="about_dialog", classes="about_content")
    def on_button_pressed(self, event: Button.Pressed) -> None: self.dismiss()

# --- Main Application ---
class VpnApp(App):
    CSS_PATH = "vpn_style.tcss"
    TITLE = APP_TITLE
    SUB_TITLE = APP_SUB_TITLE

    BINDINGS = [
        Binding("q", "quit_app", "Quit"), Binding("a", "add_subscription_action", "Add Sub"),
        Binding("u", "update_and_test_subs_action", "Update & Test Subs"), # Changed 'u' action
        Binding("s", "stop_xray_action", "Stop Xray"), Binding("c", "check_xray_path_action", "Check Xray"),
        Binding("f1", "show_about_screen", "About"),
    ]

    subscriptions = reactive(load_subscriptions())
    parsed_server_configs = reactive([]) # Raw parsed from subs
    active_servers = reactive([]) # Tested, filtered, and sorted servers
    active_log_message = reactive("App Started.")
    is_testing_servers = reactive(False)

    def on_mount(self) -> None:
        self.log_to_widget(f"Welcome to {self.TITLE} v{APP_VERSION}!")
        self.call_later(self.check_xray_path, silent=True)
        if self.subscriptions: # Auto-update and test on startup if subs exist
            self.call_later(self.action_update_and_test_subs_action)


    def log_to_widget(self, message: str, is_error: bool = False):
        try:
            log_widget = self.query_one("#main_log", Log)
            current_time = time.strftime("%H:%M:%S")
            styled_message = f"[b red]{message}[/b red]" if is_error else message
            log_widget.write_line(f"[{current_time}] {styled_message}")
        except Exception: pass
        if not is_error: self.active_log_message = message


    async def show_message_modal(self, message: str):
        if self.is_running: await self.push_screen(MessageScreen(message))

    def check_xray_path(self, silent: bool = False) -> bool:
        path_status_widget = self.query_one("#xray_path_status", Static)
        if not XRAY_PATH.exists() or not os.access(XRAY_PATH, os.X_OK):
            msg = f"Xray NOT found/exec: {XRAY_PATH}"
            tip = f"\nDownload Xray, place as 'xray' in '{SCRIPT_DIR}', then `chmod +x xray`."
            self.log_to_widget(msg + tip, is_error=True)
            path_status_widget.update(f"[b red]{msg}[/b red]")
            if not silent: self.call_later(self.show_message_modal, msg + tip)
            return False
        status_msg = f"Xray OK: {XRAY_PATH}"
        if not silent: self.log_to_widget(status_msg) # Log success only if not silent startup
        path_status_widget.update(f"[b green]{status_msg}[/b green]")
        return True
    
    async def action_check_xray_path_action(self) -> None: self.check_xray_path()
    async def action_show_about_screen(self) -> None: await self.push_screen(AboutScreen())

    def start_xray(self, server_config_to_run: dict) -> bool:
        if not self.check_xray_path(silent=True): return False
        self.stop_xray() # Stop any existing main instance
        xray_json_config = generate_xray_config(server_config_to_run) # Uses default ports 10808/10809
        if not xray_json_config: self.log_to_widget("Failed to generate main Xray config.", is_error=True); return False
        try:
            with open(LAST_SELECTED_CONFIG_FILE, "w") as f: json.dump(xray_json_config, f, indent=2)
            self.log_to_widget(f"Starting Xray with '{server_config_to_run.get('ps', 'Unknown')}'.")
            process = subprocess.Popen([str(XRAY_PATH), "run", "-c", str(LAST_SELECTED_CONFIG_FILE)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            time.sleep(1.5) # Allow Xray to start/fail
            if process.poll() is None:
                with open(CURRENT_XRAY_PID_FILE, "w") as pf: pf.write(str(process.pid))
                self.log_to_widget(f"Xray started (PID:{process.pid}). SOCKS:10808, HTTP:10809")
                return True
            else:
                err = process.stderr.read().decode(errors="ignore")[:200] if process.stderr else "No stderr"
                self.log_to_widget(f"Failed to start Xray. RC:{process.returncode}. Err:{err}", is_error=True)
                if LAST_SELECTED_CONFIG_FILE.exists(): LAST_SELECTED_CONFIG_FILE.unlink(missing_ok=True)
                return False
        except Exception as e:
            self.log_to_widget(f"Exception starting Xray: {e}", is_error=True)
            if LAST_SELECTED_CONFIG_FILE.exists(): LAST_SELECTED_CONFIG_FILE.unlink(missing_ok=True)
            return False

    def stop_xray(self) -> bool:
        pid = None
        if CURRENT_XRAY_PID_FILE.exists():
            try: pid = int(open(CURRENT_XRAY_PID_FILE).read().strip())
            except ValueError: CURRENT_XRAY_PID_FILE.unlink(missing_ok=True)
        if pid:
            try:
                os.kill(pid, subprocess.signal.SIGTERM); time.sleep(0.5)
                os.kill(pid, 0); time.sleep(0.5); os.kill(pid, subprocess.signal.SIGKILL)
                self.log_to_widget(f"Force stopped main Xray (PID:{pid}).")
            except OSError: self.log_to_widget(f"Main Xray (PID:{pid}) exited.")
            except Exception as e: self.log_to_widget(f"Error stopping Xray PID {pid}: {e}", is_error=True)
            finally: CURRENT_XRAY_PID_FILE.unlink(missing_ok=True); return True
        return False
    
    async def action_stop_xray_action(self) -> None:
        if self.stop_xray(): await self.show_message_modal("Attempted to stop main Xray.")
        else: await self.show_message_modal("Main Xray not running or PID missing.")

    async def action_add_subscription_action(self) -> None:
        if self.is_testing_servers: await self.show_message_modal("Server testing in progress. Please wait."); return
        new_url = await self.push_screen(AddSubScreen())
        if new_url:
            if any(s.get('url') == new_url for s in self.subscriptions):
                msg = f"URL '{new_url[:30]}...' exists."; self.log_to_widget(msg); await self.show_message_modal(msg); return
            name_idx = len(self.subscriptions) + 1
            while f"Sub_{name_idx}" in {s.get("name") for s in self.subscriptions}: name_idx +=1
            new_entry = {"name": f"Sub_{name_idx}", "url": new_url, "last_update": "Never"}
            self.subscriptions = self.subscriptions + [new_entry]
            save_subscriptions(self.subscriptions)
            self.log_to_widget(f"Added: {new_entry['name']} - {new_url[:40]}...")
            self.call_later(self.action_update_and_test_subs_action) # Update and test new sub
        else: self.log_to_widget("Add subscription cancelled.")

    async def action_update_and_test_subs_action(self) -> None:
        if self.is_testing_servers: await self.show_message_modal("Another test is already in progress."); return
        if not self.subscriptions: await self.show_message_modal("No subs to update. Add with 'a'."); return
        
        self.is_testing_servers = True
        self.active_servers = [] # Clear previous active servers
        self.query_one("#active_server_count", Static).update("Testing servers...") # Update UI
        self.log_to_widget("Updating subscriptions and testing servers...")
        
        all_raw = []; updated_subs = list(self.subscriptions)
        fetch_tasks = [self.fetch_single_subscription(s, i) for i, s in enumerate(updated_subs)]
        results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
        
        for i, res in enumerate(results):
            if isinstance(res, tuple): # Success from fetch_single_subscription
                idx, links = res; all_raw.extend(links)
                updated_subs[idx]["last_update"] = time.strftime('%y-%m-%d %H:%M', time.localtime())
            else: self.log_to_widget(f"Error fetching sub {updated_subs[i]['name']}: {res}", is_error=True)
        
        self.subscriptions = updated_subs; save_subscriptions(self.subscriptions)
        self.log_to_widget(f"Total raw links: {len(all_raw)}")
        
        parsed_list = []; unique_links = set()
        for link in all_raw:
            if link not in unique_links:
                if p_conf := parse_vmess_link(link): parsed_list.append(p_conf)
                unique_links.add(link)
        self.parsed_server_configs = parsed_list # Store all parsed, for reference or re-test
        self.log_to_widget(f"Parsed {len(self.parsed_server_configs)} unique configs. Starting tests...")

        if not self.parsed_server_configs:
            self.query_one("#active_server_count", Static).update("[b red]No servers to test.[/b red]")
            self.is_testing_servers = False; return

        # Test servers
        test_results = []
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_TESTS)
        test_tasks = [self.perform_connectivity_test_with_semaphore(conf, idx, semaphore) for idx, conf in enumerate(self.parsed_server_configs)]
        
        # Show progress if possible (more advanced UI)
        # For now, just log start and end of testing all servers
        
        collected_results = await asyncio.gather(*test_tasks, return_exceptions=True)
        
        active_ones = []
        for res in collected_results:
            if isinstance(res, dict) and res.get("alive"):
                active_ones.append(res)
            elif isinstance(res, Exception):
                 self.log_to_widget(f"Error during server test: {res}", is_error=True)
            # Optionally log failed tests if res is dict and not alive, or just be silent for failures
            # elif isinstance(res, dict) and not res.get("alive"):
            #    self.log_to_widget(f"Test failed: {res.get('ps', 'Unknown')} - {res.get('message', '')}")


        active_ones.sort(key=lambda x: x.get("latency_ms", float('inf')))
        self.active_servers = active_ones # This will trigger watch_active_servers
        self.log_to_widget(f"Finished testing. Found {len(self.active_servers)} active servers.")
        self.is_testing_servers = False


    async def fetch_single_subscription(self, sub_entry: dict, index: int) -> tuple[int, list] | Exception:
        url, name = sub_entry.get("url"), sub_entry.get("name", f"Sub {index+1}")
        self.log_to_widget(f"Fetching: {name} ({url[:40]}...).")
        try:
            process = await asyncio.create_subprocess_shell(f"curl -L -s --connect-timeout {CURL_CONNECT_TIMEOUT} --max-time {CURL_TOTAL_TIMEOUT*2} '{url}'", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, stderr = await process.communicate()
            if process.returncode == 0 and stdout:
                links = decode_base64_content(stdout.decode(errors="ignore"))
                self.log_to_widget(f"Decoded {len(links)} links from {name}.")
                return index, links
            else:
                err = stderr.decode(errors="ignore")[:100].strip()
                return ConnectionError(f"Fetch {name} (RC:{process.returncode}): {err or 'No stderr'}")
        except Exception as e: return e


    async def perform_connectivity_test_with_semaphore(self, server_config: dict, test_idx: int, semaphore: asyncio.Semaphore) -> dict:
        """Wrapper for check_single_server_connectivity to use with a semaphore."""
        async with semaphore:
            # self.log_to_widget(f"Semaphore acquired, testing {server_config.get('ps', 'Unknown')}")
            test_socks_port = TEST_SOCKS_PORT_BASE + test_idx % MAX_CONCURRENT_TESTS # Basic port rotation
            is_alive, latency, message = await self.check_single_server_connectivity(server_config, test_socks_port)
            # self.log_to_widget(f"Test done for {server_config.get('ps', 'Unknown')}: {message}")
            return {"config": server_config, "alive": is_alive, "latency_ms": latency, "message": message, "ps": server_config.get("ps")}


    async def check_single_server_connectivity(self, server_config: dict, test_socks_port: int) -> tuple[bool, float | None, str]:
        """Tests a single server, returns (is_alive, latency_ms, message). Uses a specific test port."""
        server_name = server_config.get('ps', 'Unknown')
        temp_config_file = TEST_XRAY_CONFIG_FILE_BASE.with_name(f"{TEST_XRAY_CONFIG_FILE_BASE.name}{test_socks_port}.json")
        
        xray_json = generate_xray_config(server_config, local_socks_port=test_socks_port, local_http_port=test_socks_port + 1)
        if not xray_json: return False, None, f"Generate XrayTestCfg Fail: {server_name}"

        with open(temp_config_file, "w") as f: json.dump(xray_json, f, indent=2)
        
        process = None
        try:
            process = await asyncio.create_subprocess_exec(str(XRAY_PATH), "run", "-c", str(temp_config_file), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await asyncio.sleep(1.5) # Time for Xray to start

            if process.returncode is not None: # Xray failed to start
                return False, None, f"XrayTestStart Fail: {server_name}"

            curl_cmd = f"curl -w '%{{time_total}}' -o /dev/null -s --connect-timeout {CURL_CONNECT_TIMEOUT} --max-time {CURL_TOTAL_TIMEOUT} --proxy socks5h://127.0.0.1:{test_socks_port} {TEST_TARGET_URL}"
            curl_proc = await asyncio.create_subprocess_shell(curl_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            curl_stdout, curl_stderr = await curl_proc.communicate()
            
            latency_ms = None
            is_alive = False
            if curl_proc.returncode == 0 and curl_stdout:
                try:
                    time_total_str = curl_stdout.decode().strip()
                    latency_ms = float(time_total_str) * 1000  # Convert to ms
                    is_alive = True
                except ValueError: # Failed to parse time
                    pass # is_alive remains False

            message = f"{int(latency_ms)}ms" if is_alive else f"Fail (CurlRC:{curl_proc.returncode})"
            return is_alive, latency_ms, message
        except Exception as e:
            return False, None, f"Exception Test: {server_name} - {str(e)[:50]}"
        finally:
            if process and process.returncode is None:
                try: process.terminate(); await asyncio.wait_for(process.wait(), timeout=1.0)
                except: try: process.kill(); await process.wait() # Force kill
                        except: pass # Already gone or unkillable
            if temp_config_file.exists(): temp_config_file.unlink(missing_ok=True)

    # --- UI Composition and Watchers ---
    def compose(self) -> ComposeResult:
        yield Header();
        with Vertical(id="main_layout"):
            with Horizontal(id="status_bar"):
                 yield Static("Xray status...", id="xray_path_status", classes="status_item")
                 yield Static("", id="active_server_count", classes="status_item status_count") # For active server count
                 yield Static(self.active_log_message, id="active_log_display", classes="status_item status_log")
            yield Label("Subscriptions:", classes="section_header")
            yield VerticalScroll(id="subscriptions_list_container", classes="list_container_subs")
            yield Label("Active Servers (Sorted by Ping):", classes="section_header")
            yield VerticalScroll(id="server_list_display_container", classes="list_container_servers")
            yield Label("Log:", classes="section_header")
            yield Log(id="main_log", auto_scroll=True, max_lines=250, markup=True) # Enable markup for log
        yield Footer()
        self.call_later(self.update_subscription_list_ui) # Initial UI population
        self.call_later(self.update_active_server_list_ui)

    async def watch_subscriptions(self, _: list, new_subs: list) -> None: self.update_subscription_list_ui()
    def update_subscription_list_ui(self):
        container = self.query_one("#subscriptions_list_container", VerticalScroll)
        container.remove_children()
        if not self.subscriptions: container.mount(Static("No subscriptions. Press 'a' to add.", classes="placeholder_text"))
        else:
            for idx, sub in enumerate(self.subscriptions):
                name, url, ts = sub.get("name",f"S_{idx+1}"), sub.get("url","N/A"), sub.get("last_update","Never")
                url_short = url[:35] + "..." if len(url) > 38 else url
                update_str = ts # Already formatted string or "Never"
                container.mount(Markdown(f"**{name}**: `{url_short}` (Upd: {update_str})", classes="sub_entry"))
    
    async def watch_active_servers(self, _: list, new_active_servers: list) -> None:
        self.update_active_server_list_ui()
        # Update active server count display
        count_str = f"[b bright_green]Active: {len(new_active_servers)}[/b bright_green]" if not self.is_testing_servers else "Testing..."
        if not new_active_servers and not self.is_testing_servers: count_str = "[b red]No active servers.[/b red]"
        self.query_one("#active_server_count", Static).update(count_str)


    def update_active_server_list_ui(self):
        container = self.query_one("#server_list_display_container", VerticalScroll)
        container.remove_children()
        if self.is_testing_servers and not self.active_servers: # Show testing status if still testing and list is empty
            container.mount(Static("Testing servers, please wait...", classes="placeholder_text"))
            return
        if not self.active_servers:
            container.mount(Static("No active servers found. Update/check subs ('u').", classes="placeholder_text"))
        else:
            for idx, server_info in enumerate(self.active_servers):
                conf = server_info["config"]
                ps, addr = conf.get("ps", f"S_{idx+1}"), conf.get("add", "N/A")
                net, tls = conf.get("net", "N/A"), "TLS" if conf.get("tls")=="tls" else "NoTLS"
                latency = server_info.get("latency_ms")
                latency_str = f"{int(latency)}ms" if latency is not None else "N/A"
                # Example: [  1] ( 123ms) My Server (1.2.3.4 | ws/TLS)
                display_text = f"[{idx+1:3}] ({latency_str:>6}) **{ps}** (`{addr}` | {net}/{tls})"
                container.mount(Markdown(display_text, classes="server_entry"))
            
            if self.active_servers: # Add buttons for the first active server
                first_active_conf = self.active_servers[0]["config"]
                first_name = first_active_conf.get("ps", "First Active Server")
                connect_btn = Button(f"Connect: {first_name}", variant="success", id="connect_first_active_server_button")
                # Test button for an active server is less critical, but can be re-test
                # test_btn = Button(f"Re-Test: {first_name}", id="retest_first_active_server_button")
                btn_container = Horizontal(connect_btn, classes="action_buttons_container")
                container.mount(btn_container)
    
    async def watch_active_log_message(self, _: str, new_log_msg: str) -> None:
        try: self.query_one("#active_log_display", Static).update(new_log_msg[:70]) # Truncate
        except Exception: pass 

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "connect_first_active_server_button": # Changed ID
            if self.is_testing_servers: await self.show_message_modal("Server testing in progress. Cannot connect."); return
            if self.active_servers:
                server_to_connect = self.active_servers[0]["config"]
                self.log_to_widget(f"Connect button pressed for: {server_to_connect.get('ps')}")
                if self.start_xray(server_to_connect): await self.show_message_modal(f"Xray started with: '{server_to_connect.get('ps')}'")
                else: await self.show_message_modal("Failed to start Xray with selected server.")
            else: await self.show_message_modal("No active servers to connect.")
        # Add re-test logic if retest_first_active_server_button is implemented
        # elif button_id == "retest_first_active_server_button":
        #     if self.active_servers:
        #         self.call_later(self.run_server_test_action, self.active_servers[0]["config"]) # Example

    async def action_quit_app(self) -> None:
        self.log_to_widget("Quit requested. Stopping Xray..."); self.stop_xray()
        self.log_to_widget("Exiting application."); self.exit("User requested quit.")

# --- Fallback CSS ---
VPN_APP_CSS_FALLBACK = """
Screen { background: $surface; color: $text; layout: vertical; overflow-y: auto; }
Header { dock: top; background: $primary; color: $text; height: 1; text-style: bold; }
Footer { dock: bottom; background: $primary-darken-2; color: $text-muted; height: 1; }
#main_layout { padding: 0 1; height: 1fr; }
#status_bar { height: 1; background: $surface-darken-1; padding: 0 1; dock: top; grid-size: 3; grid-columns: 1fr 1fr 2fr; }
#xray_path_status { width: 100%; content-align: left middle; color: $text-muted; overflow: hidden; }
#active_server_count { width: 100%; content-align: center middle; text-style: bold; }
#active_log_display { width: 100%; content-align: right middle; color: $text-muted; overflow: hidden; }
.section_header { padding: 1 0 0 0; text-style: bold underline; color: $secondary; }
.list_container_subs { border: round $primary-background-darken-2; padding: 0 1; height: auto; max-height: 6; overflow-y: auto; margin-bottom: 1; }
.list_container_servers { border: round $primary-background-darken-2; padding: 0 1; height: 1fr; /* Takes more space */ overflow-y: auto; margin-bottom: 1; }
.sub_entry { padding: 1 0; background: $boost; border-bottom: thin dashed $primary-background-darken-3;}
.server_entry { padding: 0 0; margin-bottom: 1; /*font-size: 90%;*/ /* Smaller text */ } 
.server_entry Markdown { /* font-size: 90%; */ } /* Target markdown directly for font size if needed */
.action_buttons_container { padding-top:1; align: center middle; height: auto; }
.action_buttons_container Button { margin: 0 1; width: 1fr; }
#main_log { border: panel $primary-background-darken-2; height: 8; margin-top: 1; }
.placeholder_text { color: $text-muted; padding: 1; text-align: center; }
#add_sub_dialog, #message_dialog, #about_dialog { padding: 0 1; width: 80%; max-width: 60; height: auto; border: thick $secondary; background: $panel; }
.modal_label { padding: 1 0; }
.modal_buttons { padding-top: 1; align-horizontal: right; }
.modal_buttons Button { margin-left: 1; }
.about_content Markdown { padding: 1 2; }
"""

if __name__ == "__main__":
    css_file = SCRIPT_DIR / VpnApp.CSS_PATH
    if not css_file.exists():
        with open(css_file, "w") as f: f.write(VPN_APP_CSS_FALLBACK)
        print(f"Created CSS file: {css_file} with fallback styles.")
    app = VpnApp()
    app.run()

