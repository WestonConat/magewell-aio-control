"use client";

import React from "react";
import styles from "@/styles/DeviceCard.module.css";

export interface Device {
  ip: string;
  name: string;
}

interface DeviceCardProps {
  device: Device;
  isSelected: boolean;
  isControlSource: boolean;
  targetBlockedReason?: string;
  onSelectToggle: (device: Device) => void;
  onSetControl: (device: Device) => void;
}

const DeviceCard: React.FC<DeviceCardProps> = ({
  device,
  isSelected,
  isControlSource,
  targetBlockedReason,
  onSelectToggle,
  onSetControl,
}) => {
  return (
    <div
      className={`${styles.card} ${isSelected ? styles.selected : ""} ${
        isControlSource ? styles.controlSource : ""
      }`}
    >
      <div className={styles.cardContent}>
        <div className={styles.cardTitleRow}>
          <h3 className={styles.cardName}>{device.name || "Unnamed Device"}</h3>
          {isControlSource && (
            <span className={styles.sourceBadge}>Source</span>
          )}
          {!isControlSource && targetBlockedReason && (
            <span className={styles.blockedBadge} title={targetBlockedReason}>
              Blocked
            </span>
          )}
        </div>
        <p className={styles.cardIp}>{device.ip}</p>
      </div>
      <div className={styles.cardFooter}>
        <label className={styles.checkboxContainer}>
          <input
            type="checkbox"
            checked={isSelected}
            disabled={isControlSource || Boolean(targetBlockedReason)}
            onChange={() => onSelectToggle(device)}
            className={styles.checkbox}
          />
          <span className={styles.checkboxLabel}>
            {targetBlockedReason
              ? "Blocked"
              : isSelected
                ? "Selected"
                : "Target"}
          </span>
        </label>
        <button
          className={styles.controlButton}
          onClick={() => onSetControl(device)}
          disabled={isControlSource}
        >
          {isControlSource ? "Current source" : "Use as source"}
        </button>
      </div>
    </div>
  );
};

export default DeviceCard;
