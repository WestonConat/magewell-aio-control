'use client';

import { useState, useEffect, FormEvent, ChangeEvent } from 'react';
import styles from './page.module.css';
import DeviceGrid from '@/components/DeviceGrid';
import { Device } from '@/components/DeviceCard';
import WaterfallIcon from '@/components/Waterfall'

export default function HomePage() {
  const [loading, setLoading] = useState<boolean>(false);
  const [devices, setDevices] = useState<Device[]>([]);
  const [error, setError] = useState<string>('');
  const [subnet, setSubnet] = useState<string>('');
  const [selectedDevice, setSelectedDevice] = useState<Device | null>(null);
  const [controlMessage, setControlMessage] = useState<string>('');

  // Fetch the default local subnet from the backend and return it.
  const fetchLocalSubnet = async (): Promise<string | null> => {
    try {
      const res = await fetch('http://127.0.0.1:8000/local-subnet');
      if (!res.ok) {
        throw new Error(`HTTP error! Status: ${res.statusText}`);
      }
      const data = await res.json();
      if (data.local_subnet) {
        console.log('Fetched local subnet:', data.local_subnet);
        setSubnet(data.local_subnet);
        return data.local_subnet;
      } else {
        return null;
      }
    } catch (err: unknown) {
      console.error('Error fetching local subnet:', err);
      return null;
    }
  };

  // Scan the network using the specified subnet.
  // forceRescan: if true, passes rescan=true to the backend to force a new scan.
  const scanNetwork = async (subnetToScan: string, forceRescan: boolean = false) => {
    if (!subnetToScan) {
      console.error('No subnet provided for scanning');
      return;
    }
    setLoading(true);
    setError('');
    console.log('Scanning network for subnet:', subnetToScan, 'forceRescan:', forceRescan);
    try {
      const url = `http://127.0.0.1:8000/discover-magewell?subnet=${encodeURIComponent(
        subnetToScan
      )}&per_ip_timeout=1.0&max_concurrent=50&rescan=${forceRescan}`;
      const res = await fetch(url);
      if (!res.ok) {
        throw new Error(`HTTP error! Status: ${res.statusText}`);
      }
      const data = await res.json();
      console.log('Scan response data:', data);
      setDevices(data.devices || []);
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Unknown error occurred');
      }
    } finally {
      setLoading(false);
    }
  };

  // On mount, fetch the local subnet and scan without forcing a rescan.
  useEffect(() => {
    (async () => {
      const localSubnet = await fetchLocalSubnet();
      if (localSubnet) {
        // On initial load, do not force a rescan (allow cached devices if available).
        await scanNetwork(localSubnet, false);
      }
    })();
  }, []);

  const handleSubnetChange = (e: ChangeEvent<HTMLInputElement>) => {
    setSubnet(e.target.value);
  };

  // When the form is submitted, force a new scan.
  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    scanNetwork(subnet, true);
  };

  // Handle card click: open a modal (or pop-up) to set the control device.
  const handleCardClick = (device: Device) => {
    setSelectedDevice(device);
  };

  // API call to set the control device.
  const handleSetControl = async () => {
    if (!selectedDevice) return;
    try {
      const res = await fetch(
        `http://127.0.0.1:8000/set-control?ip=${selectedDevice.ip}&magewell_id=${selectedDevice.name}`,
      );
      if (!res.ok) {
        throw new Error(`HTTP error! Status: ${res.statusText}`);
      }
      const data = await res.json();
      console.log('Set control device response:', data);
      setControlMessage(`Control device set to ${selectedDevice.ip} - ${selectedDevice.name}`);
    } catch (err: unknown) {
      console.error('Error setting control device:', err);
      setControlMessage('Error setting control device');
    } finally {
      setSelectedDevice(null); // Close modal.
    }
  };

  const handleCloseModal = () => {
    setSelectedDevice(null);
  };

  return (
    <div className={styles.page}>
      <h1 className={styles.headWrapper}>Magewell Device Scanner</h1>
      <form onSubmit={handleSubmit}>
        <label htmlFor="subnet" className={styles.label}>
          Subnet to scan:
        </label>
        <input
          id="subnet"
          type="text"
          value={subnet}
          onChange={handleSubnetChange}
          className={styles.input}
          placeholder="Enter subnet (e.g., 172.16.6.0/23)"
        />
        <button type="submit" className={styles.button28}>
          Rescan Network
        </button>
      </form>
      {controlMessage && <p className={styles.controlMessage}>{controlMessage}</p>}
      <div className={styles.tableWrapper}>
        {loading ? (
          <>
          <p className={styles.count}>Scanning...</p>
          <WaterfallIcon />
          </>
        ) : devices.length > 0 ? (
          <>
            <p className={styles.count}>
              Found {devices.length} device{devices.length !== 1 && 's'}.
            </p>
            <DeviceGrid devices={devices} onCardClick={handleCardClick} />
          </>
        ) : (
          <p>No devices found.</p>
        )}
      </div>
      {error && <p className={styles.error}>Error: {error}</p>}
      {/* Modal for setting control device */}
      {selectedDevice && (
        <div className={styles.modalOverlay} onClick={handleCloseModal}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <h2>Set Control Device</h2>
            <p>
              Set <strong>{selectedDevice.name || "Unnamed Device"}</strong> (
              {selectedDevice.ip}) as the control device?
            </p>
            <div className={styles.modalButtons}>
              <button onClick={handleCloseModal} className={styles.button28}>
                Cancel
              </button>
              <button onClick={handleSetControl} className={styles.button28}>
                Confirm
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
