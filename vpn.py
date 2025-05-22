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
from textual.screen import ModalScreen # Screen import is not strictly needed if only ModalScreen is used

# --- Configuration ---
# Get the directory where vpn.py script itself is located
SCRIPT_DIR = Path(__file__).resolve().parent
XRAY_PATH = SCRIPT_DIR / "xray"  # Expect 'xray' executable in the same directory as vpn.py

CONFIG_STORAGE_DIR = Path.home() / ".v2ray_termux_client" # For storing subscriptions.json etc.
SUBS_FILE = CONFIG_STORAGE_DIR / "subscriptions.json"
LAST_SELECTED_CONFIG_FILE = CONFIG_STORAGE_DIR / "last_selected_xray_config.json" # Changed name
CURRENT_XRAY_PID_FILE = CONFIG_STORAGE_DIR / "xray.pid"

# Ensure config storage directory exists
CONFIG_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

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
    Simplified VMess link parser. THIS IS VERY BASIC AND NEEDS IMPROVEMENT.
    """
    if not vmess_link.startswith("vmess://"):
        return None
    try:
        base64_config = vmess_link[8:]
        padding = '=' * (4 - len(base64_config) % 4)
        base64_config += padding
        decoded_json = base64.b64decode(base64_config).decode("utf-8")
        config = json.loads(decoded_json)
        config['_raw_link'] = vmess_link # Store original link for reference
        return config
    except Exception:
        return None


def generate_xray_config(server_config: dict) -> dict | None:
    """
    Generates a full Xray client configuration for a given parsed server_config.
    THIS IS BASIC AND NEEDS EXPANSION FOR VARIOUS VMESS PARAMETERS.
    """
    if not server_config:
        return None
    try:
        xray_outbound = {
            "protocol": "vmess",
            "settings": {
                "vnext": [{
                    "address": server_config.get("add", ""),
                    "port": int(server_config.get("port", 443)),
                    "users": [{
                        "id": server_config.get("id", ""),
                        "alterId": int(server_config.get("aid", 0)),
                        "security": server_config.get("scy", "auto")
                    }]
                }]
            },
            "streamSettings": {
                "network": server_config.get("net", "tcp"),
                "security": server_config.get("tls", "none"), # 'tls' or 'none'
            }
        }
        
        net_type = server_config.get("net", "tcp")
        if net_type == "ws":
            xray_outbound["streamSettings"]["wsSettings"] = {
                "path": server_config.get("path", "/"),
                "headers": {"Host": server_config.get("host", server_config.get("add"))}
            }
        # Add more stream settings for other net_types (grpc, tcp, kcp, etc.)

        if server_config.get("tls", "none") == "tls":
             xray_outbound["streamSettings"]["tlsSettings"] = {
                "serverName": server_config.get("sni", server_config.get("host", server_config.get("add"))),
                # "allowInsecure": False, # Consider adding if needed
            }

        client_config = {
            "log": {"loglevel": "warning"},
            "inbounds": [
                {"port": 10808, "listen": "127.0.0.1", "protocol": "socks", "settings": {"auth": "noauth", "udp": True, "ip": "127.0.0.1"}},
                {"port": 10809, "listen": "127.0.0.1", "protocol": "http", "settings": {}}
            ],
            "outbounds": [xray_outbound, {"protocol": "freedom", "tag": "direct"}]
            # Add routing rules here if needed
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

class VpnApp(App):
    CSS_PATH = "vpn_style.tcss"
    TITLE = "Termux V2Ray/Xray Client"
    SUB_TITLE = "Manage Connections"

    BINDINGS = [
        ("q", "quit_app", "Quit"), ("a", "add_subscription_action", "Add Sub"),
        ("u", "update_subscriptions_action", "Update Subs"), ("s", "stop_xray_action", "Stop Xray"),
        ("c", "check_xray_path_action", "Check Xray"),
    ]

    subscriptions = reactive(load_subscriptions())
    raw_configs_from_subs = reactive([])
    parsed_server_configs = reactive([])
    active_log_message = reactive("App Started. Welcome!") # For status bar

    def on_mount(self) -> None:
        self.log_to_widget("App mounted. Welcome!")
        self.call_later(self.check_xray_path, silent=True) # Check Xray on startup

    def log_to_widget(self, message: str):
        log_widget = self.query_one("#main_log", Log)
        current_time = time.strftime("%H:%M:%S")
        log_widget.write_line(f"[{current_time}] {message}")
        self.active_log_message = message # Update reactive var for status bar

    async def show_message_modal(self, message: str):
        await self.push_screen(MessageScreen(message))

    def check_xray_path(self, silent: bool = False) -> bool:
        path_status_widget = self.query_one("#xray_path_status", Static)
        if not XRAY_PATH.exists() or not os.access(XRAY_PATH, os.X_OK):
            msg = f"Xray NOT found/executable: {XRAY_PATH}"
            tip = ("\nPlease download Xray core (e.g., linux-arm32-v7a for your Termux) "
                   f"and place it as 'xray' in the same directory as this script ('{SCRIPT_DIR}'). "
                   "Then `chmod +x xray`.")
            self.log_to_widget(msg + tip)
            path_status_widget.update(f"[b red]{msg}[/b red]") # Rich markup for color
            if not silent: self.call_later(self.show_message_modal, msg + tip)
            return False
        
        status_msg = f"Xray OK: {XRAY_PATH}"
        self.log_to_widget(status_msg)
        path_status_widget.update(f"[b green]{status_msg}[/b green]")
        return True
    
    async def action_check_xray_path_action(self) -> None: self.check_xray_path()

    def start_xray(self, config_dict: dict) -> bool:
        if not self.check_xray_path(): return False
        self.stop_xray()
        with open(LAST_SELECTED_CONFIG_FILE, "w") as f: json.dump(config_dict, f, indent=2)
        self.log_to_widget(f"Starting Xray with: {LAST_SELECTED_CONFIG_FILE.name}")
        try:
            process = subprocess.Popen(
                [str(XRAY_PATH), "run", "-c", str(LAST_SELECTED_CONFIG_FILE)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL # Suppress Xray's direct output for cleaner TUI
            )
            time.sleep(1) # Allow Xray to start/fail
            if process.poll() is None:
                with open(CURRENT_XRAY_PID_FILE, "w") as pf: pf.write(str(process.pid))
                self.log_to_widget(f"Xray started. PID: {process.pid}. SOCKS: 127.0.0.1:10808")
                return True
            else:
                self.log_to_widget(f"Failed to start Xray. Return code: {process.returncode}.")
                return False
        except Exception as e:
            self.log_to_widget(f"Exception starting Xray: {e}")
            return False

    def stop_xray(self) -> bool:
        if CURRENT_XRAY_PID_FILE.exists():
            try:
                with open(CURRENT_XRAY_PID_FILE, "r") as pf: pid = int(pf.read().strip())
                os.kill(pid, subprocess.signal.SIGTERM) # Graceful termination
                time.sleep(0.5) # Wait a bit
                try: # Check if still alive then kill
                    os.kill(pid, 0) # Check if process exists
                    os.kill(pid, subprocess.signal.SIGKILL)
                    self.log_to_widget(f"Force stopped Xray process {pid}.")
                except OSError: # Process already exited
                    self.log_to_widget(f"Xray process {pid} exited gracefully.")
            except Exception as e: self.log_to_widget(f"Error stopping Xray PID {pid}: {e}")
            finally: CURRENT_XRAY_PID_FILE.unlink(missing_ok=True); return True
        self.log_to_widget("No active Xray PID file found.")
        return False
    
    async def action_stop_xray_action(self) -> None:
        if self.stop_xray(): await self.show_message_modal("Attempted to stop Xray.")
        else: await self.show_message_modal("Xray not running or PID file missing.")

    async def action_add_subscription_action(self) -> None:
        def after_add_sub_screen_callback(new_url: str | None):
            if new_url:
                if any(sub.get('url') == new_url for sub in self.subscriptions):
                    msg = f"Subscription URL already exists: {new_url}"
                    self.log_to_widget(msg)
                    self.call_later(self.show_message_modal, msg)
                    return
                new_entry = {"name": f"Sub_{len(self.subscriptions)+1}", "url": new_url, "last_update": None}
                self.subscriptions = self.subscriptions + [new_entry] # Trigger reactive update
                save_subscriptions(self.subscriptions)
                self.log_to_widget(f"Added subscription: {new_url}")
            else: self.log_to_widget("Add subscription cancelled.")
        await self.push_screen(AddSubScreen(), after_add_sub_screen_callback)

    async def action_update_subscriptions_action(self) -> None:
        if not self.subscriptions:
            await self.show_message_modal("No subscriptions to update. Add one with 'a'.")
            return
        self.log_to_widget("Updating subscriptions...")
        all_raw = []
        updated_subs_list = list(self.subscriptions) # Create a mutable copy
        for i, sub_entry in enumerate(updated_subs_list):
            url = sub_entry.get("url")
            self.log_to_widget(f"Fetching: {url[:50]}...")
            try:
                # Using asyncio.create_subprocess_shell for non-blocking curl
                process = await asyncio.create_subprocess_shell(
                    f"curl -L -s --connect-timeout 10 --max-time 20 '{url}'",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()
                if process.returncode == 0 and stdout:
                    decoded_links = decode_base64_content(stdout.decode(errors="ignore"))
                    self.log_to_widget(f"Decoded {len(decoded_links)} links from {sub_entry.get('name')}")
                    all_raw.extend(decoded_links)
                    updated_subs_list[i]["last_update"] = time.time() # Update timestamp
                else: self.log_to_widget(f"Error fetching {sub_entry.get('name')}: {stderr.decode(errors='ignore')[:100]}")
            except Exception as e: self.log_to_widget(f"Exception fetching {sub_entry.get('name')}: {e}")
        
        self.subscriptions = updated_subs_list # Update subscriptions with new timestamps
        save_subscriptions(self.subscriptions) # Save them
        self.raw_configs_from_subs = all_raw
        self.log_to_widget(f"Total raw configs: {len(self.raw_configs_from_subs)}")
        self.process_raw_configs()

    def process_raw_configs(self):
        parsed_list = [p for raw_link in self.raw_configs_from_subs if (p := parse_vmess_link(raw_link))]
        self.parsed_server_configs = parsed_list
        self.log_to_widget(f"Parsed {len(self.parsed_server_configs)} VMess configs (basic parse).")
        # Placeholder for actual testing and sorting logic

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="main_layout"):
            with Horizontal(id="status_bar"):
                 yield Static(f"Xray status checking...", id="xray_path_status")
                 yield Static(self.active_log_message, id="active_log_display")
            yield Label("Subscriptions:", classes="section_header")
            yield VerticalScroll(id="subscriptions_list_container", classes="list_container")
            yield Label("Available Servers (VMess Only - Parsed, Not Tested):", classes="section_header")
            yield VerticalScroll(id="server_list_display_container", classes="list_container") # Container for buttons
            yield Label("Log:", classes="section_header")
            yield Log(id="main_log", auto_scroll=True, max_lines=100)
        yield Footer()
        self.call_later(self.update_subscription_list_ui) # Initial population
        self.call_later(self.update_server_list_ui)       # Initial population

    async def watch_subscriptions(self, old_subs: list, new_subs: list) -> None:
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

    def update_server_list_ui(self):
        container = self.query_one("#server_list_display_container")
        container.remove_children()
        if not self.parsed_server_configs:
            container.mount(Static("No servers parsed. Update subscriptions with 'u'.", classes="placeholder_text"))
        else:
            container.mount(Static(f"{len(self.parsed_server_configs)} servers found (click to connect - first only for now):"))
            for idx, config in enumerate(self.parsed_server_configs):
                ps_name = config.get("ps", f"Server_{idx+1}")
                address = config.get("add", "N/A")
                # Create a button for each server (or first few for demo)
                # For simplicity, only one "connect first" button is implemented for now via on_button_pressed
                # This is where you'd make each item interactive or use a DataTable
                display_text = f"[{idx+1}] {ps_name} ({address})"
                # For demo, we just use one button below. If you want individual buttons:
                # server_button = Button(display_text, id=f"connect_server_{idx}")
                # container.mount(server_button)
                container.mount(Markdown(display_text, classes="server_entry")) # Display as Markdown

            # Add a single button to connect to the first server
            if self.parsed_server_configs: # Ensure there's at least one
                first_server_name = self.parsed_server_configs[0].get("ps", "First Server")
                connect_button = Button(f"Connect: {first_server_name}", variant="success", id="connect_first_parsed_server_button")
                container.mount(connect_button)
    
    async def watch_active_log_message(self, _: str, new_log_msg: str) -> None:
        try:
            status_bar_log = self.query_one("#active_log_display", Static)
            status_bar_log.update(new_log_msg[:80]) # Truncate for status bar
        except Exception: pass # Widget might not exist yet

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "connect_first_parsed_server_button":
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

    async def action_quit_app(self) -> None:
        self.stop_xray()
        self.exit("User requested quit.")

# --- CSS for the App (vpn_style.tcss) ---
VPN_APP_CSS = """
Screen {
    background: $surface;
    color: $text;
    layout: vertical;
    overflow-y: auto; /* Allow screen to scroll if content is too long */
}
Header { dock: top; background: $primary; color: $text; height: 1; text-style: bold; }
Header Title, Header SubTitle { color: $text; }
Footer { dock: bottom; background: $primary-darken-2; color: $text-muted; height: 1; }

