"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useState } from "react";

import { AllyAvatar } from "../../components/ally-avatar";
import styles from "./home.module.css";

const SHOW_AFTER_MS = 2_000;

export function HomeReadySplash() {
  const [visible, setVisible] = useState(false);
  const reducedMotion = useReducedMotion();

  useEffect(() => {
    const timer = window.setTimeout(() => setVisible(true), SHOW_AFTER_MS);
    return () => window.clearTimeout(timer);
  }, []);

  return (
    <AnimatePresence>
      {visible ? (
        <motion.div
          className={styles.readySplash}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0, scale: reducedMotion ? 1 : 0.96, transition: { duration: 0.2, ease: [0.22, 1, 0.36, 1] } }}
          transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
          aria-hidden="true"
        >
          <AllyAvatar shape="ghosty" color="#ff5800" size={56} state="idle" label="" />
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
