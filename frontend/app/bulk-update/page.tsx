'use client';

import { useState, FormEvent } from 'react';
import styles from '@/app/page.module.css';
import CustomFileInput from '@/components/CustomFileInput';

export default function BulkUpdatePage() {
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState<string>('');

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!file) {
      setStatus('Please select a CSV file.');
      return;
    }
    setStatus('Uploading and starting bulk update...');

    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch('http://127.0.0.1:8000/bulk-update', {
        method: 'POST',
        body: formData,
      });

      if (res.ok) {
        const data = await res.json();
        setStatus(data.message || 'Bulk update started!');
      } else {
        setStatus(`Error: ${res.statusText}`);
      }
    } catch (error) {
      console.error('Error during upload:', error);
      setStatus('Error during upload');
    }
  };

  return (
    <div className={styles.page}>
      <div className={styles.headWrapper}>
        <h2>Bulk Update</h2>
        <h4>Upload a CSV file to start a bulk update.</h4>
        <p>Include columns &quot;Magewell ID&quot; and &quot;Magewell IP&quot;</p>
      </div>
      <div className={styles.main}>
        <div className={styles.formWrapper}>
          <form onSubmit={handleSubmit}>
            {/* Pass the onFileSelect callback to update the parent's file state */}
            <CustomFileInput onFileSelect={setFile} />
            <button className={styles.button28} type="submit">
              Start Bulk Update
            </button>
          </form>
        </div>
        {status && <div className={styles.statusBox}>{status}</div>}
      </div>
    </div>
  );
}
