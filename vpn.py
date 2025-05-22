import json
import base64
import subprocess
import os
import time
from pathlib import Path
import asyncio

# --- Textual App Imports ---
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Button, Static, Log, Input, Label, Markdown
from textual.containers import VerticalScroll, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen

# --- Configuration ---
SCRIPT_DIR = Path(__file__).resolve().parent
XRAY_PATH = SCRIPT_DIR / "xray"

CONFIG_STORAGE_DIR = Path.home() / ".v2ray_termux_client"
SUBS_FILE = CONFIG_STORAGE_DIR / "subscriptions.json"
LAST_SELECTED_CONFIG_FILE = CONFIG_STORAGE_DIR / "last_selected_xray_config.json"
TEST_XRAY_CONFIG_FILE = CONFIG_STORAGE_DIR / "test_xray_config.json"
CURRENT_XRAY_PID_FILE = CONFIG_STORAGE_DIR / "xray.pid"

CONFIG_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

# --- Application Information Constants (Global for easy access) ---
APP_TITLE = "Termux V2Ray/Xray Client"
APP_SUB_TITLE = "Manage Connections"
APP_VERSION = "0.3.0" # Updated version example
DEVELOPER_NAME_CONST = "Developer Victor Geek"
DEVELOPER_EMAIL_CONST = "frussel4@asu.edu"

# --- Helper Functions ---
def load_subscriptions():
    if SUBS_FILE.exists():
        try:
            with open(SUBS_FILE, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return []
    return []

def save_subscriptions(subs):
    with open(SUBS_FILE, "w") as f:
        json.dump(subs, f, indent=2)

def decode_base64_content(content: str) -> list:
    try:
        decoded_bytes = base64.b64decode(content)
        decoded_str = decoded_bytes.decode("utf-8")
        return decoded_str.strip().splitlines()
    except Exception:
        return []

def parse_vmess_link(vmess_link: str) -> dict | None:
    if not vmess_link.startswith("vmess://"):
        return None
    try:
        base64_config = vmess_link[8:]
        padding = '=' * (4 - len(base64_config) % 4)
        base64_config += padding
        decoded_json = base64.b64decode(base64_config).decode("utf-8")
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
        # Default SNI to host, then address if host is empty
        default_sni = config.get('host') if config.get('host') else config.get('add')
        config['sni'] = config.get('sni', default_sni if default_sni else "") # Ensure SNI is not None
        # Default PS (name) for the server
        default_ps = f"{config.get('add', 'UnknownAddress')}:{config.get('port', 'N/A')}"
        config['ps'] = config.get('ps', default_ps)
        config['_raw_link'] = vmess_link
        return config
    except Exception:
        return None

def generate_xray_config(server_config: dict) -> dict | None:
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
                        "security": server_config.get("scy", "auto")
                    }]
                }]
            },
            "streamSettings": {
                "network": server_config.get("net"),
                "security": server_config.get("tls"),
            }
        }
        
        net_type = server_config.get("net")
        host_header = server_config.get("host", server_config.get("add")) # Use 'add' if 'host' is empty
        if net_type == "ws":
            xray_outbound["streamSettings"]["wsSettings"] = {
                "path": server_config.get("path"),
                "headers": {"Host": host_header}
            }
        elif net_type == "grpc":
             xray_outbound["streamSettings"]["grpcSettings"] = {
                "serviceName": server_config.get("path") 
            }

        if server_config.get("tls") == "tls":
             xray_outbound["streamSettings"]["tlsSettings"] = {
                "serverName": server_config.get("sni", host_header),
                "allowInsecure": server_config.get("allowInsecure", False),
            }
             fp = server_config.get("fp") # Fingerprint for TLS
             if fp: xray_outbound["streamSettings"]["tlsSettings"]["fingerprint"] = fp


        client_config = {
            "log": {"loglevel": "warning"},
            "inbounds": [
                {"port": 10808, "listen": "127.0.0.1", "protocol": "socks", "settings": {"auth": "noauth", "udp": True, "ip": "127.0.0.1"}},
                {"port": 10809, "listen": "127.0.0.1", "protocol": "http", "settings": {}}
            ],
            "outbounds": [xray_outbound, {"protocol": "freedom", "tag": "direct"}],
             "routing": {
                "rules": [
                    {"type": "field", "ip": ["geoip:private"], "outboundTag": "direct"}
                ]
            }
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
            id="about_dialog"
        )
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok_about_button":
            self.dismiss()

