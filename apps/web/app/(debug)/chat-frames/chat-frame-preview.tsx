"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { DebugConversationFrame } from "./debug-conversation-frame";
import type {
  DebugConversationAction,
  DebugConversationFrameModel,
} from "./debug-conversation-frame-model";
import type { ChatFrameFixture } from "./chat-frame-fixtures";
import styles from "./chat-frame-debug.module.css";

export function ChatFramePreview({ fixture }: { fixture: ChatFrameFixture }) {
  return <ChatFramePreviewState key={fixture.frameId} fixture={fixture} />;
}

function ChatFramePreviewState({ fixture }: { fixture: ChatFrameFixture }) {
  const [overlay, setOverlay] = useState(fixture.model.overlay);
  const [queue, setQueue] = useState(fixture.model.queue);
  const [acknowledgement, setAcknowledgement] = useState(fixture.model.acknowledgement);
  const [deleted, setDeleted] = useState(fixture.model.deleted);
  const [composerDraft, setComposerDraft] = useState(fixture.model.composer.draft);
  const [quantities, setQuantities] = useState<Record<string, number>>({});
  const previewRef = useRef<HTMLDivElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);

  const products = useMemo(() => {
    const item = fixture.model.timeline.find((candidate) => candidate.kind === "products");
    return item?.kind === "products" ? item.products : [];
  }, [fixture.model.timeline]);

  const model = useMemo<DebugConversationFrameModel>(() => ({
    ...fixture.model,
    queue,
    overlay,
    acknowledgement,
    deleted,
    composer: {
      ...fixture.model.composer,
      draft: composerDraft,
    },
    timeline: fixture.model.timeline
      .filter((item) => !(acknowledgement && item.kind === "failure"))
      .map((item) => (
        item.kind === "cart-editor"
          ? { ...item, quantity: quantities[item.id] ?? item.quantity }
          : item
      )),
  }), [acknowledgement, composerDraft, deleted, fixture.model, overlay, quantities, queue]);

  const handleAction = useCallback((action: DebugConversationAction) => {
    switch (action) {
      case "approve":
        setAcknowledgement("Approved for this fixture");
        setOverlay(null);
        return;
      case "reject":
        setAcknowledgement("Rejected for this fixture");
        setOverlay(null);
        return;
      case "report":
        setAcknowledgement("Thanks for sharing this report");
        return;
      case "push":
        setAcknowledgement("Queued message pushed locally");
        return;
      case "open-image": {
        const image = fixture.model.timeline.find((item) => item.kind === "image");
        if (image?.kind === "image") setOverlay({ kind: "image", alt: image.alt });
        return;
      }
      case "open-cart":
        setOverlay({ kind: "cart", itemCount: 4, products });
        return;
      case "open-routine":
        setOverlay({ kind: "routine" });
        return;
      case "delete-routine":
        setOverlay({ kind: "delete-routine" });
        return;
      case "cancel-delete":
      case "close-overlay":
      case "done-cart":
        setOverlay(null);
        return;
      case "confirm-delete":
        setDeleted(true);
        setAcknowledgement("Routine deleted");
        setOverlay(null);
        return;
    }
  }, [fixture.model.timeline, products]);

  useEffect(() => {
    const preview = previewRef.current;
    preview?.setAttribute("data-frame-hydrated", "true");
    return () => preview?.removeAttribute("data-frame-hydrated");
  }, []);

  useEffect(() => {
    if (!overlay) return;
    returnFocusRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const frame = window.requestAnimationFrame(() => {
      const dialog = previewRef.current?.querySelector<HTMLElement>("[role='dialog']");
      dialog?.querySelector<HTMLElement>("button, [href], input, textarea")?.focus();
    });
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        handleAction("close-overlay");
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("keydown", onKeyDown);
      if (returnFocusRef.current?.isConnected) returnFocusRef.current.focus();
    };
  }, [handleAction, overlay]);

  return (
    <main ref={previewRef} className={styles.page} data-frame-id={fixture.frameId} data-frame-ready>
      <DebugConversationFrame
        model={model}
        actions={{
          onAction: handleAction,
          onComposerChange: setComposerDraft,
          onComposerSubmit: () => {
            if (composerDraft.trim()) setAcknowledgement("Message kept local for this fixture");
          },
          onRemoveQueue: (id) => setQueue((current) => current.filter((item) => item.id !== id)),
          onQuantityChange: (id, next) => setQuantities((current) => ({ ...current, [id]: next })),
        }}
      />
    </main>
  );
}