#main_layout { padding: 0 1; height: 1fr; }
#status_bar { height: 1; background: $primary-background-darken-1; padding: 0 1; dock: top; }
#xray_path_status { width: 1fr; content-align: left middle; color: $text-muted; }
#active_log_display { width: 3fr; content-align: right middle; color: $warning; overflow: hidden; }

.section_header { padding: 1 0 0 0; text-style: bold underline; color: $secondary; }

.list_container { /* Common style for subscription and server list containers */
    border: round $primary-background-darken-2;
    padding: 0 1;
    height: auto; 
    max-height: 10; /* Max height before scrolling */
    overflow-y: auto;
    margin-bottom: 1; /* Space below list containers */
}
#subscriptions_list_container { /* Specific if needed, else uses .list_container */ }
#server_list_display_container { /* Specific if needed, else uses .list_container */
    /* max-height: 1fr; /* Allow server list to take more space if needed, but careful with Log below */
}


.sub_entry, .server_entry { /* Common style for list items */
    padding: 1 0;
    background: $boost;
    border-bottom: dashed $primary-background-darken-3;
}
.server_entry Button { width: 100%; } /* If using buttons for each server */

#connect_first_parsed_server_button { width: 100%; margin-top: 1; }

#main_log { border: panel $primary-background-darken-2; height: 8; margin-top: 1; }
.placeholder_text { color: $text-muted; padding: 1; text-align: center; }

#add_sub_dialog, #message_dialog {
    padding: 0 1; width: 80%; max-width: 60; height: auto;
    border: thick $secondary; background: $panel;
}
.modal_label { padding: 1 0; }
.modal_buttons { padding-top: 1; align-horizontal: right; }
.modal_buttons Button { margin-left: 1; }
"""

# --- Main Execution ---
if __name__ == "__main__":
    css_file_path = SCRIPT_DIR / "vpn_style.tcss"
    if not css_file_path.exists():
        with open(css_file_path, "w") as cf:
            cf.write(VPN_APP_CSS)
            print(f"Created CSS file: {css_file_path}")
    
    app = VpnApp()
    app.run()
