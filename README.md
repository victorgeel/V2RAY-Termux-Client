<div align="center">
  <h1>🐥 Termux V2Ray/Xray Client 🐥</h1>
  <p>
    <strong>Termux အတွက် ရိုးရှင်းပြီး အသုံးပြုရလွယ်ကူသော V2Ray/Xray client (TUI)</strong><br />
    <em>A simple and easy-to-use V2Ray/Xray client (TUI) for Termux.</em>
  </p>
  <p>
    <img src="https://img.shields.io/badge/Python-3.9+-blue.svg?style=flat-square&logo=python&logoColor=white" alt="Python 3.9+">
    <img src="https://img.shields.io/badge/Made%20for-Termux-lightgrey.svg?style=flat-square&logo=android&logoColor=white" alt="Made for Termux">
    <img src="https://img.shields.io/badge/License-MIT-green.svg?style=flat-square" alt="License: MIT">
  </p>
</div>

---

<details>
<summary><strong>English Version</strong> (Click to expand)</summary>

## Termux V2Ray/Xray Client (TUI)

A simple Textual User Interface (TUI) application for Termux to manage V2Ray/Xray connections using subscriptions. It allows you to add subscription links, fetch server configurations, automatically test their connectivity and latency, and connect to the best available server.

### Features

* **Subscription Management**: Add and update V2Ray/Xray subscription links.
* **Automatic Server Testing**:
    * Fetches server configurations from subscriptions.
    * Automatically tests each server for connectivity and latency (ping).
    * Displays only active servers, sorted by the lowest latency.
* **Connection Management**:
    * Start and stop Xray connection using the selected active server.
    * SOCKS5 proxy on `127.0.0.1:10808` and HTTP proxy on `127.0.0.1:10809`.
* **Xray Core Auto-Setup**:
    * Checks for the Xray executable in the script's directory.
    * If not found, attempts to download and set up the appropriate Xray core for your Termux architecture.
