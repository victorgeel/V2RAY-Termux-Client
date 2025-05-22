import json
import base64
import subprocess
import os
import time
from pathlib import Path

# --- Textual App Imports ---
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Button, Static, Log, Input, Label, Markdown
from textual.containers import VerticalScroll, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen

# --- Configuration ---
CONFIG_DIR = Path.home() / ".v2ray_termux_client"
SUBS_FILE = CONFIG_DIR / "subscriptions.json"
XRAY_PATH = CONFIG_DIR / "xray" # Expected path to Xray binary
LAST_SELECTED_CONFIG_FILE = CONFIG_DIR / "last_selected_v2ray_config.json"
CURRENT_XRAY_PID_FILE = CONFIG_DIR / "xray.pid"

# Ensure config directory exists
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

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
    This is a VERY basic parser and needs to be much more robust.
    Example: vmess://ewogICJ2IjogIjIiLAogICJpZCI6ICJhYmMxMjMiLAogICJhZGRyIjogInNlcnZlci5jb20iLAogICJwb3J0IjogIjQ0MyIsCiAgInR5cGUiOiAibm9uZSIsCiAgImhvc3QiOiAid3d3LmV4YW1wbGUuY29tIiwKICAicGF0aCI6ICIvZm9vYmFyIiwKICAibmV0IjogIndzIiwKICAidGxzIjogInRscyIsCiAgInBzIjogIk15IFNlcnZlciIKfQ==
    """
    if not vmess_link.startswith("vmess://"):
        return None
    try:
        base64_config = vmess_link[8:]
        # Add padding if necessary for base64 decoding
        padding = '=' * (4 - len(base64_config) % 4)
        base64_config += padding
        decoded_json = base64.b64decode(base64_config).decode("utf-8")
        config = json.loads(decoded_json)
        # Add the original link for reference or re-testing
        config['_raw_link'] = vmess_link
        return config
    except Exception as e:
        # self.log_message(f"Error parsing VMess link: {vmess_link} - {e}") # How to log from here?
        return None


def generate_xray_config(server_config: dict) -> dict | None:
    """
    Generates a full Xray client configuration for a given server.
    The server_config is expected to be the parsed output from parse_vmess_link.
    """
    if not server_config:
        return None

    # Basic Xray client configuration structure
    # This needs to be adapted based on the actual content of server_config (ps, add, port, id, net, type, host, path, tls, etc.)
    try:
        xray_outbound = {
            "protocol": "vmess",
            "settings": {
                "vnext": [
                    {
                        "address": server_config.get("add", ""),
                        "port": int(server_config.get("port", 443)),
                        "users": [
                            {
                                "id": server_config.get("id", ""),
                                "alterId": int(server_config.get("aid", 0)), # V2Ray's alterId, Xray usually uses 0
                                "security": server_config.get("scy", "auto")
                            }
                        ]
                    }
                ]
            },
            "streamSettings": {
                "network": server_config.get("net", "tcp"),
                "security": server_config.get("tls", "none"),
            }
        }
        
        # Add specific stream settings based on network type (ws, grpc, etc.)
        if server_config.get("net") == "ws":
            xray_outbound["streamSettings"]["wsSettings"] = {
                "path": server_config.get("path", "/"),
                "headers": {"Host": server_config.get("host", server_config.get("add"))}
            }
        # Add more network types (grpc, tcp, kcp, etc.) as needed

        if server_config.get("tls", "none") == "tls":
             xray_outbound["streamSettings"]["tlsSettings"] = {
                "serverName": server_config.get("sni", server_config.get("host", server_config.get("add"))),
                # "allowInsecure": False, # Add if you need to configure this
            }


        client_config = {
            "log": {"loglevel": "warning"},
            "inbounds": [
                {
                    "port": 10808, # SOCKS port
                    "listen": "127.0.0.1",
                    "protocol": "socks",
                    "settings": {"auth": "noauth", "udp": True, "ip": "127.0.0.1"}
                },
                {
                    "port": 10809, # HTTP port
                    "listen": "127.0.0.1",
                    "protocol": "http",
                    "settings": {}
                }
            ],
            "outbounds": [xray_outbound, {"protocol": "freedom", "tag": "direct"}]
            # Add routing rules if needed
        }
        return client_config
    except Exception as e:
        # Log error
        return None

# --- Textual Screens ---

class AddSubScreen(ModalScreen):
    """Screen for adding a new subscription URL."""
    
    BINDINGS = [("escape", "pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Enter Subscription URL:", classes="modal_label"),
            Input(placeholder="https://example.com/sub", id="sub_url_input"),
            Horizontal(
                Button("Add", variant="primary", id="add_sub_button"),
                Button("Cancel", id="cancel_add_sub_button"),
                classes="modal_buttons"
            ),
            id="add_sub_dialog"
        )

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add_sub_button":
            input_widget = self.query_one(Input)
            new_url = input_widget.value.strip()
            if new_url:
                self.dismiss(new_url)
            else:
                self.dismiss(None)
        elif event.button.id == "cancel_add_sub_button":
            self.dismiss(None)

class MessageScreen(ModalScreen):
    """A modal screen to show a message and an OK button."""
    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        yield Vertical(
            Markdown(self.message), # Use Markdown for better formatting
            Button("OK", variant="primary", id="ok_button"),
            id="message_dialog"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok_button":
            self.dismiss()

class VpnApp(App):
    """Main V2Ray/Xray Termux Client App."""

    CSS_PATH = "vpn_style.tcss" # Will create this later
    TITLE = "V2Ray/Xray Termux Client"
    SUB_TITLE = "Manage your connections"

    BINDINGS = [
        ("q", "quit_app", "Quit"),
        ("a", "add_subscription", "Add Sub URL"),
        ("u", "update_subscriptions_action", "Update Subs"),
        ("s", "stop_xray_action", "Stop Xray"),
        ("c", "check_xray_path_action", "Check Xray Path"),
    ]

    subscriptions = reactive(load_subscriptions())
    raw_configs_from_subs = reactive([]) # List of raw links (vmess://...)
    parsed_server_configs = reactive([]) # List of dicts from parsed links
    active_log = reactive("") # For general status messages

    def on_mount(self) -> None:
        """Called when app is mounted."""
        self.log_message("App mounted. Welcome!")
        self.check_xray_path(silent=True) # Check for Xray on startup

    def log_message(self, message: str):
        """Appends a message to the log widget."""
        log_widget = self.query_one(Log)
        current_time = time.strftime("%H:%M:%S")
        log_widget.write_line(f"[{current_time}] {message}")
        self.active_log = message # Update reactive var for status bar or other uses

    async def show_message_modal(self, message: str):
        """Helper to show a modal message."""
        await self.push_screen(MessageScreen(message))

    # --- Xray Process Management (Simplified) ---
    def check_xray_path(self, silent: bool = False) -> bool:
        if not XRAY_PATH.exists() or not os.access(XRAY_PATH, os.X_OK):
            msg = (
                f"Xray binary not found or not executable at '{XRAY_PATH}'.\n"
                "Please download the Xray core for your architecture (e.g., linux-arm64-v8a)\n"
                f"from https://github.com/XTLS/Xray-core/releases, extract it, and place the 'xray' file at:\n"
                f"'{XRAY_PATH}'\nThen make it executable: `chmod +x {XRAY_PATH}`"
            )
            self.log_message(msg)
            if not silent:
                self.call_later(self.show_message_modal, msg) # Call later to avoid issues during mount
            return False
        self.log_message(f"Xray binary found at {XRAY_PATH}")
        return True
    
    async def action_check_xray_path_action(self) -> None:
        self.check_xray_path()


    def start_xray(self, config_dict: dict) -> bool:
        if not self.check_xray_path():
            return False
        
        self.stop_xray() # Ensure any existing instance is stopped

        with open(LAST_SELECTED_CONFIG_FILE, "w") as f:
            json.dump(config_dict, f, indent=2)
        
        self.log_message(f"Attempting to start Xray with config: {LAST_SELECTED_CONFIG_FILE}")
        try:
            # Using Popen for non-blocking execution
            process = subprocess.Popen(
                [str(XRAY_PATH), "run", "-c", str(LAST_SELECTED_CONFIG_FILE)],
                stdout=subprocess.PIPE, # Capture stdout
                stderr=subprocess.PIPE  # Capture stderr
            )
            time.sleep(1) # Give Xray a moment to start or fail

            if process.poll() is None: # Process is still running
                with open(CURRENT_XRAY_PID_FILE, "w") as pf:
                    pf.write(str(process.pid))
                self.log_message(f"Xray started successfully. PID: {process.pid}. SOCKS: 127.0.0.1:10808, HTTP: 127.0.0.1:10809")
                # For more robust check, you might try to connect to the proxy port.
                return True
            else: # Process terminated quickly, likely an error
                stdout, stderr = process.communicate()
                err_msg = stderr.decode(errors='ignore') or stdout.decode(errors='ignore')
                self.log_message(f"Failed to start Xray. Return code: {process.returncode}. Error: {err_msg}")
                return False
        except Exception as e:
            self.log_message(f"Exception while starting Xray: {e}")
            return False

    def stop_xray(self) -> bool:
        if CURRENT_XRAY_PID_FILE.exists():
            try:
                with open(CURRENT_XRAY_PID_FILE, "r") as pf:
                    pid = int(pf.read().strip())
                # Check if process exists
                os.kill(pid, 0) # Raises an OSError if pid does not exist or you don't have permission
                os.kill(pid, subprocess.signal.SIGTERM) # Terminate gracefully
                time.sleep(0.5)
                os.kill(pid, subprocess.signal.SIGKILL) # Force kill if still running
                self.log_message(f"Sent SIGKILL to Xray process {pid}.")
            except (OSError, ValueError, ProcessLookupError) as e: # Catch if pid invalid or process not found
                self.log_message(f"Xray process not found or already stopped ({e}).")
            except Exception as e:
                self.log_message(f"Error stopping Xray process {pid}: {e}")
            finally:
                CURRENT_XRAY_PID_FILE.unlink(missing_ok=True)
                return True
        self.log_message("No active Xray process found (no PID file).")
        return False
    
    async def action_stop_xray_action(self) -> None:
        if self.stop_xray():
            await self.show_message_modal("Attempted to stop Xray.")
        else:
            await self.show_message_modal("Xray was not running or PID file missing.")


    # --- Subscription and Config Processing ---
    async def action_add_subscription(self) -> None:
        """Shows the Add Subscription modal screen."""
        def_new_sub_url = "" # To hold the result from modal

        def after_add_sub_screen(new_url: str | None):
            nonlocal def_new_sub_url 
            def_new_sub_url = new_url # Assign to outer scope variable
            if def_new_sub_url: # Check if new_url has a value
                if any(sub.get('url') == def_new_sub_url for sub in self.subscriptions):
                    self.log_message(f"Subscription URL already exists: {def_new_sub_url}")
                    self.call_later(self.show_message_modal, f"Subscription URL already exists:\n{def_new_sub_url}")
                    return

                new_sub_entry = {"name": f"Subscription {len(self.subscriptions) + 1}", "url": def_new_sub_url, "last_update": None}
                
                # Create a new list, append, then assign to reactive var
                updated_subs = list(self.subscriptions) # Create a copy
                updated_subs.append(new_sub_entry)
                self.subscriptions = updated_subs # This will trigger watchers

                save_subscriptions(self.subscriptions)
                self.log_message(f"Added subscription: {def_new_sub_url}")
                self.call_later(self.show_message_modal, f"Added subscription:\n{def_new_sub_url}")
            else:
                 self.log_message("Add subscription cancelled.")

        await self.push_screen(AddSubScreen(), after_add_sub_screen)


    async def action_update_subscriptions_action(self) -> None:
        """Fetches and processes all subscription URLs."""
        if not self.subscriptions:
            self.log_message("No subscription URLs to update.")
            await self.show_message_modal("No subscription URLs to update.\nPlease add one first using 'a'.")
            return

        self.log_message("Starting subscription update...")
        # For simplicity, we'll use subprocess to call curl.
        # In a real app, use an async HTTP client like 'httpx'.
        
        all_new_raw_configs = []
        updated_subs_data = list(self.subscriptions) # Make a mutable copy

        for i, sub_entry in enumerate(updated_subs_data):
            url = sub_entry.get("url")
            self.log_message(f"Fetching: {url}")
            try:
                # Using curl via subprocess for simplicity in Termux environment
                # Consider using httpx for async requests in a more complex app
                process = await asyncio.create_subprocess_shell(
                    f"curl -L -s --connect-timeout 10 '{url}'", # Added -L for redirects, -s for silent
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()

                if process.returncode == 0:
                    content = stdout.decode("utf-8", errors="ignore")
                    if not content.strip():
                        self.log_message(f"Empty content from {url}")
                        continue
                    
                    decoded_links = decode_base64_content(content)
                    self.log_message(f"Decoded {len(decoded_links)} links from {url}")
                    all_new_raw_configs.extend(decoded_links)
                    
                    # Update last_update timestamp
                    updated_subs_data[i]["last_update"] = time.time()

                else:
                    self.log_message(f"Error fetching {url}: {stderr.decode(errors='ignore')}")
            except Exception as e:
                self.log_message(f"Exception fetching {url}: {e}")
        
        self.raw_configs_from_subs = all_new_raw_configs # Update reactive variable
        save_subscriptions(updated_subs_data) # Save updated timestamps
        self.subscriptions = updated_subs_data # Trigger UI update if any

        self.log_message(f"Total raw configs obtained: {len(self.raw_configs_from_subs)}")
        self.process_raw_configs() # Now parse them

    def process_raw_configs(self):
        """Parses raw configuration links into structured dicts."""
        parsed_list = []
        for raw_link in self.raw_configs_from_subs:
            # Assuming VMess for now
            parsed = parse_vmess_link(raw_link)
            if parsed:
                parsed_list.append(parsed)
            else:
                self.log_message(f"Failed to parse: {raw_link[:30]}...")
        
        self.parsed_server_configs = parsed_list # Update reactive variable
        self.log_message(f"Successfully parsed {len(self.parsed_server_configs)} server configs.")
        
        # Placeholder: Here you would test connectivity and sort by latency
        # For now, we'll just use the first parsed config if available
        if self.parsed_server_configs:
            self.log_message("Placeholder: Configs ready. Select one to connect (not implemented yet in UI).")
            self.update_server_list_ui() # Refresh server list display
        else:
            self.log_message("No usable server configs found after parsing.")
            self.update_server_list_ui() # Refresh server list display (will be empty)


    # --- UI Composition and Updates ---
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="main_layout"):
            with Horizontal(id="status_bar"):
                 yield Static(f"Xray: {XRAY_PATH}", id="xray_path_status")
                 yield Static(self.active_log, id="active_log_display") # Display reactive log

            yield Label("Subscriptions:", classes="section_header")
            yield VerticalScroll(id="subscriptions_list_container") # Will populate this

            yield Label("Available Server Configs (VMess Only - Parsed):", classes="section_header")
            yield VerticalScroll( Log(id="server_config_log_display", auto_scroll=False, max_lines=300) , id="server_list_container") # Will populate this

            yield Label("Log:", classes="section_header")
            yield Log(id="main_log", auto_scroll=True, max_lines=100)
        yield Footer()
        # Initial population after compose
        self.call_later(self.update_subscription_list_ui)
        self.call_later(self.update_server_list_ui)


    @reactive. πολλές("subscriptions") # Greek for "watch"
    async def _watch_subscriptions(self, old_subs: list, new_subs: list) -> None:
        self.update_subscription_list_ui()

    def update_subscription_list_ui(self):
        """Updates the display of subscription URLs."""
        container = self.query_one("#subscriptions_list_container")
        # Clear previous buttons/widgets if any simple way or re-compose
        # For simplicity, we'll clear and add. In complex apps, manage widgets more carefully.
        container.remove_children() 
        
        new_widgets = []
        if not self.subscriptions:
            new_widgets.append(Static("No subscriptions. Press 'a' to add.", classes="placeholder_text"))
        else:
            for idx, sub_entry in enumerate(self.subscriptions):
                sub_name = sub_entry.get("name", f"Sub {idx+1}")
                sub_url = sub_entry.get("url", "N/A")
                last_update_ts = sub_entry.get("last_update")
                last_update_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(last_update_ts)) if last_update_ts else "Never"
                
                # Using Markdown for richer text display
                md_text = f"**{sub_name}**: `{sub_url}`\n_Last Update: {last_update_str}_"
                new_widgets.append(Markdown(md_text, classes="sub_entry_markdown"))
                # Add delete/edit buttons per sub later if needed
        container.mount_all(new_widgets)
    
    @reactive. πολλές("parsed_server_configs")
    async def _watch_parsed_server_configs(self, old_parsed: list, new_parsed: list) -> None:
        self.update_server_list_ui()

    def update_server_list_ui(self):
        """Updates the display of parsed server configurations."""
        log_display = self.query_one("#server_config_log_display", Log)
        log_display.clear() # Clear previous entries

        if not self.parsed_server_configs:
            log_display.write_line("No server configs available or parsed yet. Update subscriptions.")
        else:
            log_display.write_line(f"Found {len(self.parsed_server_configs)} configs. Click to connect (not interactive yet):")
            for idx, config in enumerate(self.parsed_server_configs):
                # Display some key info from the parsed config
                ps_name = config.get("ps", f"Server {idx+1}")
                address = config.get("add", "N/A")
                port = config.get("port", "N/A")
                net = config.get("net", "N/A")
                
                # Make each server config clickable (basic for now)
                # In a real app, use a DataTable or custom Widget for better interaction
                log_display.write_line(f"[{idx+1}] {ps_name} ({address}:{port} - {net})")
                # Placeholder for connecting - for now, let's connect the first one if any button is pressed
        
        # Example: if you had a connect button for the first server:
        # connect_button = Button(f"Connect to {self.parsed_server_configs[0].get('ps', 'Server 1')}", id="connect_first_server")
        # server_list_container.mount(connect_button)
        # ... then handle on_button_pressed for "connect_first_server"
        # For now, connecting a specific server needs a more interactive list.
        # We'll just demonstrate starting Xray with the *first* available config if user presses a hypothetical key later.
        # Or, a simple approach: let's add a button to connect the first parsed server for demonstration.
        
        server_list_container = self.query_one("#server_list_container")
        
        # Remove old connect button if it exists
        try:
            old_connect_button = server_list_container.query_one("#connect_first_server_button")
            old_connect_button.remove()
        except Exception:
            pass # No button found, fine

        if self.parsed_server_configs:
            first_server_name = self.parsed_server_configs[0].get("ps", "First Server")
            connect_button = Button(f"Connect: {first_server_name}", variant="success", id="connect_first_server_button")
            
            # Mount below the log
            server_list_container.mount(connect_button)
    
    @reactive. πολλές("active_log")
    async def _watch_active_log(self, old_log: str, new_log: str) -> None:
        try:
            log_display_widget = self.query_one("#active_log_display", Static)
            log_display_widget.update(new_log[:100]) # Display truncated log
        except Exception:
            pass # Widget might not be ready during initial mount

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "connect_first_server_button":
            if self.parsed_server_configs:
                self.log_message("Connect button pressed for first server.")
                first_config_data = self.parsed_server_configs[0]
                xray_json_config = generate_xray_config(first_config_data)
                if xray_json_config:
                    if self.start_xray(xray_json_config):
                         await self.show_message_modal(f"Xray started with '{first_config_data.get('ps', 'Unknown Server')}'")
                    else:
                         await self.show_message_modal(f"Failed to start Xray with '{first_config_data.get('ps', 'Unknown Server')}'")
                else:
                    self.log_message("Failed to generate Xray JSON for the selected config.")
                    await self.show_message_modal("Could not generate valid Xray config.")
            else:
                self.log_message("Connect button pressed, but no parsed configs available.")
                await self.show_message_modal("No server configs available to connect.")

    async def action_quit_app(self) -> None:
        """Called when 'q' is pressed."""
        self.stop_xray() # Ensure Xray is stopped on exit
        self.exit("User requested quit.")

# --- CSS for the App (vpn_style.tcss) ---
VPN_APP_CSS = """
Screen {
    background: $surface;
    color: $text;
    layout: vertical;
}

