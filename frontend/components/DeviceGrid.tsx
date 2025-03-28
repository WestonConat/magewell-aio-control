'use client';

import React from 'react';
import { Device } from './DeviceCard';
import DeviceCard from './DeviceCard';
import styles from '@/styles/DeviceGrid.module.css';

interface DeviceGridProps {
  devices: Device[];
  selectedDeviceIps: string[]; // Array of IP addresses of selected devices.
  onSelectToggle: (device: Device) => void;
  onSetControl: (device: Device) => void;
}

const DeviceGrid: React.FC<DeviceGridProps> = ({ devices, selectedDeviceIps, onSelectToggle, onSetControl }) => {
  return (
    <div className={styles.grid}>
      {devices.map((device) => (
        <DeviceCard 
          key={device.ip}
          device={device}
          isSelected={selectedDeviceIps.includes(device.ip)}
          onSelectToggle={onSelectToggle}
          onSetControl={onSetControl}
        />
      ))}
    </div>
  );
};

export default DeviceGrid;
