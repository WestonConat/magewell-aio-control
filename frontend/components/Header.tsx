'use client';

import Image from "next/image";
import aio from "@/assets/AIO.png";
import styles from "@/styles/header.module.css"

export default function Header() {
    return (
        <header className={styles.headerWrapper}>
            <Image src={aio} alt="Magewell Device" width={200} height={200} />
            <h1>Magewell Ultra Encode AIO Config Tool</h1>
        </header>
    );
}