class VpnApp(App):
    CSS_PATH = "vpn_style.tcss"
    TITLE = APP_TITLE
    SUB_TITLE = APP_SUB_TITLE
    DEVELOPER_NAME = DEVELOPER_NAME_CONST
    DEVELOPER_EMAIL = DEVELOPER_EMAIL_CONST

    BINDINGS = [
        ("q", "quit_app", "Quit"), ("a", "add_subscription_action", "Add Sub"),
        ("u", "update_subscriptions_action", "Update Subs"),
        ("s", "stop_xray_action", "Stop Xray"),
        ("c", "check_xray_path_action", "Check Xray"),
        ("f1", "show_about_screen", "About"),
    ]

    subscriptions = reactive(load_subscriptions())
    raw_configs_from_subs = reactive([])
    parsed_server_configs = reactive([])
    active_log_message = reactive("App Started. Welcome!")

    def on_mount(self) -> None:
        self.log_to_widget("App mounted. Welcome!")
        self.call_later(self.check_xray_path, silent=True)

    def log_to_widget(self, message: str):
        try:
            log_widget = self.query_one("#main_log", Log)
            current_time = time.strftime("%H:%M:%S")
            log_widget.write_line(f"[{current_time}] {message}")
        except Exception: pass
        self.active_log_message = message 

    async def show_message_modal(self, message: str):
        if self.is_running: # Corrected: Removed 'and self.app_is_mounted'
            await self.push_screen(MessageScreen(message))

    def check_xray_path(self, silent: bool = False) -> bool:
        path_status_widget = self.query_one("#xray_path_status", Static)
        if not XRAY_PATH.exists() or not os.access(XRAY_PATH, os.X_OK):
            msg = f"Xray NOT found/executable: {XRAY_PATH}"
            tip = (f"\nPlease download Xray core, place it as 'xray' in '{SCRIPT_DIR}', and run `chmod +x xray`.")
            self.log_to_widget(msg + tip)
            path_status_widget.update(f"[b red]{msg}[/b red]")
            if not silent: self.call_later(self.show_message_modal, msg + tip)
            return False
        status_msg = f"Xray OK: {XRAY_PATH}"
        path_status_widget.update(f"[b green]{status_msg}[/b green]")
        return True
    
    async def action_check_xray_path_action(self) -> None: self.check_xray_path()

    async def action_show_about_screen(self) -> None:
        await self.push_screen(AboutScreen())

    def start_xray(self, config_dict: dict) -> bool:
        if not self.check_xray_path(silent=True): return False
        self.stop_xray()
        try:
            with open(LAST_SELECTED_CONFIG_FILE, "w") as f: json.dump(config_dict, f, indent=2)
            self.log_to_widget(f"Starting Xray with {LAST_SELECTED_CONFIG_FILE.name}")
            process = subprocess.Popen(
                [str(XRAY_PATH), "run", "-c", str(LAST_SELECTED_CONFIG_FILE)],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
            )
            time.sleep(1.2)
            if process.poll() is None:
                with open(CURRENT_XRAY_PID_FILE, "w") as pf: pf.write(str(process.pid))
                self.log_to_widget(f"Xray started. PID: {process.pid}. SOCKS: 127.0.0.1:10808, HTTP: 127.0.0.1:10809")
                return True
            else:
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
                os.kill(pid_to_stop, subprocess.signal.SIGTERM)
                time.sleep(0.5) 
                os.kill(pid_to_stop, 0)
                time.sleep(0.5)
                os.kill(pid_to_stop, subprocess.signal.SIGKILL)
                self.log_to_widget(f"Force stopped Xray process {pid_to_stop}.")
            except OSError: 
                self.log_to_widget(f"Xray process {pid_to_stop} exited.")
            except Exception as e: self.log_to_widget(f"Error stopping Xray PID {pid_to_stop}: {e}")
            finally: 
                CURRENT_XRAY_PID_FILE.unlink(missing_ok=True)
                return True
        return False
    
    async def action_stop_xray_action(self) -> None:
        if self.stop_xray(): await self.show_message_modal("Attempted to stop Xray.")
        else: await self.show_message_modal("Xray not running or PID file missing.")

    async def action_add_subscription_action(self) -> None:
        def after_add_sub_screen_callback(new_url: str | None):
            if new_url:
                if any(sub.get('url') == new_url for sub in self.subscriptions):
                    msg = f"Subscription URL '{new_url[:30]}...' already exists."
                    self.log_to_widget(msg); self.call_later(self.show_message_modal, msg)
                    return
                sub_names = {s.get("name") for s in self.subscriptions}; idx = 1; new_name = f"Sub_{idx}"
                while new_name in sub_names: idx += 1; new_name = f"Sub_{idx}"
                new_entry = {"name": new_name, "url": new_url, "last_update": None}
                self.subscriptions = self.subscriptions + [new_entry] 
                save_subscriptions(self.subscriptions)
                self.log_to_widget(f"Added: {new_name} - {new_url[:40]}...")
            else: self.log_to_widget("Add subscription cancelled.")
        await self.push_screen(AddSubScreen(), after_add_sub_screen_callback)

    async def action_update_subscriptions_action(self) -> None:
        if not self.subscriptions:
            await self.show_message_modal("No subscriptions to update. Add one with 'a'."); return
        self.log_to_widget("Updating subscriptions...")
        all_raw_links = []; updated_subs_list = list(self.subscriptions) 
        fetch_tasks = [self.fetch_single_subscription(sub_entry, i) for i, sub_entry in enumerate(updated_subs_list)]
        results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.log_to_widget(f"Exception gathering fetch for sub {updated_subs_list[i].get('name', i)}: {result}")
            elif result:
                idx, links = result; all_raw_links.extend(links)
                updated_subs_list[idx]["last_update"] = time.time()
        self.subscriptions = updated_subs_list; save_subscriptions(self.subscriptions) 
        self.raw_configs_from_subs = all_raw_links
        self.log_to_widget(f"Total raw configs: {len(self.raw_configs_from_subs)}")
        self.process_raw_configs()

    async def fetch_single_subscription(self, sub_entry: dict, index: int) -> tuple[int, list] | None:
        url = sub_entry.get("url"); name = sub_entry.get("name", f"Sub {index+1}")
        self.log_to_widget(f"Fetching: {name} ({url[:40]}...).")
        decoded_links = []
        try:
            process = await asyncio.create_subprocess_shell(
                f"curl -L -s --connect-timeout 10 --max-time 20 '{url}'",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, stderr = await process.communicate()
            if process.returncode == 0 and stdout:
                decoded_links = decode_base64_content(stdout.decode(errors="ignore"))
                self.log_to_widget(f"Decoded {len(decoded_links)} links from {name}")
            else:
                err_msg = stderr.decode(errors="ignore")[:100].strip()
                self.log_to_widget(f"Error {name} (RC:{process.returncode}): {err_msg if err_msg else 'No stderr'}")
        except Exception as e: self.log_to_widget(f"Exception {name}: {e}")
        return index, decoded_links

    def process_raw_configs(self):
        parsed_list = []; unique_raw_links = set()
        for raw_link in self.raw_configs_from_subs:
            if raw_link not in unique_raw_links:
                parsed_config = parse_vmess_link(raw_link)
                if parsed_config: parsed_list.append(parsed_config)
                unique_raw_links.add(raw_link)
        self.parsed_server_configs = sorted(parsed_list, key=lambda x: x.get('ps', 'zzzz').lower())
        self.log_to_widget(f"Parsed {len(self.parsed_server_configs)} unique VMess configs.")

    async def check_server_alive(self, server_config_to_test: dict) -> tuple[bool, str]:
        server_name = server_config_to_test.get('ps', 'Unknown Server')
        self.log_to_widget(f"Testing: {server_name}...")
        xray_json_config = generate_xray_config(server_config_to_test)
        if not xray_json_config: return False, f"Failed to generate Xray config for {server_name}."
        if not self.check_xray_path(silent=True): return False, "Xray executable not ready for test."
        self.stop_xray() # Stop main Xray if running
        with open(TEST_XRAY_CONFIG_FILE, "w") as f: json.dump(xray_json_config, f, indent=2)
        xray_test_process = None
        try:
            xray_test_process = await asyncio.create_subprocess_exec(
                str(XRAY_PATH), "run", "-c", str(TEST_XRAY_CONFIG_FILE),
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
            await asyncio.sleep(2.5) # Increased wait time
            if xray_test_process.returncode is not None:
                stderr_output = await xray_test_process.stderr.read()
                err_msg = stderr_output.decode(errors='ignore').strip()[:150]
                return False, f"Xray failed for {server_name} test. Error: {err_msg}"
            
            TEST_URL = "http://www.gstatic.com/generate_204"; PROXY_ADDRESS = "127.0.0.1:10808"
            curl_cmd = f"curl -s --head --connect-timeout 7 --max-time 12 --proxy socks5h://{PROXY_ADDRESS} {TEST_URL}"
            curl_proc = await asyncio.create_subprocess_shell(curl_cmd,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            curl_stdout, curl_stderr = await curl_proc.communicate()
            is_success = False
            if curl_proc.returncode == 0:
                headers = curl_stdout.decode(errors='ignore')
                if any(status_ok in headers for status_ok in ["HTTP/1.1 204", "HTTP/2 204", "HTTP/1.0 204"]):
                    is_success = True
            
            if xray_test_process.returncode is None:
                try: xray_test_process.terminate(); await asyncio.wait_for(xray_test_process.wait(), 2.0)
                except: pass
            if TEST_XRAY_CONFIG_FILE.exists(): TEST_XRAY_CONFIG_FILE.unlink(missing_ok=True)
            
            if is_success: return True, f"SUCCESS: {server_name} is alive."
            else:
                curl_err = curl_stderr.decode(errors='ignore').strip()[:100]
                return False, f"FAIL: {server_name}. Curl_RC:{curl_proc.returncode}. CurlErr:{curl_err}"
        except Exception as e:
            if xray_test_process and xray_test_process.returncode is None:
                try: xray_test_process.terminate(); await xray_test_process.wait()
                except: pass
            if TEST_XRAY_CONFIG_FILE.exists(): TEST_XRAY_CONFIG_FILE.unlink(missing_ok=True)
            return False, f"Exception testing {server_name}: {e}"

    async def run_server_test_action(self, server_config_to_test: dict):
        if not server_config_to_test:
            await self.show_message_modal("No server config for testing."); return
        self.log_to_widget(f"Init test for {server_config_to_test.get('ps', 'Unknown')}...")
        is_alive, message = await self.check_server_alive(server_config_to_test)
        self.log_to_widget(message); await self.show_message_modal(message)

    def compose(self) -> ComposeResult:
        yield Header();
        with Vertical(id="main_layout"):
            with Horizontal(id="status_bar"):
                 yield Static("Xray status checking...", id="xray_path_status")
                 yield Static(self.active_log_message, id="active_log_display")
            yield Label("Subscriptions:", classes="section_header")
            yield VerticalScroll(id="subscriptions_list_container", classes="list_container")
            yield Label("Available Servers (VMess Only - Parsed):", classes="section_header")
            yield VerticalScroll(id="server_list_display_container", classes="list_container")
            yield Label("Log:", classes="section_header")
            yield Log(id="main_log", auto_scroll=True, max_lines=200)
        yield Footer()
        self.call_later(self.update_subscription_list_ui)
        self.call_later(self.update_server_list_ui)

    async def watch_subscriptions(self, _: list, new_subs: list) -> None: self.update_subscription_list_ui()
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
    
    async def watch_parsed_server_configs(self, _: list, new_configs: list) -> None: self.update_server_list_ui()
    def update_server_list_ui(self):
        container = self.query_one("#server_list_display_container")
        container.remove_children()
        if not self.parsed_server_configs:
            container.mount(Static("No servers. Update subs with 'u'.", classes="placeholder_text"))
        else:
            status_msg = f"{len(self.parsed_server_configs)} servers. Actions for first server below:"
            container.mount(Static(status_msg))
            for idx, config in enumerate(self.parsed_server_configs):
                ps = config.get("ps", f"S_{idx+1}"); addr = config.get("add", "N/A")
                net = config.get("net", "N/A"); tls = "TLS" if config.get("tls") == "tls" else "NoTLS"
                container.mount(Markdown(f"[{idx+1}] **{ps}** (`{addr}` | {net}/{tls})", classes="server_entry")) 
            if self.parsed_server_configs:
                first_conf = self.parsed_server_configs[0]; first_name = first_conf.get("ps", "First Server")
                connect_btn = Button(f"Connect: {first_name}", variant="success", id="connect_first_parsed_server_button")
                test_btn = Button(f"Test Alive: {first_name}", id="test_first_parsed_server_button")
                # Corrected: Pass buttons to Horizontal constructor
                btn_container = Horizontal(connect_btn, test_btn, classes="action_buttons_container")
                container.mount(btn_container)
    
    async def watch_active_log_message(self, _: str, new_log_msg: str) -> None:
        try:
            self.query_one("#active_log_display", Static).update(new_log_msg[:80]) 
        except Exception: pass 

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "connect_first_parsed_server_button":
            if self.parsed_server_configs:
                self.log_to_widget("Connect btn pressed for 1st parsed server.")
                first_config = self.parsed_server_configs[0]
                xray_json = generate_xray_config(first_config)
                if xray_json:
                    if self.start_xray(xray_json): await self.show_message_modal(f"Xray started with: '{first_config.get('ps')}'")
                    else: await self.show_message_modal("Failed to start Xray.")
                else: await self.show_message_modal("Could not generate Xray config.")
            else: await self.show_message_modal("No parsed servers to connect.")
        elif button_id == "test_first_parsed_server_button":
            if self.parsed_server_configs:
                first_config_to_test = self.parsed_server_configs[0]
                self.call_later(self.run_server_test_action, first_config_to_test)
            else: await self.show_message_modal("No parsed servers to test.")

    async def action_quit_app(self) -> None:
        self.log_to_widget("Quit requested. Stopping Xray..."); self.stop_xray()
        self.log_to_widget("Exiting application."); self.exit("User requested quit.")

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
.sub_entry { padding: 1 0; background: $boost; border-bottom: dashed $primary-background-darken-3; }
.server_entry { padding: 0 0 1 0; /* Reduced padding for server entry */ background: $boost; border-bottom: dashed $primary-background-darken-3; }
.action_buttons_container { padding-top:1; align: center middle; height: auto; }
.action_buttons_container Button { margin: 0 1; width: 1fr; } /* Make buttons take equal width */
#main_log { border: panel $primary-background-darken-2; height: 10; margin-top: 1; } /* Increased log height */
.placeholder_text { color: $text-muted; padding: 1; text-align: center; }
#add_sub_dialog, #message_dialog, #about_dialog {
    padding: 0 1; width: 80%; max-width: 60; height: auto;
    border: thick $secondary; background: $panel;
}
.modal_label { padding: 1 0; }
.modal_buttons { padding-top: 1; align-horizontal: right; }
.modal_buttons Button { margin-left: 1; }
.about_content { padding: 1 2; }
"""

if __name__ == "__main__":
    css_file_path_to_check = SCRIPT_DIR / VpnApp.CSS_PATH
    if not css_file_path_to_check.exists():
        with open(css_file_path_to_check, "w") as cf:
            cf.write(VPN_APP_CSS_FALLBACK)
            print(f"Created CSS file: {css_file_path_to_check} with fallback styles.")
    app = VpnApp()
    app.run()
