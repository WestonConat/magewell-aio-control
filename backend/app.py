import csv
import hashlib
import asyncio
import ipaddress
import aiohttp
import socket
import logging
import io
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, Query, UploadFile, File
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
from yarl import URL

app = FastAPI()

origins = [
    "http://localhost:3000",  # Adjust if your Next.js dev server runs on a different port/host
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,      # Allow these origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Utility Functions ---

def get_local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip

def get_local_subnet(prefix_length: int = 23) -> str:
    local_ip = get_local_ip()
    network = ipaddress.ip_network(f"{local_ip}/{prefix_length}", strict=False)
    return str(network)

LOCAL_SUBNET = get_local_subnet(23)

def md5_hash(password: str) -> str:
    return hashlib.md5(password.encode('utf-8')).hexdigest()

def get_modified_settings(magewell_id: str) -> dict:
    return {
        "is-low-latency": 0,
        "is-auto-send-file": 0,
        "is-auto-del-file": 0,
        "is-check-update": 0,
        "audio-sync-offset": 0,
        "enable-advanced-pcr": 0,
        "udp-mtu": 1496,
        "cloud-num": 2,
        "enable-ndi-hx3": 0,
        "enable-4k60-input": 0,
        "enable-usb-audio-capture": 1,
        "net-prior": 1,
        "input-source": {
            "source": 2,
            "mixer": {
                "input-device": 2,
                "is-hdmi-top": 0,
                "type": 0,
                "location": 2
            }
        },
        "use-nosignal-file": 1,
        "nosignal-files": [
            {"id": 0, "is-use": 0, "is-edit": 0, "file-path": "/no-signal/default0.jpg", "time": 0},
            {"id": 1, "is-use": 0, "is-edit": 0, "file-path": "/no-signal/default1.jpg", "time": 0},
            {"id": 2, "is-use": 1, "is-edit": 1, "file-path": "/no-signal/default2.jpg", "time": 17149641665160202}
        ],
        "video-input-format": {
            "hdmi": {"is-color-fmt": 0, "color-fmt": 1, "is-quant-range": 0, "quant-range": 1},
            "sdi": {"is-color-fmt": 0, "color-fmt": 1, "is-quant-range": 0, "quant-range": 1}
        },
        "video-output-format": {
            "hdmi": {"is-color-fmt": 0, "color-fmt": 3, "is-quant-range": 0, "quant-range": 2, "is-sat-range": 0, "sat-range": 2},
            "sdi": {"is-color-fmt": 0, "color-fmt": 3, "is-quant-range": 0, "quant-range": 2, "is-sat-range": 0, "sat-range": 2}
        },
        "video-color": {
            "hdmi": {"contrast": 100, "brightness": 0, "saturation": 100, "hue": 0},
            "sdi": {"contrast": 100, "brightness": 0, "saturation": 100, "hue": 0}
        },
        "volume": {
            "is-spi": 1,
            "spi-gain": 0,
            "is-linein": 1,
            "linein-gain": 0,
            "is-lineout": 1,
            "lineout-gain": 0,
            "enable-mic-bias": 0
        },
        "audio-mixer": {"enable-spi-mix": 0, "enable-lineout-mix": 1},
        "enable-deinterlace": 0,
        "deinterlace-mode": 1,
        "3d-output": {"enable": 0, "mode": 1},
        "main-stream": {
            "is-auto": 0,
            "codec": 1,
            "cx": 3840,
            "cy": 2160,
            "duration": 333333,
            "kbps": 25600,
            "gop": 60,
            "fourcc": 0,
            "profile": 0,
            "cbrstat": 60,
            "fullrange": 0,
            "is-vbr": 1,
            "min-vbr-qp": 12,
            "max-vbr-qp": 36,
            "is-time-code-sei": 0,
            "is-closed-caption-sei": 0,
            "ar-convert-mode": 2,
            "rotation": 0,
            "mirroring": 0,
            "crop": {
                "is-use": 0,
                "effect": {"x-offset": 0, "y-offset": 0, "act-w": 3840, "act-h": 2160},
                "crop": {"x-offset": 0, "y-offset": 0, "act-w": 0, "act-h": 0}
            }
        },
        "sub-stream": {
            "enable": 1,
            "codec": 1,
            "cx": 1280,
            "cy": 720,
            "duration": 333667,
            "kbps": 2048,
            "gop": 60,
            "fourcc": 0,
            "profile": 0,
            "cbrstat": 60,
            "fullrange": 0,
            "is-vbr": 0,
            "min-vbr-qp": 0,
            "max-vbr-qp": 0,
            "is-time-code-sei": 0,
            "is-closed-caption-sei": 0,
            "ar-convert-mode": 2,
            "rotation": 0,
            "mirroring": 0,
            "crop": {
                "is-use": 0,
                "effect": {"x-offset": 0, "y-offset": 0, "act-w": 1280, "act-h": 720},
                "crop": {"x-offset": 0, "y-offset": 0, "act-w": 0, "act-h": 0}
            }
        },
        "channel-mask": 255,
        "audio-stream-count": 1,
        "audio-streams": [
            {"sample-rate": 48000, "channels": 2, "kbps": 192, "ch0": 0, "ch1": 1, "ch2": 2, "ch3": 3, "ch4": 4, "ch5": 5, "ch6": 6, "ch7": 7, "use-lfe": 0}
        ],
        "eth": {"is-dhcp": 1, "ip": "", "mask": "", "router": "", "dns": ""},
        "enable-station": 1,
        "wifi": [
            {"name": "Sector 2024", "passwd": "c2VjdG9yMjAyNA==", "identity": "", "freq": 0, "level": 0, "secu": 3, "is-auto": 1, "is-use": 0, "is-hide": 0, "is-dhcp": 1, "ip": "", "mask": "", "router": "", "dns": ""},
            {"name": "BLACKHATEUROPE2024", "passwd": "QkhFVVJPUEUyMDI0", "identity": "", "freq": 0, "level": 0, "secu": 3, "is-auto": 1, "is-use": 0, "is-hide": 0, "is-dhcp": 1, "ip": "", "mask": "", "router": "", "dns": ""}
        ],
        "softap": {"is-softap": 0, "is-visible": 1, "softap-ssid": "B313231201201", "softap-passwd": "31201201"},
        "rndis": {"ip": "192.168.66.1", "mask": "255.255.255.0"},
        "stream-server": [
            {"id": 0, "type": 121, "name": "SRT Listener", "is-use": 1, "port": 8000, "max-connections": 1, "latency": 200, "bandwidth": 25, "net-mode": 0, "stream-index": 1, "aes": 0, "aes-word": "", "mtu": 1496, "audio": 0, "audio-streams": 1, "is-media-hub": 0}
        ],
        "rec-channels": [
            {
                "id": 0, "type": 0, "is-use": 1, "stream-index": 0, "mode": 0, 
                "dir-name": f"{magewell_id}_REC_Folder", 
                "file-prefix": 0, 
                "prefix-name": f"{magewell_id}_", 
                "file-suffix": 0, 
                "time-unit": 10, "audio": 0
            },
            {
                "id": 1, "type": 1, "is-use": 0, "stream-index": 0, "mode": 0, 
                "dir-name": magewell_id, 
                "file-prefix": 0, 
                "prefix-name": magewell_id, 
                "file-suffix": 0, 
                "time-unit": 90, "audio": 0
            },
            {
                "id": 2, "type": 2, "is-use": 0, "stream-index": 0, "mode": 0, 
                "dir-name": "REC_Folder", 
                "file-prefix": 0, 
                "prefix-name": "VID", 
                "file-suffix": 0, 
                "time-unit": 30, "audio": 0
            }
         ],
        "nas": [],
        "send-file-cloud": [],
        "schedulers": [],
        "image": [
            {"id": 0, "name": "", "type": 1, "path": "/surface-image/image0.png", "time": 17091101447340797, "cx": 401, "cy": 50}
        ],
        "surface": {"main-surface": 0, "second-surface": 0, "surfaces": []},
        "web": {"is-http": 1, "http-port": 80, "is-https": 0, "https-port": 443, "is-cert-valid": 0, "is-cert-key-valid": 0, "theme": 0},
        "rec": {"is-auto": 0, "trigger-mode": 0},
        "living": {
            "ts": {"mtu": 1496},
            "hls-push": {"seg-count": 3, "seg-duration": 3},
            "ndi-find": {"group-name": "Public", "extra-ips": "", "enable-discovery": 0, "discovery-server": ""}
        },
        "date-time": {"timezone": "America/Los_Angeles", "is-auto": 1, "ntp-server": "0.pool.ntp.org", "ntp-server-backup": "1.pool.ntp.org"},
        "lcd-control": {"no-touch": 0, "page-idx": 1, "no-flip": 0, "duration": 666667}
    }

# --- Retry-Wrapped API Calls ---

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2), retry=retry_if_exception_type(aiohttp.ClientError))
async def login_device(session: aiohttp.ClientSession, magewell_ip: str, username: str, hashed_password: str, magewell_id: str) -> str:
    login_url = f"http://{magewell_ip}/usapi?method=login&id={username}&pass={hashed_password}"
    async with session.get(login_url) as login_response:
        login_response.raise_for_status()
        login_data = await login_response.json()
        logger.info(f"Login successful for device {magewell_id}. Received JSON: {login_data}")

        # Manually construct the Cookie header from the login response
        cookie_header = "; ".join(
            f"{name}={cookie.value}" for name, cookie in login_response.cookies.items()
        )
        logger.info(f"Constructed Cookie header for device {magewell_id}: {cookie_header}")
        return cookie_header

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2), retry=retry_if_exception_type(aiohttp.ClientError))
async def import_settings_call(session: aiohttp.ClientSession, magewell_ip: str, modified_settings: dict, cookie_header: str, magewell_id: str):
    import_url = f"http://{magewell_ip}/usapi?method=import-settings"
    headers = {"Cookie": cookie_header}
    async with session.post(import_url, json=modified_settings, headers=headers) as import_response:
        import_response.raise_for_status()
        result = await import_response.json()
        logger.info(f"Settings imported successfully for device {magewell_id}. Response: {result}")
        return result

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2), retry=retry_if_exception_type(aiohttp.ClientError))
async def get_device_settings_with_login(session: aiohttp.ClientSession, magewell_ip: str, timeout: float = 2.0) -> dict:
    """
    Login to the device and then retrieve its settings.
    """
    username = "Admin"
    plaintext_password = "bl4z35"
    hashed_password = md5_hash(plaintext_password)
    try:
        # Login to get the auth cookie
        cookie_header = await login_device(session, magewell_ip, username, hashed_password, magewell_ip)
    except Exception as e:
        logger.error(f"Login failed for {magewell_ip} when fetching settings: {e}")
        return {}
    
    # Now call the get-settings endpoint with the auth cookie.
    url = f"http://{magewell_ip}/usapi?method=get-settings"
    headers = {
        "Accept": "application/json",
        "User-Agent": "curl/7.68.0",
        "Cookie": cookie_header,
    }
    try:
        # First, await the GET request with a timeout.
        const_response = await asyncio.wait_for(
            session.get(url, timeout=timeout, headers=headers, allow_redirects=False),
            timeout=timeout
        )
        # Then, use the response as an async context manager.
        async with const_response as response:
            response.raise_for_status()
            data = await response.json()
            logger.info(f"Got settings from {magewell_ip}: {data}")
            return data
    except Exception as e:
        logger.error(f"Error fetching settings for {magewell_ip}: {e}")
        return {}


