'use client';

import React from 'react';
import styles from '@/styles/DeviceCard.module.css';

export interface Device {
  ip: string;
  name: string;
}

interface DeviceCardProps {
  device: Device;
  isSelected: boolean;
  onSelectToggle: (device: Device) => void;
  onSetControl: (device: Device) => void;
}

const DeviceCard: React.FC<DeviceCardProps> = ({ device, isSelected, onSelectToggle, onSetControl }) => {
  return (
    <div className={styles.card}>
      <div className={styles.cardContent}>
        <h2 className={styles.cardName}>{device.name || "Unnamed Device"}</h2>
        <p className={styles.cardIp}>{device.ip}</p>
      </div>
      <div className={styles.cardFooter}>
        <div className={styles.checkboxContainer}>
          <input 
            type="checkbox" 
            checked={isSelected} 
            onChange={() => onSelectToggle(device)} 
            className={styles.checkbox}
            id={`select-${device.ip}`}
          />
          <label htmlFor={`select-${device.ip}`} className={styles.checkboxLabel}>
            Update
          </label>
        </div>
        <button 
          className={styles.controlButton} 
          onClick={() => onSetControl(device)}
        >
          Set Control
        </button>
      </div>
    </div>
  );
};

export default DeviceCard;

