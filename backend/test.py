import requests
import hashlib
from bs4 import BeautifulSoup

def md5_hash(password: str) -> str:
    """Return the MD5 hash of the given password string."""
    return hashlib.md5(password.encode('utf-8')).hexdigest()

def login_device(ip: str, username: str, password: str) -> str:
    """
    Login to the device and return the authentication cookie header.
    """
    hashed_password = md5_hash(password)
    login_url = f"http://{ip}/usapi?method=login&id={username}&pass={hashed_password}"
    try:
        response = requests.get(login_url, timeout=5)
        response.raise_for_status()
    except Exception as e:
        print(f"Error logging in to {ip}: {e}")
        return ""
    login_data = response.json()
    print(f"Login successful for {ip}. Received JSON: {login_data}")
    cookie_dict = response.cookies.get_dict()
    cookie_header = "; ".join(f"{k}={v}" for k, v in cookie_dict.items())
    print(f"Constructed Cookie header for {ip}: {cookie_header}")
    return cookie_header

def get_report(ip: str, cookie_header: str) -> dict:
    """
    Fetches the report from the device at the given IP using the get-report endpoint,
    then parses the HTML to extract sections based on <h2> headings within the report content.
    """
    url = f"http://{ip}/usapi?method=get-report"
    # Request HTML
    headers = {
        "Accept": "text/html", 
        "User-Agent": "curl/7.68.0",
        "Cookie": cookie_header,
    }
    try:
        response = requests.get(url, timeout=5, headers=headers)
        response.raise_for_status()
        print(f"Response from get-report: {response}")
        html = response.text
    except Exception as e:
        print(f"Error fetching report from {ip}: {e}")
        return {}

    soup = BeautifulSoup(html, "html.parser")
    report_content = soup.find("div", class_="report-content")
    if not report_content:
        print(f"No report content found in the response from {ip}")
        return {}

    sections = {}
    content_divs = report_content.find_all("div", class_="content-level1")
    for div in content_divs:
        h2 = div.find("h2")
        pre = div.find("pre", class_="json")
        if h2 and pre:
            section_title = h2.get_text(strip=True)
            content = pre.get_text(strip=True)
            sections[section_title] = content

    return sections

if __name__ == "__main__":
    test_ip = "172.16.6.208"  # Replace with a valid device IP for testing.
    cookie_header = login_device(test_ip, "Admin", "bl4z35")
    if cookie_header:
        report = get_report(test_ip, cookie_header)
        if report:
            print("Parsed Report:")
            for section, content in report.items():
                print(f"{section}: {content}")
        else:
            print("Failed to parse report.")
    else:
        print("Login failed; cannot fetch report.")
