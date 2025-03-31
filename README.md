# Magewell Ultra Encode AIO Bulk Update Tool

This tool provides a user-friendly interface to scan your local network for Magewell Ultra Encode AIO devices, select a control device, and push configuration updates in bulk. The app consists of two main components:

- **Frontend (Next.js):**
    
    Displays a grid of detected devices (showing device names and IPs), lets you choose a control device, and provides a CSV upload page for bulk updates.
    
- **Backend (Python FastAPI with Uvicorn):**
    
    Handles network scanning, stores device settings, and pushes updates to selected devices. The backend scans a default network (which can be overridden via environment variable) but also allows you to adjust the network range from the UI.
    

---

## Prerequisites

- [Docker](https://docs.docker.com/get-started/get-docker/)
- [Docker Compose](https://docs.docker.com/compose/)
- Basic knowledge of using the command line

---

## Installation & Setup

1. **Clone the Repository**
    
    Open your terminal and run:
    
    ```bash
    git clone https://github.com/WestonConat/magewell-aio-control.git
    cd magewell-aio-control
    ```
    
2. **Configure Environment (Optional)**
    
    If your local network IP differs from Docker’s default (for example, your local network is `172.16.6.0`), you can override the default in the Docker Compose file. In the `docker-compose.yml` file, under the backend service, add:
    
    ```bash
    environment:
      - LOCAL_HOST_IP=172.16.6.0
    ```
    
3. **Build and Run the App**
    
    InIn the repository root (where the `docker-compose.yml` file is located), run:
    
    ```
    docker compose up
    ```
    
    Docker Compose will build the images for both the backend and frontend, then start the containers.
    

## How to Use the App

- **Access the UI:**
    
    Open your browser and go to [http://localhost:3000](http://localhost:3000/). You’ll see a grid listing the detected Magewell Ultra Encode AIO devices with their names and IP addresses.
    
- **Select a Control Device:**
    
    Click on one of the devices in the grid to set it as the control device. The app stores this selection and uses it to push updates to other devices.
    
- **Bulk Update via CSV:**
    
    Navigate to the CSV upload page in the UI. Upload a CSV file containing device names and IP addresses to perform bulk configuration updates without relying on a network scan.
    
- **Network Rescan & Configuration:**
    
    The app scans the default network (which can be set via the `LOCAL_HOST_IP` environment variable) but also allows you to change the subnet and rescan for devices directly from the interface.
    

## Troubleshooting

- **Network Scanning Shows the Wrong Subnet:**
    
    On some systems (like macOS), Docker Desktop may use a VM network (e.g. `192.168.64.0`). In such cases, ensure you have set the `LOCAL_HOST_IP` environment variable in the `docker-compose.yml` file to match your local network (e.g. `172.16.6.0`).
    
- **Containers Not Starting or Failing:**
    
    Run the following command to view container logs:
    
    ```bash
    docker compose logs
    ```
    
    Check both backend and frontend logs for error messages. If necessary, rebuild the containers by running:
    
    ```bash
    docker compose up --build
    ```
    
- **Stopping and Cleaning Up:**
    
    To stop the containers, press `CTRL+C` in your terminal. To remove the containers, networks, and images created by Docker Compose, run:
    
    ```bash
    docker compose down
    ```
    

## Additional Notes

- **Cross‑Platform Considerations:**
    
    On Linux, Docker’s host network can be used for more direct access, but on macOS, Docker Desktop runs in a VM. Using the `LOCAL_HOST_IP` environment variable (or using `host.docker.internal` in your code) ensures your app scans the correct network regardless of your operating system.
    
- **Further Customizations:**
    
    You can modify the source code or Docker configuration as needed. For more information on Docker, visit the [Docker Documentation](https://docs.docker.com/).
