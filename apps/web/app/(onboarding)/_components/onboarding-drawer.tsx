"use client";

import {
  useEffect,
  useRef,
  useSyncExternalStore,
  type MouseEvent,
  type ReactNode,
} from "react";
import { AnimatePresence, motion } from "motion/react";

const PHONE_QUERY = "(max-width: 639px)";

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
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;

    const previousOverflow = document.body.style.overflow;
    const previousFocus = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    document.body.style.overflow = "hidden";

    const focusableSelector = [
      "a[href]",
      "button:not([disabled])",
      "input:not([disabled])",
      "textarea:not([disabled])",
      "select:not([disabled])",
      "[tabindex]:not([tabindex='-1'])",
    ].join(",");

    const focusFrame = window.requestAnimationFrame(() => {
      const focusable = panelRef.current?.querySelector<HTMLElement>(focusableSelector);
      (focusable ?? panelRef.current)?.focus();
    });

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !panelRef.current) return;
      const focusable = [...panelRef.current.querySelectorAll<HTMLElement>(focusableSelector)]
        .filter((element) => element.offsetParent !== null);
      if (!focusable.length) {
        event.preventDefault();
        panelRef.current.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable.at(-1)!;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
      previousFocus?.focus();
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
            className="onboarding-drawer-backdrop"
            aria-hidden="true"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
            onClick={handleBackdropClick}
          />
          <motion.div
            key="onboarding-drawer-layer"
            className="onboarding-drawer-layer"
            initial={panelInitial}
            animate={{ x: 0, y: 0 }}
            exit={panelExit}
            transition={{
              type: "spring",
              stiffness: 360,
              damping: 38,
              mass: 0.85,
            }}
          >
            <div
              ref={panelRef}
              tabIndex={-1}
              data-testid="onboarding-drawer"
              role="dialog"
              aria-modal="true"
              aria-label="Make your Ally"
              onClick={(event) => event.stopPropagation()}
              className="onboarding-drawer-panel"
            >
              <div className="onboarding-drawer-content">
                {children}
              </div>
            </div>
          </motion.div>
        </>
      ) : null}
    </AnimatePresence>
  );
}
