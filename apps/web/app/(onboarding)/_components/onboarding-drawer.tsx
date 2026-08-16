"use client";

import {
  useEffect,
  useSyncExternalStore,
  type MouseEvent,
  type ReactNode,
} from "react";
import { AnimatePresence, motion } from "motion/react";

const PHONE_QUERY = "(max-width: 639px)";
const DESKTOP_DRAWER_VERTICAL_INSET = 24;
const DESKTOP_DRAWER_RIGHT = 24;
const DESKTOP_DRAWER_CONTENT_OFFSET = -32;

function subscribeToPhoneQuery(callback: () => void) {
  if (typeof window === "undefined") return () => undefined;

  const mediaQuery = window.matchMedia(PHONE_QUERY);
  mediaQuery.addEventListener("change", callback);
  return () => mediaQuery.removeEventListener("change", callback);
}

function getPhoneQuerySnapshot() {
  return typeof window !== "undefined" && window.matchMedia(PHONE_QUERY).matches;
}

function useIsPhone() {
  return useSyncExternalStore(subscribeToPhoneQuery, getPhoneQuerySnapshot, () => false);
}

export default function OnboardingDrawer({
  open,
  onClose,
  onClosed,
  children,
}: {
  open: boolean;
  onClose: () => void;
  onClosed?: () => void;
  children: ReactNode;
}) {
  const isPhone = useIsPhone();

  useEffect(() => {
    if (!open) return;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [onClose, open]);

  const handleBackdropClick = (event: MouseEvent<HTMLDivElement>) => {
    if (event.target === event.currentTarget) onClose();
  };

  const panelInitial = isPhone ? { y: "100%" } : { x: "100%" };
  const panelExit = isPhone ? { y: "100%" } : { x: "100%" };

  return (
    <AnimatePresence initial={false} onExitComplete={onClosed}>
      {open ? (
        <>
          <motion.div
            key="onboarding-drawer-backdrop"
            aria-hidden="true"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
            onClick={handleBackdropClick}
            style={{
              position: "fixed",
              inset: 0,
              zIndex: 40,
              background: "rgba(18, 18, 18, 0.18)",
            }}
          />
          <motion.div
            key="onboarding-drawer-panel"
            role="dialog"
            aria-modal="true"
            aria-label="Make your Ally"
            initial={panelInitial}
            animate={{ x: 0, y: 0 }}
            exit={panelExit}
            transition={{
              type: "spring",
              stiffness: 360,
              damping: 38,
              mass: 0.85,
            }}
            onClick={(event) => event.stopPropagation()}
            style={{
              position: "fixed",
              top: isPhone ? 0 : DESKTOP_DRAWER_VERTICAL_INSET,
              right: isPhone ? 0 : DESKTOP_DRAWER_RIGHT,
              bottom: isPhone ? 0 : DESKTOP_DRAWER_VERTICAL_INSET,
              left: isPhone ? 0 : "auto",
              zIndex: 41,
              width: isPhone ? "100vw" : "min(400px, calc(100vw - 48px))",
              height: isPhone
                ? "100dvh"
                : `calc(100dvh - ${DESKTOP_DRAWER_VERTICAL_INSET * 2}px)`,
              overflow: "hidden",
              borderRadius: isPhone ? "24px 24px 0 0" : 24,
              background: "#fff",
              boxShadow: "none",
            }}
          >
            <div
              style={{
                height: isPhone
                  ? "100%"
                  : `calc(100% + ${-DESKTOP_DRAWER_CONTENT_OFFSET}px)`,
                transform: isPhone
                  ? undefined
                  : `translateY(${DESKTOP_DRAWER_CONTENT_OFFSET}px)`,
                ["--onboarding-artboard-min-height" as string]: "100%",
              }}
            >
              {children}
            </div>
          </motion.div>
        </>
      ) : null}
    </AnimatePresence>
  );
}