* **User-Friendly TUI**: Built with [Textual](https://github.com/Textualize/textual) for an easy-to-navigate terminal interface.
* **About Section**: Displays application and developer information.

### Requirements

* Termux environment.
* Python 3.9 or higher.
* `curl` installed in Termux (usually available by default: `pkg install curl`).
* An active internet connection for downloading subscriptions, Xray core, and testing servers.

### Installation & Usage

1.  **Clone the Repository:**
    ```bash
    git clone https://github.com/victorgeel/V2RAY-Termux-Client
    cd V2RAY-Termux-Client 
    ```


2.  **Xray Core:**
    * The script will attempt to download and set up the Xray core automatically if it's not found in the `V2RAY-Termux-Client` directory.
    * **Manual Setup (if needed):**
        1.  Download the appropriate Xray core for your Termux (e.g., `linux-arm64-v8a` or `linux-arm32-v7a`) from [Xray-core Releases](https://github.com/XTLS/Xray-core/releases).
        2.  Extract the archive and copy the `xray` executable to the `V2RAY-Termux-Client` directory.
        3.  Make it executable: `chmod +x xray`

3.  **Run the Client:**
    ```bash
    python vpn.py
    ```

4.  **Basic Controls:**
    * `a`: Add a new subscription URL.
    * `u`: Update all subscriptions and automatically test all servers.
    * `s`: Stop the current Xray connection.
    * `c`: Check Xray executable status (and attempt setup if missing).
    * `F1`: Show the About screen.
    * `q`: Quit the application.
    * Use arrow keys for navigation within lists if scrollable.

### Disclaimer

This tool is provided for educational and personal use. Please ensure your use complies with your local laws and regulations, and the terms of service of any networks or services you access.

---
_Developed by: Victor Geek (frussel4@asu.edu)_

</details>

<details>
<summary><strong>မြန်မာဘာသာဖြင့်ဖော်ပြချက်</strong> (နှိပ်၍ကြည့်ပါ)</summary>

## Termux V2Ray/Xray Client (TUI)

Termux ပေါ်တွင် V2Ray/Xray subscription link များကို အသုံးပြု၍ connection များကို စီမံခန့်ခွဲနိုင်ရန် ရိုးရှင်းစွာရေးသားထားသော Textual User Interface (TUI) application ဖြစ်ပါသည်။ Subscription link များထည့်ခြင်း၊ server configuration များရယူခြင်း၊ server တစ်ခုချင်းစီ၏ connectivity နှင့် latency (ping) ကို အလိုအလျောက်စမ်းသပ်ပေးခြင်း၊ နှင့် အကောင်းဆုံး server ကို ရွေးချယ်ချိတ်ဆက်ခြင်းတို့ကို ပြုလုပ်နိုင်ပါသည်။

### အဓိကလုပ်ဆောင်ချက်များ

* **Subscription စီမံခန့်ခွဲမှု**: V2Ray/Xray subscription link များထည့်ခြင်း၊ update လုပ်ခြင်း။
* **Server များကို အလိုအလျောက် စမ်းသပ်ခြင်း**:
    * Subscription များမှ server configuration များကို ရယူပေးသည်။
    * Server တစ်ခုချင်းစီ၏ ချိတ်ဆက်နိုင်စွမ်း (connectivity) နှင့် latency (ping) ကို အလိုအလျောက် စမ်းသပ်ပေးသည်။
    * Active ဖြစ်သော server များကိုသာ latency အနည်းဆုံးမှ စီ၍ ပြသပေးသည်။
* **Connection စီမံခန့်ခွဲမှု**:
    * ရွေးချယ်ထားသော active server ကို အသုံးပြု၍ Xray connection ကို စတင်ခြင်း၊ ရပ်တန့်ခြင်း။
    * SOCKS5 proxy ကို `127.0.0.1:10808` တွင် နှင့် HTTP proxy ကို `127.0.0.1:10809` တွင် ရရှိနိုင်မည်။
* **Xray Core အလိုအလျောက် ထည့်သွင်းမှု**:
    * Script run သည့် directory ထဲတွင် `xray` executable ရှိမရှိ စစ်ဆေးသည်။
    * မရှိပါက၊ သင်၏ Termux architecture နှင့်ကိုက်ညီသော Xray core ကို အလိုအလျောက် download လုပ်ပြီး ထည့်သွင်းရန် ကြိုးစားပေးသည်။
* **အသုံးပြုရလွယ်ကူသော TUI**: [Textual](https://github.com/Textualize/textual) library ကို အသုံးပြု၍ Terminal ထဲတွင် လွယ်ကူစွာ ထိန်းချုပ်နိုင်သော interface ကို တည်ဆောက်ထားသည်။
* **About ကဏ္ဍ**: Application နှင့် developer အကြောင်းအရာများကို ပြသပေးသည်။

### လိုအပ်ချက်များ

* Termux environment.
* Python 3.9 နှင့်အထက်။
* Termux တွင် `curl` ထည့်သွင်းထားရန် (ပုံမှန်အားဖြင့် `pkg install curl` ဖြင့်ရနိုင်သည်)။
* Subscription များ၊ Xray core download လုပ်ရန် နှင့် server များစမ်းသပ်ရန် အင်တာနက် connection လိုအပ်သည်။

### Install လုပ်ခြင်း နှင့် အသုံးပြုပုံ

၁။ **Repository ကို Clone ဆွဲပါ:**
    ```bash
    git clone https://github.com/victorgeel/V2RAY-Termux-Client
    cd V2RAY-Termux-Client
    ```
  

၂။ **Xray Core ထည့်သွင်းခြင်း:**
    * Script run သည့် `V2RAY-Termux-Client` directory ထဲတွင် `xray` executable မရှိပါက script မှ အလိုအလျောက် download လုပ်ပြီး ထည့်သွင်းရန် ကြိုးစားပါမည်။
    * **လိုအပ်ပါက Manual ထည့်သွင်းနည်း:**
        ၁။ သင်၏ Termux နှင့်ကိုက်ညီသော Xray core (ဥပမာ `linux-arm64-v8a` သို့မဟုတ် `linux-arm32-v7a`) ကို [Xray-core Releases](https://github.com/XTLS/Xray-core/releases) မှ download ဆွဲပါ။
        ၂။ Download ဆွဲထားသော zip ဖိုင်ကိုဖြည်ပြီး `xray` ဟုအမည်ရသော executable ဖိုင်ကို `V2RAY-Termux-Client` directory ထဲသို့ copy ကူးထည့်ပါ။
        ၃။ Executable ဖြစ်အောင် permission ပေးပါ: `chmod +x xray`

၃။ **Client ကို Run ပါ:**
    ```bash
    python vpn.py
    ```

၄။ **အခြေခံထိန်းချုပ်မှုများ:**
    * `a`: Subscription URL အသစ်ထည့်ရန်။
    * `u`: Subscription အားလုံးကို update လုပ်ပြီး server အားလုံးကို အလိုအလျောက် test လုပ်ရန်။
    * `s`: လက်ရှိ Xray connection ကို ရပ်တန့်ရန်။
    * `c`: Xray executable program ၏ အခြေအနေကိုစစ်ဆေးရန် (မရှိပါက ထည့်သွင်းရန်ကြိုးစားမည်)။
    * `F1`: About screen ကိုပြရန်။
    * `q`: Application မှထွက်ရန်။
    * Scroll လုပ်နိုင်သော list များတွင် arrow key များသုံး၍ အပေါ်အောက်ရွှေ့ပါ။

### သတိပြုရန်

ဤ tool ကို ပညာရေးဆိုင်ရာ နှင့် ကိုယ်ပိုင်အသုံးပြုမှုအတွက်သာ ရည်ရွယ်ပါသည်။ သင်၏ အသုံးပြုမှုသည် သင်อยู่ထိုင်ရာ ဒေသ၏ ဥပဒေများ၊ စည်းမျဉ်းစည်းကမ်းများနှင့် သင်အသုံးပြုသော network သို့မဟုတ် service များ၏ သတ်မှတ်ချက်များနှင့် ကိုက်ညီမှုရှိစေရန် သေချာဂရုပြုပါ။

---
_ရေးသားသူ: Victor Geek (frussel4@asu.edu)_

</details>
