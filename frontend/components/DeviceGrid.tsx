'use client';

import React from 'react';
import { Device } from './DeviceCard';
import DeviceCard from './DeviceCard';
import styles from '@/styles/DeviceGrid.module.css';

interface DeviceGridProps {
  devices: Device[];
  onCardClick: (device: Device) => void;
}

const DeviceGrid: React.FC<DeviceGridProps> = ({ devices, onCardClick }) => {
  return (
    <div className={styles.grid}>
      {devices.map((device) => (
        <DeviceCard
          key={device.ip}
          device={device}
          onClick={() => onCardClick(device)}
        />
      ))}
    </div>
  );
};

export default DeviceGrid;
