'use client';

import React from 'react';
import styles from '@/styles/DeviceCard.module.css';

export interface Device {
  ip: string;
  name: string;
}

interface DeviceCardProps {
  device: Device;
  onClick: () => void;
}

const DeviceCard: React.FC<DeviceCardProps> = ({ device, onClick }) => {
  return (
    <div className={styles.card} onClick={onClick}>
      <h2 className={styles.cardName}>{device.name || "Unnamed Device"}</h2>
      <p className={styles.cardIp}>{device.ip}</p>
    </div>
  );
};

export default DeviceCard;