# --- Device Discovery Functions ---

async def ping_magewell(session: aiohttp.ClientSession, ip: str, per_ip_timeout: float = 1.0) -> bool:
    url = f"http://{ip}/usapi?method=ping"
    headers = {"Accept": "application/json", "User-Agent": "curl/7.68.0"}
    try:
        response = await asyncio.wait_for(
            session.get(url, timeout=per_ip_timeout, headers=headers, allow_redirects=False),
            timeout=per_ip_timeout
        )
        status = response.status
        text = await response.text()
        logger.info(f"Ping response from {ip} - Status: {status}, Body: {text}")

        try:
            data = await response.json()
        except Exception as json_err:
            logger.error(f"Failed to parse JSON from {ip}: {repr(json_err)}")
            return False

        logger.info(f"Parsed JSON from {ip}: {data}")
        result = data.get("result")
        return result == 0 or result == "0"
    except Exception as e:
        logger.error(f"Error pinging {ip}: {repr(e)}")
        return False

async def sem_ping(sem: asyncio.Semaphore, session: aiohttp.ClientSession, ip: str, timeout: float) -> bool:
    async with sem:
        return await ping_magewell(session, ip, timeout)
    
# --- Device Processing Functions ---

async def process_device(row: dict, session: aiohttp.ClientSession):
    magewell_id = row["Magewell ID"]
    magewell_ip = row["Magewell IP"]
    logger.info(f"Processing device {magewell_id} at {magewell_ip}")

    username = "Admin"
    plaintext_password = "bl4z35"
    hashed_password = md5_hash(plaintext_password)

    try:
        cookie_header = await login_device(session, magewell_ip, username, hashed_password, magewell_id)
    except Exception as e:
        logger.error(f"Login failed for device {magewell_id}: {e}")
        return

    modified_settings = get_modified_settings(magewell_id)
    try:
        await import_settings_call(session, magewell_ip, modified_settings, cookie_header, magewell_id)
    except Exception as e:
        logger.error(f"Import-settings failed for device {magewell_id}: {e}")

