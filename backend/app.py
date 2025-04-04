import csv
import os
import json
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
from bs4 import BeautifulSoup
from .magewell_settings import get_modified_settings
from .settings_merge import get_bulk_update_settings

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Utility Functions ---

def get_local_ip() -> str:
    """Determine the local IP address using an environment variable, DNS, or socket fallback."""
    host_ip = os.environ.get("LOCAL_HOST_IP")
    if host_ip:
        return host_ip
    try:
        return socket.gethostbyname("host.docker.internal")
    except socket.gaierror:
        # Fallback: use UDP socket to determine local IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('8.8.8.8', 80))
            return s.getsockname()[0]
        except Exception:
            return '127.0.0.1'
        finally:
            s.close()

def get_allowed_subnet(default_prefix: int = 23) -> str:
    """
    Returns the allowed subnet in CIDR notation.
    
    If ALLOWED_SUBNET is provided as an environment variable (e.g. "172.16.6.0/23"),
    it is used directly. Otherwise, it constructs a CIDR using the local IP
    (determined by get_local_ip()) and the default prefix.
    """
    allowed_subnet = os.environ.get("ALLOWED_SUBNET")
    if not allowed_subnet:
        local_ip = get_local_ip()
        allowed_subnet = f"{local_ip}/{default_prefix}"
        logger.info(f"No ALLOWED_SUBNET set; using computed local subnet: {allowed_subnet}")
    else:
        logger.info(f"Using ALLOWED_SUBNET environment variable: {allowed_subnet}")
    return allowed_subnet

def cidr_to_regex(cidr: str) -> str:
    """
    Convert a CIDR (e.g. '172.16.6.0/23') into a regex that matches any IP in that network.
    Supports /16, /23, and /24.
    """
    network = ipaddress.ip_network(cidr)
    if network.prefixlen == 24:
        A, B, C, _ = str(network.network_address).split(".")
        return f"{A}\\.{B}\\.{C}\\.(\\d{{1,3}})(:\\d+)?"
    elif network.prefixlen == 23:
        A, B, C, _ = str(network.network_address).split(".")
        allowed_third = f"({C}|{int(C)+1})"
        return f"{A}\\.{B}\\.{allowed_third}\\.(\\d{{1,3}})(:\\d+)?"
    elif network.prefixlen == 16:
        A, B, _, _ = str(network.network_address).split(".")
        return f"{A}\\.{B}\\.(\\d{{1,3}})\\.(\\d{{1,3}})(:\\d+)?"
    else:
        raise ValueError(f"CIDR mask /{network.prefixlen} not supported by this function")

def get_allowed_origin_regex(default_prefix: int = 23) -> str:
    """
    Build and return a composite regex for allowed origins.
    
    It uses ALLOWED_SUBNET if provided; otherwise, it calculates the local subnet using get_local_ip()
    and the default prefix. The resulting CIDR is converted to a regex via cidr_to_regex and combined
    with a localhost pattern.
    """
    allowed_subnet = get_allowed_subnet(default_prefix)
    try:
        subnet_regex = cidr_to_regex(allowed_subnet)
    except ValueError as e:
        raise ValueError(f"Error processing allowed subnet: {e}")
    # Composite regex allowing either localhost (with optional port) or an IP in the subnet.
    composite_regex = f"^http://(localhost(:\\d+)?|{subnet_regex})$"
    return composite_regex

# Get the composite regex to be used by CORSMiddleware.
allowed_origin_regex = get_allowed_origin_regex()

