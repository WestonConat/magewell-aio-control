import json
import hashlib
import requests

def md5_hash(password):
    """Return the MD5 hash of the given password string."""
    return hashlib.md5(password.encode('utf-8')).hexdigest()

def login(ip, username, plaintext_password):
    """
    Log in to the device and return a session with the authentication cookie.
    """
    hashed_password = md5_hash(plaintext_password)
    login_url = f"http://{ip}/usapi?method=login&id={username}&pass={hashed_password}"
    session = requests.Session()
    try:
        response = session.get(login_url)
        response.raise_for_status()
        if response.status_code == 200:
            # Optionally process login JSON data
            login_data = response.json()
            print("Login successful:", login_data)
        else:
            print("Login failed with status code:", response.status_code)
            return None
    except requests.exceptions.RequestException as err:
        print("Login error:", err)
        return None
    return session

def export_settings(session, ip, file_name):
    """
    Retrieve the current settings from the device.
    """
    url = f"http://{ip}/usapi?method=export-settings&file-name={file_name}"
    response = session.get(url)
    response.raise_for_status()
    return response.json()

# def modify_settings(settings_json):
#     """
#     Modify the settings JSON as required.
    
#     In this example, we update 'settingA' to 'new_value' if it exists.
#     """
#     if 'audio-sync-offset' in settings_json:
#         settings_json['audio-sync-offset'] = "100"
#     # Add more modifications as needed
#     return settings_json

# def import_settings(session, ip, modified_settings):
#     """
#     Import settings to the device using a POST request.
#     """
#     url = f"http://{ip}/usapi?method=import-settings"
#     response = session.post(url, json=modified_settings)
#     response.raise_for_status()
#     return response.json()


def main():
    # Device and login configuration
    ip = "172.16.7.227"  # Replace with your device's IP address
    username = "Admin"  # Replace with your login username
    plaintext_password = "bl4z35"  # Replace with your password
    file_name = "config.json"  # The file-name parameter as expected by your device

    # Log in and obtain a session with authentication cookies (e.g., sid)
    session = login(ip, username, plaintext_password)
    if session is None:
        print("Failed to log in. Exiting.")
        return

    try:
        # Step 1: Export settings
        settings = export_settings(session, ip, file_name)
        print("Exported settings:", settings)

        # # Step 2: Modify settings as needed
        # modified_settings = modify_settings(settings)
        # print("Modified settings:", modified_settings)

        # # Step 3: Import the modified settings
        # import_response = import_settings(session, ip, modified_settings)
        # print("Import response:", import_response)
    except requests.exceptions.RequestException as err:
        print("An error occurred during the process:", err)

if __name__ == "__main__":
    main()