Header {
    dock: top;
    background: $primary; /* Darker blue */
    color: $text; /* White or light text */
    height: 1;
    text-style: bold;
}
Header Title, Header SubTitle {
    color: $text;
}


Footer {
    dock: bottom;
    background: $primary-darken-2; /* Even darker blue */
    color: $text-muted; /* Greyish text */
    height: 1;
}

#main_layout {
    padding: 0 1; /* Horizontal padding */
    height: 1fr; /* Fill available space */
}

#status_bar {
    height: 1;
    background: $primary-background-darken-1; /* Slightly darker than screen */
    padding: 0 1;
    dock: top; /* Dock it below header but above main content */
}
#xray_path_status {
    width: 1fr;
    content-align: left middle;
    color: $text-muted;
}
#active_log_display {
    width: 2fr; /* Give more space to log */
    content-align: right middle;
    color: $warning; /* Use warning color for active log */
    overflow: hidden;
}


.section_header {
    padding: 1 0 0 0;
    text-style: bold underline;
    color: $secondary; /* A distinct color like teal or orange */
}

#subscriptions_list_container {
    border: round $primary-background-darken-2;
    padding: 0 1;
    height: auto; /* Adjust based on content or set fixed */
    max-height: 8; /* Example max height */
    overflow-y: auto; /* Allow scrolling if content exceeds max-height */
}

