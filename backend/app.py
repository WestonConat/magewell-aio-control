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
from .magewell_settings import get_modified_settings


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