# --- FastAPI App Setup ---
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=allowed_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
async def get_device_report_with_login(session: aiohttp.ClientSession, magewell_ip: str, timeout: float = 2.0) -> dict:
    """
    Login to the device and then retrieve its report using get-report.
    Parses the returned HTML to extract the SETTINGS section JSON,
    and returns that JSON as a dict.
    """
    username = "Admin"
    plaintext_password = "bl4z35"
    hashed_password = md5_hash(plaintext_password)
    try:
        cookie_header = await login_device(session, magewell_ip, username, hashed_password, magewell_ip)
    except Exception as e:
        logger.error(f"Login failed for {magewell_ip} when fetching report: {e}")
        return {}
    
    url = f"http://{magewell_ip}/usapi?method=get-report"
    headers = {
        "Accept": "text/html",
        "User-Agent": "curl/7.68.0",
        "Cookie": cookie_header,
    }
    try:
        const_response = await asyncio.wait_for(
            session.get(url, timeout=timeout, headers=headers, allow_redirects=False),
            timeout=timeout
        )
        async with const_response as response:
            response.raise_for_status()
            html = await response.text()
            logger.info(f"Got report from {magewell_ip}")
            soup = BeautifulSoup(html, "html.parser")
            # Look for the report-content div and then find the content-level1 div with h2 == "SETTINGS"
            report_content = soup.find("div", class_="report-content")
            if not report_content:
                logger.error(f"No report-content found for {magewell_ip}")
                return {}
            settings_div = None
            for div in report_content.find_all("div", class_="content-level1"):
                h2 = div.find("h2")
                if h2 and h2.get_text(strip=True).upper() == "SETTINGS":
                    settings_div = div
                    break
            if not settings_div:
                logger.error(f"No SETTINGS section found for {magewell_ip}")
                return {}
            pre = settings_div.find("pre", class_="json")
            if not pre:
                logger.error(f"No JSON pre tag found in SETTINGS for {magewell_ip}")
                return {}
            settings_json = pre.get_text(strip=True)
            try:
                settings_data = json.loads(settings_json)
            except Exception as json_err:
                logger.error(f"Error parsing JSON in SETTINGS for {magewell_ip}: {json_err}")
                return {}
            return settings_data
    except Exception as e:
        logger.error(f"Error fetching report for {magewell_ip}: {e}")
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

    # Instead of directly calling get_modified_settings, we merge control settings if available.
    control_settings = getattr(app.state, "control_settings", None)
    if control_settings:
        # Use the current device's magewell_id to build settings while merging in the control device's settings.
        modified_settings = get_bulk_update_settings(magewell_id, control_settings)
        logger.info(f"Using merged control settings for device {magewell_id}: {modified_settings}")
    else:
        modified_settings = get_modified_settings(magewell_id)
        logger.info(f"Using default settings for device {magewell_id}: {modified_settings}")
    
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



def update_control_settings(magewell_id: str, control_settings: dict) -> dict:
    """
    Get the default settings for the given magewell_id (from magewell_settings.py)
    and overwrite its keys with those from control_settings.
    Returns the merged settings.
    """
    default_settings = get_modified_settings(magewell_id)
    # A shallow merge: keys in control_settings override those in default_settings.
    merged_settings = {**default_settings, **control_settings}
    return merged_settings

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
    rescan: bool = Query(False, description="Force a new scan"),
    per_ip_timeout: float = Query(1.0, description="Timeout for each ping request"),
    max_concurrent: int = Query(50, description="Max concurrent ping tasks"),
    settings_timeout: float = Query(2.0, description="Timeout for each get-report request")
):
    # If not rescan and devices are cached, return the cached devices.
    if not rescan and hasattr(app.state, "devices") and app.state.devices:
        return {"devices": app.state.devices}

    try:
        network = ipaddress.ip_network(subnet, strict=False)
    except Exception as e:
        return {"error": f"Invalid subnet: {subnet}"}

    ips = list(network.hosts())
    connector = aiohttp.TCPConnector(ssl=False, family=socket.AF_INET)
    sem = asyncio.Semaphore(max_concurrent)
    
    async with aiohttp.ClientSession(connector=connector) as session:
        # Discover devices using ping
        ping_tasks = [sem_ping(sem, session, str(ip), per_ip_timeout) for ip in ips]
        ping_results = await asyncio.gather(*ping_tasks, return_exceptions=True)
        magewell_ips = [str(ip) for ip, is_magewell in zip(ips, ping_results) if is_magewell is True]
        logger.info(f"Discovered Magewell devices: {magewell_ips}")

        # For each discovered device, retrieve the report via get-report (which contains SETTINGS).
        report_tasks = [get_device_report_with_login(session, ip, settings_timeout) for ip in magewell_ips]
        report_results = await asyncio.gather(*report_tasks, return_exceptions=True)

    devices = []
    for ip, report in zip(magewell_ips, report_results):
        if isinstance(report, Exception):
            logger.error(f"Exception fetching report for {ip}: {repr(report)}")
            device_name = ""
            settings_dict = {}
        elif isinstance(report, dict):
            device_name = report.get("name", "")
            settings_dict = report  # Store the entire settings dictionary.
        else:
            device_name = ""
            settings_dict = {}
        devices.append({"ip": ip, "name": device_name, "settings": settings_dict})
    
    # Cache discovered devices
    app.state.devices = devices
    return {"devices": devices}