.sub_entry_markdown {
    padding: 1 0;
    background: $boost;
    border-bottom: dashed $primary-background-darken-3;
}

#server_list_container {
    border: round $primary-background-darken-2;
    padding: 0;
    height: 1fr; /* Take up remaining space */
    /* max-height: 15; Remove fixed max-height to fill space */
    overflow-y: auto;
}
#server_config_log_display {
    /* Styles for the Log widget inside server_list_container */
    height: 1fr; /* Make the Log widget fill its container */
}


#connect_first_server_button {
    width: 100%;
    margin-top: 1;
}


#main_log {
    border: panel $primary-background-darken-2;
    height: 8; /* Fixed height for the main log */
    margin-top: 1;
}

.placeholder_text {
    color: $text-muted;
    padding: 1;
    text-align: center;
}

/* Modal Dialog Styles */
#add_sub_dialog, #message_dialog {
    padding: 0 1;
    width: 80%;
    max-width: 60; /* Max width for dialogs */
    height: auto;
    border: thick $secondary;
    background: $panel;
}
.modal_label {
    padding: 1 0;
}
.modal_buttons {
    padding-top: 1;
    align-horizontal: right; /* Align buttons to the right */
}
.modal_buttons Button {
    margin-left: 1; /* Space between buttons */
}
"""

# --- Main Execution ---
if __name__ == "__main__":
    # Create the CSS file if it doesn't exist
    css_file_path = Path(__file__).parent / "vpn_style.tcss"
    if not css_file_path.exists():
        with open(css_file_path, "w") as cf:
            cf.write(VPN_APP_CSS)
            print(f"Created CSS file: {css_file_path}")

    # Import asyncio here, only if __main__
    # This can help avoid some import issues on certain platforms or with Textual's reloading
    import asyncio 
    
    app = VpnApp()
    app.run()