async def limited_process_device(row: dict, session: aiohttp.ClientSession, sem: asyncio.Semaphore):
    async with sem:
        await process_device(row, session)

async def run_bulk_update(devices: list):
    max_concurrent = 10
    sem = asyncio.Semaphore(max_concurrent)
    async with aiohttp.ClientSession() as session:
        tasks = [asyncio.create_task(limited_process_device(row, session, sem)) for row in devices]
        await asyncio.gather(*tasks)

# --- FastAPI Endpoints ---

@app.post("/bulk-update")
async def bulk_update(file: UploadFile = File(...)):
    content = await file.read()
    csv_file = io.StringIO(content.decode("utf-8"))
    reader = csv.DictReader(csv_file)
    devices = [row for row in reader]
    asyncio.create_task(run_bulk_update(devices))
    return {"message": "Bulk update started. Check logs for progress."}

@app.get("/discover-magewell")
async def discover_magewell(
    subnet: str = Query("172.16.6.0/23", description="Subnet to scan, e.g., 172.16.6.0/23"),
    per_ip_timeout: float = Query(1.0, description="Timeout for each ping request"),
    max_concurrent: int = Query(50, description="Max concurrent ping tasks"),
    settings_timeout: float = Query(2.0, description="Timeout for each get-settings request")
):
    try:
        network = ipaddress.ip_network(subnet, strict=False)
    except Exception as e:
        return {"error": f"Invalid subnet: {subnet}"}

    ips = list(network.hosts())
    connector = aiohttp.TCPConnector(ssl=False, family=socket.AF_INET)
    sem = asyncio.Semaphore(max_concurrent)
    
    async with aiohttp.ClientSession(connector=connector) as session:
        ping_tasks = [sem_ping(sem, session, str(ip), per_ip_timeout) for ip in ips]
        ping_results = await asyncio.gather(*ping_tasks, return_exceptions=True)
        magewell_ips = [str(ip) for ip, is_magewell in zip(ips, ping_results) if is_magewell is True]
        logger.info(f"Discovered Magewell devices: {magewell_ips}")

        settings_tasks = [get_device_settings_with_login(session, ip, settings_timeout) for ip in magewell_ips]
        settings_results = await asyncio.gather(*settings_tasks, return_exceptions=True)

    devices = []
    for ip, settings in zip(magewell_ips, settings_results):
        if isinstance(settings, Exception):
            logger.error(f"Exception fetching settings for {ip}: {repr(settings)}")
            device_name = ""
        elif isinstance(settings, dict):
            device_name = settings.get("name", "")
        else:
            device_name = ""
        devices.append({"ip": ip, "name": device_name})
    
    return {"devices": devices}

@app.get("/local-subnet")
async def local_subnet():
    return {"local_subnet": LOCAL_SUBNET}