@app.get("/local-subnet")
async def local_subnet():
    return {"local_subnet": get_allowed_subnet()}

@app.get("/set-control")
async def set_control(
    ip: str = Query(..., description="IP address of the control device"),
    magewell_id: str = Query(..., description="Target magewell_id for bulk updates")
):
    """
    Set the control device.
    Look up the device in the cached devices; use its SETTINGS dict as the control settings.
    Then, generate new settings for a target magewell_id by merging in the control settings
    into the default settings (from get_modified_settings) while preserving dynamic fields.
    Store the merged settings in app.state.control_settings.
    """
    if not hasattr(app.state, "devices") or not app.state.devices:
        return {"error": "No devices cached. Please run a network scan first."}
    
    # Look up the control device by its IP.
    devices = app.state.devices
    control_device = next((d for d in devices if d["ip"] == ip), None)
    if not control_device:
        return {"error": f"Device with IP {ip} not found in cache."}
    
    control_settings = control_device.get("settings", {})
    # Merge control device settings into the default for the given magewell_id.
    new_settings = get_bulk_update_settings(magewell_id, control_settings)
    
    # Cache the new settings in app.state for later bulk update use.
    app.state.control_settings = new_settings
    logger.info(f"Control device set for magewell_id {magewell_id}. New bulk update settings: {new_settings}")
    return {"message": f"Control device set. New settings for magewell_id {magewell_id} updated.", "settings": new_settings}

@app.post("/push-updates")
async def push_updates(selected_devices: list[dict]):
    """
    Push updates to the selected devices. Each object in selected_devices should contain
    at least:
      - "ip": the device IP
      - "magewell_id": the device's ID (to be used for dynamic fields)
      
    For each device, merge the default settings (for that device) with the stored control settings,
    and then push out the merged settings using import_settings_call.
    """
    if not hasattr(app.state, "control_settings") or not app.state.control_settings:
        return {"error": "Control settings not set. Please set a control device first."}
    
    control_settings = app.state.control_settings
    logger.info(f"Pushing updates using control settings: {control_settings}")
    
    connector = aiohttp.TCPConnector(ssl=False, family=socket.AF_INET)
    results = []
    async with aiohttp.ClientSession(connector=connector) as session:
        # Process each selected device concurrently.
        tasks = []
        for device in selected_devices:
            ip = device.get("ip")
            magewell_id = device.get("magewell_id")
            # Merge settings for the target device using its own magewell_id.
            merged_settings = get_bulk_update_settings(magewell_id, control_settings)
            logger.info(f"Merged settings for device {magewell_id} ({ip}): {merged_settings}")
            # Create a task to login and then push the merged settings.
            tasks.append(push_update_for_device(session, ip, magewell_id, merged_settings))
        task_results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in task_results:
            results.append(res)
    return {"results": results}


async def push_update_for_device(session: aiohttp.ClientSession, magewell_ip: str, magewell_id: str, settings: dict) -> dict:
    username = "Admin"
    plaintext_password = "bl4z35"
    try:
        cookie_header = await login_device(session, magewell_ip, username, md5_hash(plaintext_password), magewell_id)
    except Exception as e:
        logger.error(f"Login failed for device {magewell_id} ({magewell_ip}): {e}")
        return {"ip": magewell_ip, "magewell_id": magewell_id, "status": "login failed", "error": str(e)}
    try:
        await import_settings_call(session, magewell_ip, settings, cookie_header, magewell_id)
        return {"ip": magewell_ip, "magewell_id": magewell_id, "status": "updated"}
    except Exception as e:
        logger.error(f"Update failed for device {magewell_id} ({magewell_ip}): {e}")
        return {"ip": magewell_ip, "magewell_id": magewell_id, "status": "update failed", "error": str(e)}
