'use client';

import { useState, useEffect, FormEvent, ChangeEvent } from 'react';
import DeviceGrid from '@/components/DeviceGrid';
import { Device } from '@/components/DeviceCard';
import styles from './page.module.css';
import WaterfallIcon from '@/components/Waterfall';

export default function HomePage() {
  const [loading, setLoading] = useState<boolean>(false);
  const [devices, setDevices] = useState<Device[]>([]);
  const [error, setError] = useState<string>('');
  const [subnet, setSubnet] = useState<string>('');
  const [selectedControlDevice, setSelectedControlDevice] = useState<Device | null>(null);
  const [selectedPushIps, setSelectedPushIps] = useState<string[]>([]);
  const [controlMessage, setControlMessage] = useState<string>('');
  const [pushResult, setPushResult] = useState<string>('');

  // Fetch local subnet
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
      }
      return null;
    } catch (err: unknown) {
      console.error('Error fetching local subnet:', err);
      return null;
    }
  };

  // Scan network
  const scanNetwork = async (subnetToScan: string, forceRescan: boolean = false) => {
    if (!subnetToScan) return;
    setLoading(true);
    setError('');
    console.log('Scanning network for subnet:', subnetToScan, 'forceRescan:', forceRescan);
    try {
      const url = `http://127.0.0.1:8000/discover-magewell?subnet=${encodeURIComponent(
        subnetToScan
      )}&per_ip_timeout=1.0&max_concurrent=50&rescan=${forceRescan}`;
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP error! Status: ${res.statusText}`);
      const data = await res.json();
      console.log('Scan response data:', data);
      setDevices(data.devices || []);
      setSelectedPushIps([]); // reset selections on new scan
    } catch (err: unknown) {
      if (err instanceof Error) setError(err.message);
      else setError('Unknown error occurred');
    } finally {
      setLoading(false);
    }
  };

  // On mount, fetch subnet and scan if devices not cached.
  useEffect(() => {
    (async () => {
      const localSubnet = await fetchLocalSubnet();
      if (localSubnet) {
        await scanNetwork(localSubnet, false);
      }
    })();
  }, []);

  const handleSubnetChange = (e: ChangeEvent<HTMLInputElement>) => {
    setSubnet(e.target.value);
  };

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    scanNetwork(subnet, true);
    setControlMessage('');
    setSelectedControlDevice(null);
    setPushResult('');
    setDevices([]); // clear devices on new scan
    setSelectedPushIps([]); // reset selections on new scan
  };

  // Toggle push selection via checkbox
  const handleSelectToggle = (device: Device) => {
    setSelectedPushIps((prev) => {
      if (prev.includes(device.ip)) {
        return prev.filter(ip => ip !== device.ip);
      } else {
        return [...prev, device.ip];
      }
    });
  };

  const handleSelectAllToggle = (e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.checked) {
      // Select all device IPs
      setSelectedPushIps(devices.map((device) => device.ip));
    } else {
      setSelectedPushIps([]);
    }
  };

  // When user clicks "Set as Control" button on a card.
  const handleSetControlClick = (device: Device) => {
    setSelectedControlDevice(device);
  };

  // API call to set the control device.
  const handleConfirmControl = async () => {
    if (!selectedControlDevice) return;
    try {
      const res = await fetch(
        `http://127.0.0.1:8000/set-control?ip=${selectedControlDevice.ip}&magewell_id=${selectedControlDevice.name}`
      );
      if (!res.ok) {
        throw new Error(`HTTP error! Status: ${res.statusText}`);
      }
      const data = await res.json();
      console.log('Set control device response:', data);
      // Check if the response contains an error message
      if (data.error) {
        setControlMessage(`Error: ${data.error}`);
      } else {
        setControlMessage(
          `Control device set to ${selectedControlDevice.ip} - ${selectedControlDevice.name}`
        );
      }
    } catch (err: unknown) {
      console.error('Error setting control device:', err);
      setControlMessage('Error setting control device');
    } finally {
      setSelectedControlDevice(null);
    }
  };
  

  const handleCloseControlModal = () => {
    setSelectedControlDevice(null);
  };

  // Push updates to selected devices.
  const pushUpdates = async () => {
    if (selectedPushIps.length === 0) {
      setPushResult("No devices selected for push updates.");
      return;
    }
    try {
      // Filter devices based on selected IPs and map them to include both ip and magewell_id (from name)
      const devicesToUpdate = devices
        .filter((device) => selectedPushIps.includes(device.ip))
        .map((device) => ({
          ip: device.ip,
          magewell_id: device.name,
        }));
          
      const res = await fetch("http://127.0.0.1:8000/push-updates", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(devicesToUpdate),
      });
      if (!res.ok) {
        throw new Error(`HTTP error! Status: ${res.statusText}`);
      }
      const data = await res.json();
      console.log("Push updates result:", data);
      // Check if the response includes an error message.
      if (data.error) {
        setPushResult(`Error: ${data.error}`);
      } else {
        setPushResult("Push updates successful");
      }
    } catch (err: unknown) {
      if (err instanceof Error) {
        setPushResult(`Error pushing updates: ${err.message}`);
      } else {
        setPushResult("Unknown error pushing updates");
      }
    }
  };
  
  

  return (
    <div className={styles.main}>
      <div className={styles.formWrapper}>
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
      </div>
      <div className={styles.messageWrapper}>
        <p className={styles.count}>
          Found {devices.length} device{devices.length !== 1 && "s"}.
        </p>
        {controlMessage && <div className={styles.controlMessage}>{controlMessage}</div>}
      </div>
      <div className={styles.gridWrapper}>
        {loading ? (
          <>
            <p className={styles.count}>Scanning...</p>
            <WaterfallIcon />
          </>
        ) : devices.length > 0 ? (
          <>
            <DeviceGrid 
              devices={devices} 
              selectedDeviceIps={selectedPushIps} 
              onSelectToggle={handleSelectToggle}
              onSetControl={handleSetControlClick}
            />
            
          </>
        ) : (
          <p className={styles.count}>No devices found.</p>
        )}
      </div>
      {error && <p className={styles.error}>Error: {error}</p>}
      <div className={styles.selectAllContainer}>
              <input 
                type="checkbox" 
                id="select-all"
                checked={selectedPushIps.length === devices.length && devices.length > 0}
                onChange={handleSelectAllToggle}
                className={styles.checkbox}
              />
              <label htmlFor="select-all" className={styles.checkboxLabel}>
                Select All
              </label>
            </div>
      <div className={styles.pushContainer}>
        <h2>Selected for Updates: {selectedPushIps.length}</h2>
        {selectedPushIps.length > 0 && (
          <ul className={styles.selectedList}>
            {selectedPushIps.map(ip => {
              const device = devices.find(d => d.ip === ip);
              return <li key={ip}>{device?.name || ""} - {ip}</li>;
            })}
          </ul>
        )}
        <button onClick={pushUpdates} className={styles.button28}>
          Push Settings
        </button>
        {pushResult && <p className={styles.pushResult}>{pushResult}</p>}
      </div>
      {/* Modal for setting control device */}
      {selectedControlDevice && (
        <div className={styles.modalOverlay} onClick={handleCloseControlModal}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <h2>Set Control Device</h2>
            <p>
              Set <strong>{selectedControlDevice.name || "Unnamed Device"}</strong> ({selectedControlDevice.ip}) as the control device?
            </p>
            <div className={styles.modalButtons}>
              <button onClick={handleCloseControlModal} className={styles.button28}>
                Cancel
              </button>
              <button onClick={handleConfirmControl} className={styles.button28}>
                Confirm
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
