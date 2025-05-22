import json
import base64
import subprocess
import os
import time
from pathlib import Path
import asyncio # Make sure to import asyncio

# --- Textual App Imports ---
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Button, Static, Log, Input, Label, Markdown
from textual.containers import VerticalScroll, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen

# --- Configuration ---
# Get the directory where vpn.py script itself is located
SCRIPT_DIR = Path(__file__).resolve().parent
XRAY_PATH = SCRIPT_DIR / "xray"  # Expect 'xray' executable in the same directory as vpn.py

CONFIG_STORAGE_DIR = Path.home() / ".v2ray_termux_client" # For storing subscriptions.json etc.
SUBS_FILE = CONFIG_STORAGE_DIR / "subscriptions.json"
LAST_SELECTED_CONFIG_FILE = CONFIG_STORAGE_DIR / "last_selected_xray_config.json"
TEST_XRAY_CONFIG_FILE = CONFIG_STORAGE_DIR / "test_xray_config.json" # For server alive test
CURRENT_XRAY_PID_FILE = CONFIG_STORAGE_DIR / "xray.pid"

# Ensure config storage directory exists
CONFIG_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

# --- Developer Information (Global for easy access in AboutScreen) ---
APP_TITLE = "Termux V2Ray/Xray Client"
APP_SUB_TITLE = "Manage Connections"
APP_VERSION = "0.2.0" # Example version
DEVELOPER_NAME_CONST = "Developer Victor Geek"
DEVELOPER_EMAIL_CONST = "frussel4@asu.edu"


# --- Helper Functions (Simplified for this single file) ---

def load_subscriptions():
    """Loads subscription URLs from the JSON file."""
    if SUBS_FILE.exists():
        try:
            with open(SUBS_FILE, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return []
    return []

def save_subscriptions(subs):
    """Saves subscription URLs to the JSON file."""
    with open(SUBS_FILE, "w") as f:
        json.dump(subs, f, indent=2)

def decode_base64_content(content: str) -> list:
    """Decodes base64 content. Assumes one link per line after decoding."""
    try:
        decoded_bytes = base64.b64decode(content)
        decoded_str = decoded_bytes.decode("utf-8")
        return decoded_str.strip().splitlines()
    except Exception:
        return []

def parse_vmess_link(vmess_link: str) -> dict | None:
    """
    Simplified VMess link parser.
    """
    if not vmess_link.startswith("vmess://"):
        return None
    try:
        base64_config = vmess_link[8:]
        padding = '=' * (4 - len(base64_config) % 4)
        base64_config += padding
        decoded_json = base64.b64decode(base64_config).decode("utf-8")
        config = json.loads(decoded_json)
        # Ensure essential fields have default values if missing, for robust parsing
        config['add'] = config.get('add', '')
        config['port'] = int(config.get('port', 443))
        config['id'] = config.get('id', '')
        config['aid'] = int(config.get('aid', 0))
        config['net'] = config.get('net', 'tcp')
        config['type'] = config.get('type', 'none') # For header type in http
        config['host'] = config.get('host', '')
        config['path'] = config.get('path', '/')
        config['tls'] = config.get('tls', 'none')
        config['sni'] = config.get('sni', config.get('host', config.get('add'))) # SNI default
        config['ps'] = config.get('ps', f"{config['add']}:{config['port']}") # Default PS
        config['_raw_link'] = vmess_link # Store original link for reference
        return config
    except Exception:
        return None


def generate_xray_config(server_config: dict) -> dict | None:
    """
    Generates a full Xray client configuration for a given parsed server_config.
    """
    if not server_config:
        return None
    try:
        xray_outbound = {
            "protocol": "vmess",
            "settings": {
                "vnext": [{
                    "address": server_config.get("add"),
                    "port": server_config.get("port"),
                    "users": [{
                        "id": server_config.get("id"),
                        "alterId": server_config.get("aid"),
                        "security": server_config.get("scy", "auto") # scy for security cipher
                    }]
                }]
            },
            "streamSettings": {
                "network": server_config.get("net"),
                "security": server_config.get("tls"),
            }
        }
        
        net_type = server_config.get("net")
        if net_type == "ws":
            xray_outbound["streamSettings"]["wsSettings"] = {
                "path": server_config.get("path"),
                "headers": {"Host": server_config.get("host", server_config.get("add"))}
            }
        elif net_type == "grpc":
             xray_outbound["streamSettings"]["grpcSettings"] = {
                "serviceName": server_config.get("path") # gRPC path is serviceName
            }
        # Add more stream settings for other net_types (tcp, kcp, httpupgrade etc.)

        if server_config.get("tls") == "tls":
             xray_outbound["streamSettings"]["tlsSettings"] = {
                "serverName": server_config.get("sni", server_config.get("host", server_config.get("add"))),
                "allowInsecure": server_config.get("allowInsecure", False), # Common field
            }
             # For reality certs if present in vmess (less common in basic links)
             # fp = server_config.get("fp")
             # if fp: xray_outbound["streamSettings"]["tlsSettings"]["fingerprint"] = fp


        client_config = {
            "log": {"loglevel": "warning"},
            "inbounds": [
                {"port": 10808, "listen": "127.0.0.1", "protocol": "socks", "settings": {"auth": "noauth", "udp": True, "ip": "127.0.0.1"}},
                {"port": 10809, "listen": "127.0.0.1", "protocol": "http", "settings": {}}
            ],
            "outbounds": [xray_outbound, {"protocol": "freedom", "tag": "direct"}]
            # Basic routing: block QUIC, route private IPs direct (example)
            # "routing": {
            #     "rules": [
            #         {"type": "field", "ip": ["geoip:private"], "outboundTag": "direct"},
            #         {"type": "field", "protocol": ["bittorrent"], "outboundTag": "direct"}, # or block
            #     ]
            # }
        }
        return client_config
    except Exception:
        return None

# --- Textual Screens ---

class AddSubScreen(ModalScreen):
    BINDINGS = [("escape", "pop_screen", "Back")]
    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Enter Subscription URL:", classes="modal_label"),
            Input(placeholder="https://example.com/sub", id="sub_url_input"),
            Horizontal(
                Button("Add", variant="primary", id="add_sub_button"),
                Button("Cancel", id="cancel_add_sub_button"), classes="modal_buttons"
            ), id="add_sub_dialog"
        )
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add_sub_button":
            self.dismiss(self.query_one(Input).value.strip() or None)
        else: self.dismiss(None)

