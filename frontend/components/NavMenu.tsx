'use client';

import Link from 'next/link';
import styles from '@/styles/NavMenu.module.css';

export default function NavMenu() {
  return (
    <nav className={styles.nav}>
      <ul className={styles.menu}>
        <li className={styles.menuItem}>
          <Link href="/">Device Scanner</Link>
        </li>
        <li>|</li>
        <li className={styles.menuItem}>
          <Link href="/bulk-update">CSV Update</Link>
        </li>
        {/* Add additional menu items here if needed */}
      </ul>
    </nav>
  );
}
