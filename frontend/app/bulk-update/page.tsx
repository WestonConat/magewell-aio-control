import Link from "next/link";
import styles from "@/app/page.module.css";

export default function BulkUpdatePage() {
  return (
    <div className={styles.page}>
      <div className={styles.headWrapper}>
        <h2>Embedded Baseline Writes Disabled</h2>
        <p>
          This controlled workflow accepts settings only from an explicitly
          selected, live Magewell control device. CSV baseline writes are
          rejected by the backend.
        </p>
        <p>
          <Link href="/">Return to discovery and live-source selection.</Link>
        </p>
      </div>
    </div>
  );
}
