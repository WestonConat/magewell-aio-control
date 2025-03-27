'use client';

import { useState, useEffect, FormEvent, ChangeEvent } from 'react';
import styles from './page.module.css';

interface Device {
  ip: string;
  name: string;
}

export default function HomePage() {
  const [loading, setLoading] = useState<boolean>(false);
  const [devices, setDevices] = useState<Device[]>([]);
  const [error, setError] = useState<string>('');
  const [subnet, setSubnet] = useState<string>('');

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
  const scanNetwork = async (subnetToScan: string) => {
    if (!subnetToScan) {
      console.error('No subnet provided for scanning');
      return;
    }
    setLoading(true);
    setError('');
    console.log('Scanning network for subnet:', subnetToScan);
    try {
      const res = await fetch(
        `http://127.0.0.1:8000/discover-magewell?subnet=${encodeURIComponent(
          subnetToScan
        )}&per_ip_timeout=1.0&max_concurrent=50`
      );
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

  // On mount, fetch the local subnet and then scan it.
  useEffect(() => {
    (async () => {
      const localSubnet = await fetchLocalSubnet();
      if (localSubnet) {
        await scanNetwork(localSubnet);
      }
    })();
  }, []);

  const handleSubnetChange = (e: ChangeEvent<HTMLInputElement>) => {
    setSubnet(e.target.value);
  };

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    scanNetwork(subnet);
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
      <div className={styles.tableWrapper}>
        <p className={styles.count}>
          Found {devices.length} device{devices.length !== 1 && 's'}.
        </p>
        {loading ? (
          <p>Scanning network…</p>
        ) : devices.length > 0 ? (
          <table className={styles.table}>
            <thead>
              <tr>
                <th className={styles.tableHeader}>Device Name</th>
                <th className={styles.tableHeader}>IP Address</th>
              </tr>
            </thead>
            <tbody>
              {devices.map(({ ip, name }) => (
                <tr key={ip}>
                  <td className={styles.tableCell}>{name}</td>
                  <td className={styles.tableCell}>{ip}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p>No devices found.</p>
        )}
      </div>
      {error && <p className={styles.error}>Error: {error}</p>}
    </div>
  );
}
