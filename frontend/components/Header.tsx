"use client";

import NavMenu from "./NavMenu";
import Image from "next/image";
import aio from "@/assets/AIO.png";
import styles from "@/styles/Header.module.css";

export default function Header() {
  return (
    <header className={styles.headerWrapper}>
      <div className={styles.headerInner}>
        <div className={styles.brand}>
          <Image
            src={aio}
            alt="Magewell Ultra Encode AIO"
            width={64}
            height={64}
            priority
          />
          <strong>Magewell AIO</strong>
        </div>
        <NavMenu />
      </div>
    </header>
  );
}