class MessageScreen(ModalScreen):
    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message
    def compose(self) -> ComposeResult:
        yield Vertical(Markdown(self.message), Button("OK", variant="primary", id="ok_button"), id="message_dialog")
    def on_button_pressed(self, event: Button.Pressed) -> None: self.dismiss()

# --- NEW: About Screen ---
class AboutScreen(ModalScreen):
    BINDINGS = [("escape", "pop_screen", "Back")]
    def compose(self) -> ComposeResult:
        about_md = f"""\
# {APP_TITLE}

Version: {APP_VERSION}

{APP_SUB_TITLE}

---
Developed by:
**{DEVELOPER_NAME_CONST}**
({DEVELOPER_EMAIL_CONST})

Powered by Textual and Xray.
"""
        yield Vertical(
            Markdown(about_md, classes="about_content"),
            Button("OK", variant="primary", id="ok_about_button"),
            id="about_dialog" # Use same ID for styling if consistent
        )
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok_about_button":
            self.dismiss()


class VpnApp(App):
    CSS_PATH = "vpn_style.tcss" # Defined globally now
    TITLE = APP_TITLE
    SUB_TITLE = APP_SUB_TITLE
    # --- ADDED: Developer info constants for potential direct use in app logic ---
    DEVELOPER_NAME = DEVELOPER_NAME_CONST
    DEVELOPER_EMAIL = DEVELOPER_EMAIL_CONST


    BINDINGS = [
        ("q", "quit_app", "Quit"), ("a", "add_subscription_action", "Add Sub"),
        ("u", "update_subscriptions_action", "Update Subs"),
        ("s", "stop_xray_action", "Stop Xray"),
        ("c", "check_xray_path_action", "Check Xray"),
        ("f1", "show_about_screen", "About"), # ADDED: F1 for About
    ]

    subscriptions = reactive(load_subscriptions())
    raw_configs_from_subs = reactive([])
    parsed_server_configs = reactive([])
    active_log_message = reactive("App Started. Welcome!") # For status bar

    def on_mount(self) -> None:
        self.log_to_widget("App mounted. Welcome!")
        self.call_later(self.check_xray_path, silent=True)

    def log_to_widget(self, message: str):
        try: # During shutdown, widget might be gone
            log_widget = self.query_one("#main_log", Log)
            current_time = time.strftime("%H:%M:%S")
            log_widget.write_line(f"[{current_time}] {message}")
        except Exception: pass # Ignore if log widget not found
        self.active_log_message = message 

    async def show_message_modal(self, message: str):
        # This check prevents pushing screen during shutdown or if app not fully ready
        if self.is_running and self.app_is_mounted:
            await self.push_screen(MessageScreen(message))


    def check_xray_path(self, silent: bool = False) -> bool:
        path_status_widget = self.query_one("#xray_path_status", Static)
        if not XRAY_PATH.exists() or not os.access(XRAY_PATH, os.X_OK):
            msg = f"Xray NOT found/executable: {XRAY_PATH}"
            tip = ("\nPlease download Xray core (e.g., appropriate for your Termux) "
                   f"and place it as 'xray' in '{SCRIPT_DIR}'. Then `chmod +x xray`.")
            self.log_to_widget(msg + tip)
            path_status_widget.update(f"[b red]{msg}[/b red]")
            if not silent: self.call_later(self.show_message_modal, msg + tip)
            return False
        
        status_msg = f"Xray OK: {XRAY_PATH}"
        # self.log_to_widget(status_msg) # Can be noisy on startup if silent
        path_status_widget.update(f"[b green]{status_msg}[/b green]")
        return True
    
    async def action_check_xray_path_action(self) -> None: self.check_xray_path()

    # --- ADDED: About screen action ---
    async def action_show_about_screen(self) -> None:
        await self.push_screen(AboutScreen())

    def start_xray(self, config_dict: dict) -> bool:
        if not self.check_xray_path(silent=True): return False # Ensure Xray is ready
        self.stop_xray() # Stop any existing instance before starting a new one
        
        try:
            with open(LAST_SELECTED_CONFIG_FILE, "w") as f: json.dump(config_dict, f, indent=2)
            self.log_to_widget(f"Starting Xray with: {LAST_SELECTED_CONFIG_FILE.name}")
            
            process = subprocess.Popen(
                [str(XRAY_PATH), "run", "-c", str(LAST_SELECTED_CONFIG_FILE)],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE # Capture stderr
            )
            time.sleep(1.2) # Allow Xray to start/fail

            if process.poll() is None: # Xray is running
                with open(CURRENT_XRAY_PID_FILE, "w") as pf: pf.write(str(process.pid))
                self.log_to_widget(f"Xray started. PID: {process.pid}. SOCKS: 127.0.0.1:10808, HTTP: 127.0.0.1:10809")
                return True
            else: # Xray failed to start
                stderr_output = process.stderr.read().decode(errors="ignore") if process.stderr else "No stderr"
                self.log_to_widget(f"Failed to start Xray. RC: {process.returncode}. Error: {stderr_output[:200]}")
                if LAST_SELECTED_CONFIG_FILE.exists(): LAST_SELECTED_CONFIG_FILE.unlink(missing_ok=True)
                return False
        except Exception as e:
            self.log_to_widget(f"Exception starting Xray: {e}")
            if LAST_SELECTED_CONFIG_FILE.exists(): LAST_SELECTED_CONFIG_FILE.unlink(missing_ok=True)
            return False

    def stop_xray(self) -> bool:
        pid_to_stop = None
        if CURRENT_XRAY_PID_FILE.exists():
            try:
                with open(CURRENT_XRAY_PID_FILE, "r") as pf: pid_to_stop = int(pf.read().strip())
            except ValueError:
                self.log_to_widget(f"Invalid PID in {CURRENT_XRAY_PID_FILE}.")
                CURRENT_XRAY_PID_FILE.unlink(missing_ok=True)
                return False
        
        if pid_to_stop:
            try:
                os.kill(pid_to_stop, subprocess.signal.SIGTERM) # Graceful termination
                time.sleep(0.5) 
                try: 
                    os.kill(pid_to_stop, 0) # Check if process exists
                    time.sleep(0.5) # Give more time then force
                    os.kill(pid_to_stop, subprocess.signal.SIGKILL)
                    self.log_to_widget(f"Force stopped Xray process {pid_to_stop}.")
                except OSError: 
                    self.log_to_widget(f"Xray process {pid_to_stop} exited.")
            except Exception as e: self.log_to_widget(f"Error stopping Xray PID {pid_to_stop}: {e}")
            finally: 
                CURRENT_XRAY_PID_FILE.unlink(missing_ok=True)
                return True
        # self.log_to_widget("No active Xray PID file found to stop.") # Can be noisy
        return False
    
    async def action_stop_xray_action(self) -> None:
        if self.stop_xray(): await self.show_message_modal("Attempted to stop Xray.")
        else: await self.show_message_modal("Xray not running or PID file missing.")

    async def action_add_subscription_action(self) -> None:
        def after_add_sub_screen_callback(new_url: str | None):
            if new_url:
                if any(sub.get('url') == new_url for sub in self.subscriptions):
                    msg = f"Subscription URL '{new_url[:30]}...' already exists."
                    self.log_to_widget(msg)
                    self.call_later(self.show_message_modal, msg)
                    return
                # Generate a unique name if possible, or just increment
                sub_names = {s.get("name") for s in self.subscriptions}
                idx = 1
                new_name = f"Sub_{idx}"
                while new_name in sub_names:
                    idx += 1
                    new_name = f"Sub_{idx}"

                new_entry = {"name": new_name, "url": new_url, "last_update": None}
                self.subscriptions = self.subscriptions + [new_entry] 
                save_subscriptions(self.subscriptions)
                self.log_to_widget(f"Added subscription: {new_name} - {new_url[:40]}...")
            else: self.log_to_widget("Add subscription cancelled.")
        await self.push_screen(AddSubScreen(), after_add_sub_screen_callback)

    async def action_update_subscriptions_action(self) -> None:
        if not self.subscriptions:
            await self.show_message_modal("No subscriptions to update. Add one with 'a'.")
            return
        self.log_to_widget("Updating subscriptions...")
        all_raw_links = [] # Renamed for clarity
        updated_subs_list = list(self.subscriptions) 
        
        # Create a list of tasks to run concurrently
        fetch_tasks = []
        for i, sub_entry in enumerate(updated_subs_list):
            fetch_tasks.append(self.fetch_single_subscription(sub_entry, i))
        
        results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.log_to_widget(f"Exception during gathering fetch result for sub {i}: {result}")
            elif result: # Result is (index, decoded_links_list)
                idx, links = result
                all_raw_links.extend(links)
                updated_subs_list[idx]["last_update"] = time.time() # Update timestamp
        
        self.subscriptions = updated_subs_list 
        save_subscriptions(self.subscriptions) 
        self.raw_configs_from_subs = all_raw_links
        self.log_to_widget(f"Total raw configs from all subs: {len(self.raw_configs_from_subs)}")
        self.process_raw_configs()

    async def fetch_single_subscription(self, sub_entry: dict, index: int) -> tuple[int, list] | None:
        """ Helper to fetch and decode a single subscription. Used by asyncio.gather. """
        url = sub_entry.get("url")
        name = sub_entry.get("name", f"Sub {index+1}")
        self.log_to_widget(f"Fetching: {name} ({url[:40]}...).")
        decoded_links = []
        try:
            process = await asyncio.create_subprocess_shell(
                f"curl -L -s --connect-timeout 10 --max-time 20 '{url}'", # -s for silent
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate() # Wait for process to finish
            if process.returncode == 0 and stdout:
                decoded_links = decode_base64_content(stdout.decode(errors="ignore"))
                self.log_to_widget(f"Decoded {len(decoded_links)} links from {name}")
            else:
                err_msg = stderr.decode(errors="ignore")[:100].strip()
                self.log_to_widget(f"Error fetching {name} (RC:{process.returncode}): {err_msg if err_msg else 'No stderr'}")
        except Exception as e:
            self.log_to_widget(f"Exception fetching {name}: {e}")
        return index, decoded_links


    def process_raw_configs(self):
        parsed_list = []
        unique_raw_links = set() # To avoid parsing identical raw links if they appear multiple times
        for raw_link in self.raw_configs_from_subs:
            if raw_link not in unique_raw_links:
                parsed_config = parse_vmess_link(raw_link)
                if parsed_config:
                    parsed_list.append(parsed_config)
                unique_raw_links.add(raw_link)
        
        self.parsed_server_configs = parsed_list
        self.log_to_widget(f"Parsed {len(self.parsed_server_configs)} unique VMess configs.")
        # TODO: Add sorting by name or other criteria if needed.
        # self.parsed_server_configs.sort(key=lambda x: x.get('ps', 'zzzz'))


    # --- NEW: Server Alive Check Functionality ---
    async def check_server_alive(self, server_config_to_test: dict) -> tuple[bool, str]:
        """Tests connectivity through a given server config. Returns (is_alive, message)."""
        server_name = server_config_to_test.get('ps', server_config_to_test.get('add', 'Unknown Server'))
        self.log_to_widget(f"Testing connectivity for: {server_name}...")

        xray_json_config = generate_xray_config(server_config_to_test)
        if not xray_json_config:
            return False, f"Failed to generate Xray config for {server_name}."

        # Ensure Xray executable is okay (silent check)
        if not self.check_xray_path(silent=True):
            return False, "Xray executable not found/ready for test."
        
        # Stop any currently running main Xray instance to free up ports
        # This is a simplification; a more advanced version might use different ports for testing.
        self.stop_xray()
        
        # Use a temporary config file for this specific test
        with open(TEST_XRAY_CONFIG_FILE, "w") as f: json.dump(xray_json_config, f, indent=2)

        xray_test_process = None
        try:
            xray_test_process = await asyncio.create_subprocess_exec(
                str(XRAY_PATH), "run", "-c", str(TEST_XRAY_CONFIG_FILE),
                stdout=asyncio.subprocess.DEVNULL, # Suppress verbose output
                stderr=asyncio.subprocess.PIPE
            )
            await asyncio.sleep(2.0) # Give Xray time to start or fail

            if xray_test_process.returncode is not None: # Xray process already exited
                stderr_output = await xray_test_process.stderr.read()
                err_msg = stderr_output.decode(errors='ignore').strip()[:150]
                return False, f"Xray failed to start for {server_name} test. Error: {err_msg}"

            # Xray seems to be running, attempt curl test
            TEST_URL = "http://www.gstatic.com/generate_204" # Google's No Content page
            PROXY_ADDRESS = "127.0.0.1:10808" # As defined in generate_xray_config
            curl_command = f"curl -s --head --connect-timeout 7 --max-time 12 --proxy socks5h://{PROXY_ADDRESS} {TEST_URL}"
            
            curl_proc = await asyncio.create_subprocess_shell(
                curl_command,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            curl_stdout, curl_stderr = await curl_proc.communicate()

            is_success = False
            if curl_proc.returncode == 0:
                headers_output = curl_stdout.decode(errors='ignore')
                if "HTTP/1.1 204" in headers_output or "HTTP/2 204" in headers_output or "HTTP/1.0 204" in headers_output:
                    is_success = True
            
            # Ensure Xray test process is terminated
            if xray_test_process.returncode is None:
                try:
                    xray_test_process.terminate()
                    await asyncio.wait_for(xray_test_process.wait(), timeout=2.0)
                except (ProcessLookupError, asyncio.TimeoutError): pass # Already gone or stuck

            if TEST_XRAY_CONFIG_FILE.exists(): TEST_XRAY_CONFIG_FILE.unlink(missing_ok=True)

            if is_success:
                return True, f"SUCCESS: {server_name} is alive."
            else:
                curl_err_msg = curl_stderr.decode(errors='ignore').strip()[:100]
                return False, f"FAIL: {server_name} test failed. Curl_RC:{curl_proc.returncode}. CurlErr:{curl_err_msg}"

        except Exception as e:
            self.log_to_widget(f"Exception during server test for {server_name}: {e}")
            # Clean up if process started
            if xray_test_process and xray_test_process.returncode is None:
                try: 
                    xray_test_process.terminate()
                    await xray_test_process.wait()
                except ProcessLookupError: pass
            if TEST_XRAY_CONFIG_FILE.exists(): TEST_XRAY_CONFIG_FILE.unlink(missing_ok=True)
            return False, f"Exception testing {server_name}: {e}"

    async def run_server_test_action(self, server_config_to_test: dict):
        """Wrapper to run the test and show results."""
        if not server_config_to_test:
            await self.show_message_modal("No server config provided for testing.")
            return
        
        # Disable other interactions while testing or show a spinner (advanced)
        self.log_to_widget(f"Initiating test for {server_config_to_test.get('ps', 'Unknown Server')}...")
        is_alive, message = await self.check_server_alive(server_config_to_test)
        self.log_to_widget(message) # Log to main log widget
        await self.show_message_modal(message) # Show result in modal

    # --- UI Update Methods ---
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="main_layout"):
            with Horizontal(id="status_bar"):
                 yield Static(f"Xray status checking...", id="xray_path_status")
                 yield Static(self.active_log_message, id="active_log_display")
            yield Label("Subscriptions:", classes="section_header")
            yield VerticalScroll(id="subscriptions_list_container", classes="list_container")
            yield Label("Available Servers (VMess Only - Parsed):", classes="section_header")
            yield VerticalScroll(id="server_list_display_container", classes="list_container")
            yield Label("Log:", classes="section_header")
            yield Log(id="main_log", auto_scroll=True, max_lines=200) # Increased max_lines
        yield Footer()
        self.call_later(self.update_subscription_list_ui)
        self.call_later(self.update_server_list_ui)

    async def watch_subscriptions(self, _: list, new_subs: list) -> None:
        self.update_subscription_list_ui()

    def update_subscription_list_ui(self):
        container = self.query_one("#subscriptions_list_container")
        container.remove_children()
        if not self.subscriptions:
            container.mount(Static("No subscriptions. Press 'a' to add.", classes="placeholder_text"))
        else:
            for idx, sub in enumerate(self.subscriptions):
                name = sub.get("name", f"Sub {idx+1}")
                url_short = sub.get("url", "N/A")[:40] + "..." if sub.get("url") else "N/A"
                ts = sub.get("last_update")
                update_str = time.strftime('%y-%m-%d %H:%M', time.localtime(ts)) if ts else "Never"
                container.mount(Markdown(f"**{name}**: `{url_short}` (Upd: {update_str})", classes="sub_entry"))
    
    async def watch_parsed_server_configs(self, _: list, new_configs: list) -> None:
        self.update_server_list_ui()

    def update_server_list_ui(self): # MODIFIED to add Test button
        container = self.query_one("#server_list_display_container")
        container.remove_children()
        if not self.parsed_server_configs:
            container.mount(Static("No servers parsed. Update subscriptions with 'u'.", classes="placeholder_text"))
        else:
            status_msg = f"{len(self.parsed_server_configs)} servers found."
            if len(self.parsed_server_configs) > 0:
                 status_msg += " (Actions for first server shown below)"
            container.mount(Static(status_msg))
            
            for idx, config in enumerate(self.parsed_server_configs):
                ps_name = config.get("ps", f"Server_{idx+1}")
                address = config.get("add", "N/A")
                net_type = config.get("net", "N/A")
                tls_status = "TLS" if config.get("tls", "none") == "tls" else "NoTLS"
                display_text = f"[{idx+1}] **{ps_name}** (`{address}` | {net_type}/{tls_status})"
                # For simplicity, actions are for the first server. 
                # To make each interactive, you'd create buttons/widgets per server.
                container.mount(Markdown(display_text, classes="server_entry")) 

            if self.parsed_server_configs:
                first_server_config = self.parsed_server_configs[0]
                first_server_name = first_server_config.get("ps", "First Server")
                
                button_container = Horizontal(classes="action_buttons_container")
                connect_button = Button(f"Connect: {first_server_name}", variant="success", id="connect_first_parsed_server_button")
                test_button = Button(f"Test Alive: {first_server_name}", variant="default", id="test_first_parsed_server_button") # NEW Test Button
                
                button_container.mount(connect_button)
                button_container.mount(test_button)
                container.mount(button_container)
    
    async def watch_active_log_message(self, _: str, new_log_msg: str) -> None:
        try:
            status_bar_log = self.query_one("#active_log_display", Static)
            status_bar_log.update(new_log_msg[:80]) 
        except Exception: pass 

    async def on_button_pressed(self, event: Button.Pressed) -> None: # MODIFIED for test button
        button_id = event.button.id
        if button_id == "connect_first_parsed_server_button":
            if self.parsed_server_configs:
                self.log_to_widget("Connect button pressed for first parsed server.")
                first_config = self.parsed_server_configs[0]
                xray_json = generate_xray_config(first_config)
                if xray_json:
                    if self.start_xray(xray_json):
                        await self.show_message_modal(f"Xray started with: '{first_config.get('ps', 'Unknown')}'")
                    else: await self.show_message_modal("Failed to start Xray.")
                else: await self.show_message_modal("Could not generate Xray config.")
            else: await self.show_message_modal("No parsed servers to connect.")
        
        elif button_id == "test_first_parsed_server_button": # NEW Handler for Test Button
            if self.parsed_server_configs:
                first_config_to_test = self.parsed_server_configs[0]
                # Use call_later as run_server_test_action is async and involves I/O
                self.call_later(self.run_server_test_action, first_config_to_test)
            else:
                await self.show_message_modal("No parsed servers to test.")


    async def action_quit_app(self) -> None:
        self.log_to_widget("Quit requested. Stopping Xray...")
        self.stop_xray()
        self.log_to_widget("Exiting application.")
        self.exit("User requested quit.")

# --- CSS for the App (vpn_style.tcss) ---
# (CSS is not repeated here for brevity, assume it's the same as user provided or in vpn_style.tcss file)
# The existing CSS provided by user should still work. 
# Minor additions might be needed for new elements if they don't fit well.
# For example, styling for .action_buttons_container or .about_content
# If vpn_style.tcss does not exist, the script will create it with basic styles.

VPN_APP_CSS_FALLBACK = """
Screen { background: $surface; color: $text; layout: vertical; overflow-y: auto; }
Header { dock: top; background: $primary; color: $text; height: 1; text-style: bold; }
Header Title, Header SubTitle { color: $text; }
Footer { dock: bottom; background: $primary-darken-2; color: $text-muted; height: 1; }
#main_layout { padding: 0 1; height: 1fr; }
#status_bar { height: 1; background: $primary-background-darken-1; padding: 0 1; dock: top; }
#xray_path_status { width: 1fr; content-align: left middle; color: $text-muted; }
#active_log_display { width: 3fr; content-align: right middle; color: $warning; overflow: hidden; }
.section_header { padding: 1 0 0 0; text-style: bold underline; color: $secondary; }
.list_container { border: round $primary-background-darken-2; padding: 0 1; height: auto; max-height: 10; overflow-y: auto; margin-bottom: 1; }
.sub_entry, .server_entry { padding: 1 0; background: $boost; border-bottom: dashed $primary-background-darken-3; }
.server_entry Button { width: 100%; }
#connect_first_parsed_server_button, #test_first_parsed_server_button { width: 1fr; margin: 1 0 0 1;} /* Updated */
.action_buttons_container { padding-top:1; align-horizontal: center; height: auto; } /* Added */
.action_buttons_container Button { margin: 0 1; } /* Added */
#main_log { border: panel $primary-background-darken-2; height: 8; margin-top: 1; }
.placeholder_text { color: $text-muted; padding: 1; text-align: center; }
#add_sub_dialog, #message_dialog, #about_dialog { /* Added #about_dialog */
    padding: 0 1; width: 80%; max-width: 60; height: auto;
    border: thick $secondary; background: $panel;
}
.modal_label { padding: 1 0; }
.modal_buttons { padding-top: 1; align-horizontal: right; }
.modal_buttons Button { margin-left: 1; }
.about_content { padding: 1 2; } /* Added for AboutScreen markdown */
"""


# --- Main Execution ---
if __name__ == "__main__":
    # Ensure the CSS file path is correct for the app instance
    # VpnApp.CSS_PATH is already set to "vpn_style.tcss" relative to SCRIPT_DIR
    
    # Create CSS file with fallback if it doesn't exist
    css_file_path_to_check = SCRIPT_DIR / VpnApp.CSS_PATH
    if not css_file_path_to_check.exists():
        with open(css_file_path_to_check, "w") as cf:
            cf.write(VPN_APP_CSS_FALLBACK) # Use the fallback CSS defined above
            print(f"Created CSS file: {css_file_path_to_check}")
    
    app = VpnApp()
    app.run()
