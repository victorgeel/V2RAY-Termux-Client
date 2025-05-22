
import os
import asyncio
import time
import base64
import requests
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from textual.app import App, ComposeResult
from textual.widgets import Static, Button, Log, Footer, Input, Markdown
from textual.containers import Vertical, Horizontal
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.binding import Binding
from textual.timer import Timer

SCRIPT_DIR = Path(__file__).resolve().parent
APP_TITLE = "Termux V2Ray/Xray - Developer VictorGeek Email frussel4@asu.edu"
APP_SUB_TITLE = "Manage & Auto-Test Connections"

class NeonHeader(Static):
    def on_mount(self):
        self.text = APP_TITLE + " | " + APP_SUB_TITLE
        self.index = 0
        self.timer: Timer = self.set_interval(0.1, self.update_text)

    def update_text(self):
        full_text = self.text + "   "
        shift_text = full_text[self.index:] + full_text[:self.index]
        self.update(f"[b bright_cyan]{shift_text}[/b bright_cyan]")
        self.index = (self.index + 1) % len(full_text)

class MessageScreen(ModalScreen):
    BINDINGS = [Binding("escape", "pop_screen", "OK", show=False)]
    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message
    def compose(self) -> ComposeResult:
        yield Vertical(Markdown(self.message), Button("OK", id="ok_button"))
    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss()

def get_subscription_content(url: str) -> list[str]:
    resp = requests.get(url, timeout=10)
    content = base64.b64decode(resp.content + b'===').decode('utf-8')
    return [line.strip() for line in content.strip().splitlines() if line.strip()]

def decode_vmess(link: str) -> dict:
    try:
        b64 = link[len("vmess://"):]
        decoded = base64.b64decode(b64 + '===').decode('utf-8')
        return {"protocol": "vmess", **eval(decoded)}
    except:
        return {"protocol": "vmess", "raw": link, "error": "Decode failed"}

def decode_vless_or_others(link: str) -> dict:
    try:
        parsed = urlparse(link)
        query = parse_qs(parsed.query)
        return {
            "protocol": parsed.scheme,
            "user": parsed.username,
            "server": parsed.hostname,
            "port": parsed.port,
            "params": {k: v[0] for k, v in query.items()},
            "raw": link
        }
    except:
        return {"protocol": "unknown", "raw": link, "error": "Parse failed"}

def parse_link(link: str) -> dict:
    if link.startswith("vmess://"):
        return decode_vmess(link)
    elif any(link.startswith(p + "://") for p in ["vless", "trojan", "ss", "hysteria", "socks", "tuic", "reality"]):
        return decode_vless_or_others(link)
    else:
        return {"protocol": "unknown", "raw": link}

class VpnApp(App[None]):
    TITLE = APP_TITLE
    SUB_TITLE = APP_SUB_TITLE

    BINDINGS = [
        Binding("q", "quit_app", "Quit"),
        Binding("f1", "show_help", "Help"),
        Binding("a", "auto_connect", "Fast Connect"),
        Binding("s", "decode_sub", "Decode Sub")
    ]

    def compose(self) -> ComposeResult:
        yield NeonHeader()
        with Vertical():
            yield Horizontal(Static("Log:"), id="log_header")
            yield Log(id="main_log", auto_scroll=True)
        yield Footer()

    def log_to_widget(self, message: str, is_error: bool = False):
        try:
            log_w = self.query_one("#main_log", Log)
            time_str = time.strftime("%H:%M:%S")
            color = "red" if is_error else "green"
            log_w.write_line(f"[{time_str}] [{color}]{message}[/{color}]")
        except: pass

    async def on_mount(self):
        self.log_to_widget("VPN Client UI started.")

    async def action_show_help(self):
        await self.push_screen(MessageScreen("Help Menu:\n- [q] Quit\n- [a] Fast Connect\n- [f1] Help\n- [s] Decode Subscription"))

    async def action_quit_app(self) -> None:
        self.exit()

    async def action_auto_connect(self):
        self.log_to_widget("Smart Connect mock triggered.")
        await self.push_screen(MessageScreen("Mock: Connected to best server (not implemented)."))

    async def action_decode_sub(self):
        import sys
        if sys.stdin.isatty():
            sub_url = input("Enter subscription URL: ").strip()
        else:
            sub_url = "https://example.com/sub.txt"
        self.log_to_widget("Decoding subscription link...")
        try:
            links = get_subscription_content(sub_url)
            results = [parse_link(link) for link in links]
            output = "\n".join(f"{i+1}. {r.get('protocol', '?')} - {r.get('server') or r.get('raw')}" for i, r in enumerate(results[:10]))
            await self.push_screen(MessageScreen("Top Decoded Nodes:\n" + output))
        except Exception as e:
            self.log_to_widget(f"Error decoding: {e}", is_error=True)

if __name__ == "__main__":
    VpnApp().run()
