"use client";

import {
  useEffect,
  useRef,
  useSyncExternalStore,
  type MouseEvent,
  type ReactNode,
} from "react";
import { AnimatePresence, motion, useReducedMotion, type PanInfo } from "motion/react";

const PAGE_QUERY = "(max-width: 1023px)";

function subscribeToPageQuery(callback: () => void) {
  if (typeof window === "undefined") return () => undefined;

  const mediaQuery = window.matchMedia(PAGE_QUERY);
  mediaQuery.addEventListener("change", callback);
  return () => mediaQuery.removeEventListener("change", callback);
}

function getPageQuerySnapshot() {
  return typeof window !== "undefined" && window.matchMedia(PAGE_QUERY).matches;
}

function useIsPageOverlay() {
  return useSyncExternalStore(subscribeToPageQuery, getPageQuerySnapshot, () => false);
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
  const isPageOverlay = useIsPageOverlay();
  const panelRef = useRef<HTMLDivElement>(null);
  const layerRef = useRef<HTMLDivElement>(null);
  const reducedMotion = useReducedMotion();
  const pageOverlayWasOpen = useRef(false);

  useEffect(() => {
    if (!isPageOverlay) return;
    if (open) {
      pageOverlayWasOpen.current = true;
      return;
    }
    if (!pageOverlayWasOpen.current) return;
    pageOverlayWasOpen.current = false;
    onClosed?.();
  }, [isPageOverlay, onClosed, open]);

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

  const handleDragEnd = (_event: unknown, info: PanInfo) => {
    const width = layerRef.current?.offsetWidth ?? window.innerWidth;
    if (info.velocity.x > 500 || info.offset.x > width * 0.35) onClose();
  };

  const panel = (
    <div
      ref={panelRef}
      tabIndex={-1}
      data-testid="onboarding-drawer"
      data-page-overlay={isPageOverlay ? "true" : "false"}
      role="dialog"
      aria-modal="true"
      aria-label="Make your Ally"
      onClick={(event) => event.stopPropagation()}
      className={
        isPageOverlay
          ? "onboarding-drawer-panel onboarding-drawer-panel-page"
          : "onboarding-drawer-panel"
      }
    >
      <div className="onboarding-drawer-content">{children}</div>
    </div>
  );

  if (isPageOverlay) {
    if (!open) return null;
    return (
      <div className="onboarding-drawer-layer onboarding-drawer-layer-page">
        {panel}
      </div>
    );
  }

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
            ref={layerRef}
            className="onboarding-drawer-layer"
            drag={reducedMotion ? false : "x"}
            dragConstraints={{ left: 0, right: 0 }}
            dragElastic={{ left: 0, right: 0.5 }}
            onDragEnd={handleDragEnd}
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{
              type: "spring",
              stiffness: 360,
              damping: 38,
              mass: 0.85,
            }}
          >
            {panel}
          </motion.div>
        </>
      ) : null}
    </AnimatePresence>
  );
}
