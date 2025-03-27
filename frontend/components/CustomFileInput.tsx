// File: components/CustomFileInput.tsx
'use client';

import { useRef, useState, ChangeEvent } from 'react';
import styles from '@/app/page.module.css'

interface CustomFileInputProps {
  onFileSelect: (file: File) => void;
}

export default function CustomFileInput({ onFileSelect }: CustomFileInputProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [fileName, setFileName] = useState<string>('No file chosen');

  const handleButtonClick = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const selectedFile = e.target.files[0];
      setFileName(selectedFile.name);
      onFileSelect(selectedFile);
    }
  };

  return (
    <>
      <input
        type="file"
        ref={fileInputRef}
        onChange={handleFileChange}
        style={{ display: 'none' }}
      />
      <button className={styles.button28} onClick={handleButtonClick}>Browse...</button>
      <span>{fileName}</span>
    </>
  );
}
