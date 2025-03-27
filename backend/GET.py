#!/usr/bin/env python3
import requests

def send_get_request(url):
    try:
        response = requests.get(url)
        response.raise_for_status()  # Raises an error for bad responses (4xx, 5xx)
        print("Response Code:", response.status_code)
        print("Response Body:\n", response.text)
    except requests.exceptions.RequestException as err:
        print("An error occurred:", err)

if __name__ == "__main__":
    # Replace with your device's IP or hostname (and port if needed)
    device_url = "http://172.16.7.94/usapi?method=login&id=Admin&pass=bl4z35"
    send_get_request(device_url)
