"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import styles from "@/styles/NavMenu.module.css";

export default function NavMenu() {
  const pathname = usePathname();

  return (
    <nav className={styles.nav}>
      <ul className={styles.menu}>
        <li className={styles.menuItem}>
          <Link
            href="/"
            className={pathname === "/" ? styles.active : undefined}
            aria-current={pathname === "/" ? "page" : undefined}
          >
            Encoders
          </Link>
        </li>
        <li className={styles.menuItem}>
          <Link
            href="/naming"
            className={pathname === "/naming" ? styles.active : undefined}
            aria-current={pathname === "/naming" ? "page" : undefined}
          >
            Naming
          </Link>
        </li>
      </ul>
    </nav>
  );
}
