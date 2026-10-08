import { Children, useEffect, useId, useLayoutEffect, useRef, useState, type ClipboardEvent, type CSSProperties, type ReactNode, type Ref, type UIEvent } from "react";
import Link from "next/link";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";

import { AllyAvatar, type AllyShape } from "../../components/ally-avatar";
import { ShinyText } from "../../components/text-animations/shiny-text";

import styles from "./conversation-frame.module.css";
import { formatFileSize } from "./file-size";
import type { QueuedAttachmentPreview } from "./conversation-frame-model";
import { FileIcon } from "./attachments/attachment-picker";
import { useIsMobileHome } from "./use-is-mobile-home";
import { ActivityIcon } from "./activity-icon";

export type FrameAvatar = ReactNode;

const blackTextAllyColors = new Set(["#be9bf5", "#a3f06f", "#fbe65f"]);
const lightActivityAccents: Record<string, string> = {
  "#be9bf5": "#7651b5",
  "#a3f06f": "#4a821f",
  "#fbe65f": "#8a7000",
};

export function readableAccentForeground(accent: string) {
  const normalized = accent.toLowerCase();
  if (blackTextAllyColors.has(normalized)) return "#000000";
  if (["#ff5800", "#fd304f", "#0d92fd", "#3446e9"].includes(normalized)) return "#ffffff";
  const hex = accent.match(/^#([\da-f]{2})([\da-f]{2})([\da-f]{2})$/i);
  if (!hex) return "#ffffff";
  const luminance = hex.slice(1).reduce((sum, channel, index) => {
    const value = Number.parseInt(channel, 16) / 255;
    const linear = value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
    return sum + linear * [0.2126, 0.7152, 0.0722][index];
  }, 0);
  return luminance > 0.179 ? "#000000" : "#ffffff";
}

export function ConversationShell({
  accent,
  children,
  className = "",
  safeArea,
  scrolled = false,
  shellRef,
}: {
  accent: string;
  children: ReactNode;
  className?: string;
  safeArea?: { top?: string; bottom?: string };
  scrolled?: boolean;
  shellRef?: Ref<HTMLDivElement>;
}) {
  const style = {
    "--chat-accent": accent,
    "--chat-on-accent": readableAccentForeground(accent),
    "--chat-activity-light-accent": lightActivityAccents[accent.toLowerCase()] ?? accent,
    ...(safeArea?.top ? { "--chat-safe-top": safeArea.top } : {}),
    ...(safeArea?.bottom ? { "--chat-safe-bottom": safeArea.bottom } : {}),
  } as CSSProperties;
  return (
    <div
      ref={shellRef}
      className={`${styles.frameShell} ${className}`}
      data-testid="conversation-frame-shell"
      style={style}
    >
      <div className={`${styles.frameScrollBlur} ${scrolled ? "" : styles.frameDesktopFade}`} data-testid="conversation-frame-scroll-blur" aria-hidden="true" />
      {children}
    </div>
  );
}

export function ConversationHeader({
  name,
  subtitle,
  avatar,
  sleepingAvatar,
  homeHref = "/home",
  settingsHref = "/account",
  onSettings,
  sleeping = false,
  statusContent,
}: {
  name: string;
  subtitle: string;
  avatar: FrameAvatar;
  sleepingAvatar?: FrameAvatar;
  homeHref?: string;
  settingsHref?: string;
  onSettings?: () => void;
  sleeping?: boolean;
  statusContent?: ReactNode;
}) {
  return (
    <header className={`${styles.frameHeader} ${sleeping ? styles.frameHeaderSleeping : ""}`}>
      <Link className={styles.frameIconHit} href={homeHref} aria-label="Back to Allies">
        <BackIcon />
      </Link>
      <span className={styles.frameAvatar}>{avatar}</span>
      <div className={styles.frameIdentity}>
        <h1>{name}</h1>
        <p>{subtitle}</p>
      </div>
      {statusContent ?? (sleeping ? (
        <div className={styles.frameSleepingStatus} data-testid="ally-sleeping-status">
          <span className={styles.frameSleepingAvatar}>{sleepingAvatar ?? avatar}</span>
          <span>{name} is asleep</span>
        </div>
      ) : null)}
      {onSettings ? (
        <button type="button" className={`${styles.frameIconHit} ${styles.frameSettingsMobile}`} onClick={onSettings} aria-label={`${name} settings`}>
          <SettingsIcon />
        </button>
      ) : (
        <Link className={`${styles.frameIconHit} ${styles.frameSettingsMobile}`} href={settingsHref} aria-label={`${name} settings`}>
          <SettingsIcon />
        </Link>
      )}
      {onSettings ? (
        <button type="button" className={`${styles.frameSettingsDesktop} ${styles.frameSettingsDesktopButton}`} onClick={onSettings} aria-label={`${name} settings`}>
          <FrameIcon name="settings-desktop" className={styles.frameSettingsIcon} />
          <span>{name} settings</span>
        </button>
      ) : (
        <Link className={styles.frameSettingsDesktop} href={settingsHref}>
          <FrameIcon name="settings-desktop" className={styles.frameSettingsIcon} />
          <span>{name} settings</span>
        </Link>
      )}
    </header>
  );
}

export function ConversationCanvas({
  children,
  onScroll,
  canvasRef,
  className = "",
}: {
  children: ReactNode;
  onScroll?: (event: UIEvent<HTMLDivElement>) => void;
  canvasRef?: Ref<HTMLDivElement>;
  className?: string;
}) {
  const scrollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (scrollTimer.current) clearTimeout(scrollTimer.current);
  }, []);
  const handleScroll = (event: UIEvent<HTMLDivElement>) => {
    const canvas = event.currentTarget;
    canvas.dataset.scrolling = "true";
    if (scrollTimer.current) clearTimeout(scrollTimer.current);
    scrollTimer.current = setTimeout(() => { delete canvas.dataset.scrolling; }, 1100);
    onScroll?.(event);
  };
  return (
    <div ref={canvasRef} className={`${styles.frameCanvas} ${className}`} onScroll={handleScroll} data-testid="conversation-frame-canvas">
      {children}
    </div>
  );
}

export function ConversationRail({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`${styles.frameRail} ${className}`} data-testid="conversation-frame-rail">{children}</div>;
}

export function DateDivider({
  children,
  sticky = false,
}: {
  children: ReactNode;
  sticky?: boolean;
}) {
  return (
    <p className={sticky ? styles.frameDateDividerSticky : styles.frameDateDividerInline}>
      {children}
    </p>
  );
}

export function AssistantIdentity({
  avatar,
  name,
}: {
  avatar: FrameAvatar;
  name: string;
}) {
  return (
    <div className={styles.frameAssistantIdentity}>
      {avatar}
      <strong>{name}</strong>
    </div>
  );
}

export function UserBubble({
  children,
  createdAt,
  status,
  retryable = false,
  retrying = false,
  onRetry,
  className = "",
}: {
  children: ReactNode;
  createdAt?: string;
  status?: string | null;
  retryable?: boolean;
  retrying?: boolean;
  onRetry?: () => void;
  className?: string;
}) {
  const textRef = useRef<HTMLParagraphElement>(null);
  const [multiline, setMultiline] = useState(false);
  const timestamp = useTimestampReveal(createdAt);

  useLayoutEffect(() => {
    const node = textRef.current;
    if (!node) return;
    setMultiline(node.getBoundingClientRect().height > 20);
  }, [children]);

  return (
    <>
      <article
        className={`${styles.frameUserBubble} ${className}`}
        data-multiline={multiline ? "true" : "false"}
        tabIndex={timestamp ? 0 : undefined}
        onClick={timestamp?.reveal}
        onFocus={timestamp?.reveal}
        onKeyDown={(event) => {
          if (event.target !== event.currentTarget || !timestamp || !["Enter", " "].includes(event.key)) return;
          event.preventDefault();
          timestamp.reveal();
        }}
      >
        <p ref={textRef}>{children}</p>
        {status ? <span className={styles.frameBubbleStatus}>{status}</span> : null}
        {retryable && onRetry ? (
          <button type="button" className={styles.frameRetryButton} onClick={onRetry} disabled={retrying}>
            {retrying ? "Retrying…" : "Retry"}
          </button>
        ) : null}
      </article>
      {timestamp ? <time className={styles.frameMessageTimestamp} data-visible={timestamp.visible} dateTime={createdAt}>{timestamp.label}</time> : null}
    </>
  );
}

export function AssistantMessage({
  children,
  createdAt,
  className = "",
  testId,
}: {
  children: ReactNode;
  createdAt?: string;
  className?: string;
  testId?: string;
}) {
  const timestamp = useTimestampReveal(createdAt);
  return (
    <>
      <article className={`${styles.frameAssistantMessage} ${className}`} data-testid={testId} tabIndex={timestamp ? 0 : undefined} onClick={timestamp?.reveal} onFocus={timestamp?.reveal} onKeyDown={(event) => {
        if (event.target !== event.currentTarget || !timestamp || !["Enter", " "].includes(event.key)) return;
        event.preventDefault();
        timestamp.reveal();
      }}>
        <div>{children}</div>
      </article>
      {timestamp ? <time className={styles.frameMessageTimestamp} data-visible={timestamp.visible} dateTime={createdAt}>{timestamp.label}</time> : null}
    </>
  );
}

function useTimestampReveal(createdAt?: string) {
  const date = createdAt ? new Date(createdAt) : null;
  const valid = date && !Number.isNaN(date.getTime());
  const [visible, setVisible] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  if (!valid) return null;
  return {
    label: new Intl.DateTimeFormat([], { timeStyle: "short" }).format(date),
    visible,
    reveal: () => {
      setVisible(true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setVisible(false), 3_000);
    },
  };
}

export function ThinkingStatus({
  avatar,
  label,
  iconOnly = false,
  className = "",
}: {
  avatar: FrameAvatar;
  label: string;
  iconOnly?: boolean;
  className?: string;
}) {
  return (
    <div
      className={`${styles.frameThinking} ${className}`}
      role="status"
      aria-live="polite"
      aria-label={iconOnly ? "Responding" : undefined}
    >
      {avatar}
      {iconOnly ? null : (
        <ShinyText color="var(--chat-accent)" shineColor="#ffffff">
          {label}
        </ShinyText>
      )}
    </div>
  );
}

export interface ActivityDisclosureEntry {
  id: string;
  text: string;
  tone?: "accent" | "muted" | "default";
  activityKind?: string | null;
  durationMs?: number | null;
}

export function ActivityDisclosure({
  label,
  entries,
  open,
  onToggle,
  className = "",
  ongoing = false,
}: {
  label: string;
  entries: readonly ActivityDisclosureEntry[];
  ongoing?: boolean;
  open?: boolean;
  onToggle?: (open: boolean) => void;
  className?: string;
}) {
  const disclosureRef = useRef<HTMLDetailsElement>(null);
  return (
    <details
      ref={disclosureRef}
      className={`${styles.frameActivity} ${className}`}
      data-ongoing={ongoing}
      {...(open === undefined ? {} : { open })}
      onToggle={(event) => {
        const expanded = event.currentTarget.open;
        onToggle?.(expanded);
        if (expanded) window.requestAnimationFrame(() => disclosureRef.current?.scrollIntoView({ block: "nearest", behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" }));
      }}
    >
      <summary>
        <span role={ongoing ? "status" : undefined} aria-live={ongoing ? "polite" : undefined} aria-atomic={ongoing ? true : undefined} aria-label={ongoing ? label : undefined}>
          <span key={label} className={styles.frameActivityLabel}>
            {ongoing ? <ShinyText color="var(--chat-accent)">{label}</ShinyText> : label}
          </span>
        </span>
        <span className={styles.frameActivityChevron} aria-hidden="true"><ChevronIcon /></span>
      </summary>
      <div className={styles.frameActivityReveal}>
        <div className={styles.frameActivityEntries}>
          {entries.map((entry) => (
            <div className={`${styles.frameActivityEntry} ${entry.tone === "accent" ? styles.frameActivityAccent : entry.tone === "muted" ? styles.frameActivityMuted : ""}`} key={entry.id}>
              <ActivityIcon kind={entry.activityKind} tone={entry.tone} />
              <span>{entry.text}</span>
              {entry.durationMs != null ? <small>{entry.durationMs > 0 && entry.durationMs < 1000 ? "<1" : Math.round(entry.durationMs / 1000)}s</small> : null}
            </div>
          ))}
        </div>
      </div>
    </details>
  );
}

export function QueueStack({
  items,
  onRemove,
  actionLabel = "",
  actionId,
  onAction,
  onAttachmentOpen,
}: {
  items: readonly { id: string; content: string; removable?: boolean; statusLabel?: string | null; attachments?: QueuedAttachmentPreview[] }[];
  onRemove?: (id: string) => void;
  actionLabel?: string;
  actionId?: string;
  onAction?: (id: string) => void;
  onAttachmentOpen?: (file: QueuedAttachmentPreview) => void;
}) {
  const reducedMotion = useReducedMotion();
  const duration = reducedMotion ? 0 : .32;
  return (
    <ol className={`${styles.frameQueue} ${styles.frameQueueSmooth}`} aria-label="Queued messages">
      <AnimatePresence initial={false}>
      {items.map((item, index) => (
        <motion.li className={styles.frameQueueItem} key={item.id} initial={{ height: 0, marginTop: 0 }} animate={{ height: 48, marginTop: index === 0 ? 0 : 8 }} exit={{ height: 0, marginTop: 0 }} transition={{ duration, ease: [.25, 1, .5, 1] }}>
          <motion.div className={styles.frameQueuePill} initial={{ opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -3 }} transition={{ duration: duration * .65, ease: [.25, 1, .5, 1] }}>
            {item.attachments?.length ? (
              <span className={styles.frameQueueThumbs} title={item.attachments.map((file) => file.name).join(", ")}>
                {item.attachments.slice(0, 3).map((file) => {
                  const thumb = file.src
                    ? <img src={file.src} alt="" />
                    : <FileIcon />;
                  return !file.src && file.ready && !file.local && onAttachmentOpen ? (
                    <button key={file.id} type="button" aria-label={`Open ${file.name} preview`} onClick={() => onAttachmentOpen(file)}>
                      {thumb}
                    </button>
                  ) : (
                    <span key={file.id}>{thumb}</span>
                  );
                })}
                {item.attachments.length > 3 ? <span>+{item.attachments.length - 3}</span> : null}
              </span>
            ) : null}
            <span title={item.attachments?.length ? `${item.content} (${item.attachments.map((file) => file.name).join(", ")})` : item.content}>{item.content}</span>
            {actionLabel && onAction && (actionId === undefined || item.id === actionId) ? <button type="button" onClick={() => onAction(item.id)}>{actionLabel}</button> : null}
            {item.statusLabel ? <span aria-label={item.statusLabel}>{item.statusLabel}</span> : null}
            {onRemove && item.removable !== false ? (
              <button type="button" aria-label={`Remove queued message: ${item.content}`} onClick={() => onRemove(item.id)}>
                <TrashIcon />
              </button>
            ) : null}
          </motion.div>
        </motion.li>
      ))}
      </AnimatePresence>
    </ol>
  );
}

export function ConversationComposer({
  allyName,
  value,
  placeholder,
  disabled,
  sending,
  onChange,
  onSubmit,
  onStop,
  onCompositionStart,
  onCompositionEnd,
  attachments,
  onAttach,
  onFilesDrop,
  dropScope,
}: {
  allyName: string;
  value: string;
  placeholder: string;
  disabled: boolean;
  sending: boolean;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onStop?: () => void;
  onCompositionStart?: () => void;
  onCompositionEnd?: (value: string) => void;
  attachments?: ReactNode;
  onAttach?: (anchor: HTMLElement) => void;
  onFilesDrop?: (files: File[], origin: DOMRect) => boolean | void;
  dropScope?: string;
}) {
  const isMobileHome = useIsMobileHome();
  const reduceAttachmentMotion = useReducedMotion();
  const fieldRef = useRef<HTMLTextAreaElement>(null);
  const composerRef = useRef<HTMLDivElement>(null);
  const previewRef = useRef<HTMLDialogElement>(null);
  const [dropActive, setDropActive] = useState(false);
  const [dropMessage, setDropMessage] = useState("");
  const [pasteError, setPasteError] = useState("");
  const isLarge = (text: string) => text.length >= 2_000 || text.split("\n").length >= 20;
  const splitDraft = (text: string) => ({ source: text, prompt: isLarge(text) ? "" : text, paste: isLarge(text) ? text : "" });
  const [parts, setParts] = useState(() => splitDraft(value));
  let draft = parts;
  if (parts.source !== value) {
    draft = splitDraft(value);
    setParts(draft);
  }
  const compact = Boolean(draft.paste);
  const updateParts = (prompt: string, paste: string) => {
    const combined = prompt && paste ? `${prompt}\n\n${paste}` : prompt || paste;
    if (combined.length > 16_000) {
      setPasteError("Your prompt and pasted text together can contain up to 16,000 characters.");
      return;
    }
    setPasteError("");
    setParts({ source: combined, prompt, paste });
    onChange(combined);
  };
  const handlePaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    const field = event.currentTarget;
    const pasted = event.clipboardData.getData("text/plain");
    const keepPastedText = () => {
      if (!pasted) return false;
      if (value.length - (field.selectionEnd - field.selectionStart) + pasted.length > 16_000) {
        setPasteError("This paste is too long. Messages can contain up to 16,000 characters; your draft has not changed.");
        return false;
      }
      setPasteError("");
      if (field.id === "ally-message") {
        if (isLarge(pasted)) {
          const prompt = draft.prompt.slice(0, field.selectionStart) + draft.prompt.slice(field.selectionEnd);
          updateParts(prompt, draft.paste ? `${draft.paste}\n\n${pasted}` : pasted);
        } else {
          updateParts(
            draft.prompt.slice(0, field.selectionStart) + pasted + draft.prompt.slice(field.selectionEnd),
            draft.paste,
          );
        }
      } else {
        updateParts(
          draft.prompt,
          draft.paste.slice(0, field.selectionStart) + pasted + draft.paste.slice(field.selectionEnd),
        );
      }
      return true;
    };
    const clipboardItems = Array.from(event.clipboardData.items ?? []);
    const itemImages = clipboardItems
      .filter((item) => item.kind === "file" && item.type.startsWith("image/"))
      .map((item) => item.getAsFile())
      .filter((file): file is File => file !== null);
    const imageFiles = itemImages.length
      ? itemImages
      : Array.from(event.clipboardData.files ?? []).filter((file) => file.type.startsWith("image/"));
    if (imageFiles.length) {
      event.preventDefault();
      const keptText = keepPastedText();
      if (disabled || !onFilesDrop) {
        setDropMessage(
          keptText
            ? "Attachments are unavailable right now. Pasted text was kept."
            : "Attachments are unavailable right now.",
        );
        return;
      }
      try {
        const accepted = onFilesDrop(
          imageFiles,
          composerRef.current?.getBoundingClientRect() ?? field.getBoundingClientRect(),
        );
        setDropMessage(
          accepted === false
            ? keptText
              ? "These images could not be added. Pasted text was kept."
              : "These images could not be added. Your draft has not changed."
            : keptText
              ? "Images and text added to your draft."
              : "Images added to your draft.",
        );
      } catch {
        setDropMessage(
          keptText
            ? "These images could not be added. Pasted text was kept."
            : "These images could not be added. Your draft has not changed.",
        );
      }
      return;
    }
    if (value.length - (field.selectionEnd - field.selectionStart) + pasted.length > 16_000) {
      event.preventDefault();
      setPasteError("This paste is too long. Messages can contain up to 16,000 characters; your draft has not changed.");
    } else {
      setPasteError("");
      if (field.id === "ally-message" && isLarge(pasted)) {
        event.preventDefault();
        const prompt = draft.prompt.slice(0, field.selectionStart) + draft.prompt.slice(field.selectionEnd);
        updateParts(prompt, draft.paste ? `${draft.paste}\n\n${pasted}` : pasted);
      }
    }
  };
  const hasText = Boolean(value.trim()) || Boolean(attachments);
  const [expanded, setExpanded] = useState(value.includes("\n") || value.length > 48);

  useEffect(() => {
    const root = composerRef.current;
    if (!root) return;
    const dropZone = root.closest<HTMLElement>('[data-testid="conversation-frame-shell"]') ?? root;
    const hasFiles = (event: globalThis.DragEvent) =>
      Array.from(event.dataTransfer?.types ?? []).includes("Files");
    const inside = (event: globalThis.DragEvent) => {
      const target = event.target;
      return target instanceof Node && dropZone.contains(target);
    };
    const reset = () => {
      setDropActive(false);
      setDropMessage("");
      dropZone.removeAttribute("data-file-drop-active");
    };
    const filesFrom = (transfer: DataTransfer): File[] | null => {
      const items = transfer.items ? Array.from(transfer.items) : [];
      if (items.length) {
        const fileItems = items.filter((item) => item.kind === "file");
        if (!fileItems.length) return [];
        const files: File[] = [];
        for (const item of fileItems) {
          const entry = (item as DataTransferItem & {
            webkitGetAsEntry?: () => { isDirectory?: boolean } | null;
          }).webkitGetAsEntry?.();
          if (entry?.isDirectory) return null;
          const file = item.getAsFile();
          if (!file) return null;
          files.push(file);
        }
        return files;
      }
      return Array.from(transfer.files ?? []);
    };
    const onDragEnter = (event: globalThis.DragEvent) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      if (!inside(event)) return;
      setDropActive(true);
      dropZone.setAttribute("data-file-drop-active", "true");
      setDropMessage(disabled ? "Attachments are unavailable right now." : "Drop files to attach");
    };
    const onDragOver = (event: globalThis.DragEvent) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      if (inside(event)) {
        event.dataTransfer!.dropEffect = disabled || !onFilesDrop ? "none" : "copy";
        setDropActive(true);
        dropZone.setAttribute("data-file-drop-active", "true");
      }
    };
    const onDragLeave = (event: globalThis.DragEvent) => {
      if (!hasFiles(event)) return;
      const related = event.relatedTarget;
      if (related instanceof Node && dropZone.contains(related)) return;
      if (inside(event) || !(related instanceof Node && dropZone.contains(related))) reset();
    };
    const onDrop = (event: globalThis.DragEvent) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      event.stopPropagation();
      const acceptedTarget = inside(event);
      reset();
      if (!acceptedTarget) {
        setDropMessage("Drop files in the composer to attach them.");
        return;
      }
      if (disabled || !onFilesDrop) {
        setDropMessage("Attachments are unavailable right now.");
        return;
      }
      const files = filesFrom(event.dataTransfer!);
      if (!files?.length) {
        setDropMessage("These files could not be added. Your draft has not changed.");
        return;
      }
      try {
        const accepted = onFilesDrop(files, root.getBoundingClientRect());
        setDropMessage(
          accepted === false
            ? "These files could not be added. Your draft has not changed."
            : "Files added to your draft.",
        );
      } catch {
        setDropMessage("These files could not be added. Your draft has not changed.");
      }
    };
    const onDragEnd = (event: globalThis.DragEvent) => {
      if (hasFiles(event)) reset();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") reset();
    };
    document.addEventListener("dragenter", onDragEnter, true);
    document.addEventListener("dragover", onDragOver, true);
    document.addEventListener("dragleave", onDragLeave, true);
    document.addEventListener("drop", onDrop, true);
    document.addEventListener("dragend", onDragEnd, true);
    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("dragenter", onDragEnter, true);
      document.removeEventListener("dragover", onDragOver, true);
      document.removeEventListener("dragleave", onDragLeave, true);
      document.removeEventListener("drop", onDrop, true);
      document.removeEventListener("dragend", onDragEnd, true);
      document.removeEventListener("keydown", onKeyDown, true);
      reset();
    };
  }, [disabled, dropScope, onFilesDrop]);

  useLayoutEffect(() => {
    const field = fieldRef.current;
    if (!field) return;
    field.style.height = "auto";
    const nextHeight = Math.min(field.scrollHeight, 83);
    field.style.height = `${nextHeight}px`;
    const lineHeight = Number.parseFloat(getComputedStyle(field).lineHeight) || 18.2;
    setExpanded(Boolean(value) && (value.includes("\n") || value.length > 48 || nextHeight > lineHeight + 19));
  }, [value, compact]);

  return (
    <>
    {dropMessage ? <p className={styles.frameComposerNotice} role="status" aria-live="polite" aria-atomic="true">{dropMessage}</p> : null}
    <div
      ref={composerRef}
      className={styles.frameComposer}
      data-testid="conversation-composer"
      data-expanded={compact || expanded || attachments ? "true" : "false"}
      data-has-attachments={attachments ? "true" : undefined}
      data-attachment-enabled={onAttach ? "true" : undefined}
      data-has-paste={compact ? "true" : undefined}
      data-drop-active={dropActive ? "true" : undefined}
    >
      <label className={styles.frameSrOnly} htmlFor="ally-message">Message {allyName}</label>
      {onAttach ? <button type="button" className={styles.frameAttachButton} onClick={event => onAttach(event.currentTarget)} disabled={disabled} aria-label="Add attachment"><img src="/home/chat/plus.svg" alt="" width={13} height={13} /></button> : <span className={styles.frameComposerPlus} aria-hidden="true">
        <img src="/home/chat/plus.svg" alt="" width={13} height={13} />
      </span>}
      <div className={styles.frameComposerContent}>
      <AnimatePresence initial={false}>
        {attachments ? <motion.div
          key="attachments"
          data-attachment-reveal="true"
          initial={{ height: 0 }}
          animate={{ height: "auto" }}
          exit={{ height: 0, opacity: 0 }}
          transition={{ duration: reduceAttachmentMotion ? 0 : .46, ease: [.22, 1, .36, 1] }}
          style={{ overflow: "hidden" }}
        >{attachments}</motion.div> : null}
      </AnimatePresence>
      <AnimatePresence initial={false}>{compact ? <motion.div className={styles.framePasteReveal} initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: reduceAttachmentMotion ? 0 : .2, ease: [.22, 1, .36, 1] }}><div className={styles.framePasteCard}><button
        type="button"
        className={styles.framePastedText}
        disabled={disabled}
        onClick={() => previewRef.current?.showModal()}
        aria-label="Edit pasted text"
      >
        <span aria-hidden="true">≡</span>
        <span><strong>Pasted text</strong><small>{draft.paste.length.toLocaleString()} characters · Click to edit</small></span>
      </button><button type="button" className={styles.frameRemovePaste} aria-label="Remove pasted text" disabled={disabled} onClick={() => updateParts(draft.prompt, "")}><TrashIcon /></button></div></motion.div> : null}</AnimatePresence>
      <textarea
        ref={fieldRef}
        id="ally-message"
        value={draft.prompt}
        onChange={(event) => updateParts(event.target.value, draft.paste)}
        onPaste={handlePaste}
        onCompositionStart={onCompositionStart}
        onCompositionEnd={(event) => onCompositionEnd?.(event.currentTarget.value)}
        onKeyDown={(event) => {
          if (event.nativeEvent.isComposing) return;
          if (event.key === "Enter" && !event.shiftKey && (!isMobileHome || event.ctrlKey || event.metaKey)) {
            event.preventDefault();
            onSubmit();
          }
        }}
        placeholder={compact ? "Add a message…" : placeholder}
        rows={1}
        maxLength={16_000}
        disabled={disabled}
        aria-busy={sending}
      />
      </div>
      {onStop && !hasText ? (
        <button type="button" className={styles.frameStopButton} aria-label="Stop response" onClick={onStop}>
          <motion.span key="stop" initial={{ scale: .5, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ duration: reduceAttachmentMotion ? 0 : .18 }}><StopGlyph /></motion.span>
        </button>
      ) : (
        <button type="button" aria-label="Send message" onClick={onSubmit} disabled={disabled || !hasText}>
          {hasText
            ? <img src="/home/chat/send.svg" alt="" width={16} height={16} />
            : <MicIcon />}
        </button>
      )}
    </div>
    {pasteError ? <p role="alert" className={styles.frameComposerError}>{pasteError}</p> : null}
    <dialog ref={previewRef} className={styles.framePasteDialog} aria-label="Edit pasted text">
      <div className={styles.framePasteHeading}>
        <h2>Pasted text</h2>
        <button type="button" onClick={() => previewRef.current?.close()} aria-label="Close pasted text">×</button>
      </div>
      <p>Edit your text before sending it to {allyName}.</p>
      <textarea
        aria-label="Pasted text content"
        value={draft.paste}
        disabled={disabled}
        maxLength={16_000}
        onPaste={handlePaste}
        onChange={(event) => updateParts(draft.prompt, event.target.value)}
        onCompositionStart={onCompositionStart}
        onCompositionEnd={(event) => onCompositionEnd?.(event.currentTarget.value)}
      />
      {pasteError ? <p role="alert">{pasteError}</p> : null}
      <footer><span>{value.length.toLocaleString()} / 16,000</span><button type="button" onClick={() => previewRef.current?.close()}>Done</button></footer>
    </dialog>
    </>
  );
}

export function FrameError({
  children,
  action,
  onAction,
  role = "alert",
}: {
  children: ReactNode;
  action?: string;
  onAction?: () => void;
  role?: "alert" | "status";
}) {
  return (
    <div className={styles.frameError} role={role}>
      <span>{children}</span>
      {action && onAction ? <button type="button" onClick={onAction}>{action}</button> : null}
    </div>
  );
}

export function AllyFrameAvatar({
  shape,
  accent,
  size = 36,
  state = "idle",
  stateReady = true,
  label = "",
  neutral = false,
}: {
  shape: AllyShape;
  accent: string;
  size?: number;
  state?: "idle" | "thinking" | "sleeping";
  stateReady?: boolean;
  label?: string;
  neutral?: boolean;
}) {
  return <AllyAvatar shape={shape} color={accent} size={size} state={state} stateReady={stateReady} neutral={neutral} label={label} />;
}

export function RoutineCard({
  name,
  schedule,
  onOpen,
}: {
  name: string;
  schedule: string;
  onOpen?: () => void;
}) {
  const content = (
    <>
      <span className={styles.frameRoutineIcon}><RoutineIcon /></span>
      <span className={styles.frameRoutineCopy}>
        <strong>{name}</strong>
        <span> · {schedule}</span>
      </span>
      <svg aria-hidden="true" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M10 3h5v5" /><path d="M3 10v5h5" opacity=".4" /></svg>
    </>
  );
  return onOpen ? <button type="button" className={styles.frameRoutineCard} onClick={onOpen}>{content}</button> : <div className={styles.frameRoutineCard}>{content}</div>;
}

export function RoutineChatProjectionCard({
  name,
  schedule,
  status,
  onOpen,
  children,
}: {
  name: string;
  schedule: string;
  status: string;
  onOpen: () => void;
  children?: ReactNode;
}) {
  const compact = !status && Children.toArray(children).length === 0;
  return (
    <article className={`${styles.frameRoutineProjection} ${compact ? styles.frameRoutineProjectionCompact : ""}`}>
      <RoutineCard name={name} schedule={schedule} onOpen={onOpen} />
      {status ? <div className={styles.frameRoutineProjectionMeta}><span>{status}</span></div> : null}
      {children}
    </article>
  );
}

export interface ProductCardItem {
  id: string;
  name: string;
  price: string;
  color: string;
  alt: string;
}

export function ProductCarousel({
  items,
  onSelect,
}: {
  items: readonly ProductCardItem[];
  onSelect?: (item: ProductCardItem) => void;
}) {
  return (
    <div className={styles.frameProductCarousel} tabIndex={0} aria-label="Products">
      {items.map((item) => {
        const card = (
          <>
            <span className={styles.frameProductImage} style={{ background: item.color }} role="img" aria-label={item.alt}>
              <span className={styles.frameProductIllustration} aria-hidden="true" />
            </span>
            <span className={styles.frameProductMeta}>
              <strong>{item.price}</strong>
              <span>{item.name}</span>
            </span>
          </>
        );
        return onSelect ? <button type="button" className={styles.frameProductCard} key={item.id} onClick={() => onSelect(item)}>{card}</button> : <div className={styles.frameProductCard} key={item.id}>{card}</div>;
      })}
    </div>
  );
}

export function CartSummary({
  restaurant,
  itemCount,
  expanded = false,
  onOpen,
}: {
  restaurant: string;
  itemCount: number;
  expanded?: boolean;
  onOpen?: () => void;
}) {
  const content = (
    <>
      <span className={styles.frameCartStore}><StoreIcon /></span>
      <span className={styles.frameCartRestaurant}>{restaurant}</span>
      <span className={styles.frameCartCount}>{itemCount} items</span>
      <span className={styles.frameCartChevron} aria-hidden="true"><ChevronIcon /></span>
    </>
  );
  return onOpen ? <button type="button" className={`${styles.frameCartSummary} ${expanded ? styles.frameCartExpanded : ""}`} onClick={onOpen}>{content}</button> : <div className={`${styles.frameCartSummary} ${expanded ? styles.frameCartExpanded : ""}`}>{content}</div>;
}

export function BottomSheet({
  title,
  headerContent,
  children,
  onClose,
  labelledBy,
  className = "",
  style,
  modal = false,
  hideHeader = false,
  closeDisabled = false,
  onEscape,
}: {
  title?: string;
  headerContent?: ReactNode;
  children: ReactNode;
  onClose: () => void;
  labelledBy?: string;
  className?: string;
  style?: CSSProperties;
  modal?: boolean;
  hideHeader?: boolean;
  closeDisabled?: boolean;
  onEscape?: () => boolean;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const sheetRef = useRef<HTMLElement>(null);
  const closingRef = useRef(false);
  const reducedMotion = useReducedMotion();
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!modal || !dialog) return;
    const activeElement = document.activeElement;
    restoreFocusRef.current = activeElement instanceof HTMLElement && activeElement !== document.body
      ? activeElement
      : null;
    const shell = dialog.closest(`.${styles.frameShell}`);
    const positionInChat = () => {
      if (!shell) return;
      const { x, y, width, height } = shell.getBoundingClientRect();
      Object.assign(dialog.style, { left: `${x}px`, top: `${y}px`, width: `${width}px`, height: `${height}px` });
    };
    positionInChat();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(positionInChat);
    if (shell) observer?.observe(shell);
    window.addEventListener("resize", positionInChat);
    dialog.showModal();
    const firstFocusable = dialog.querySelector<HTMLElement>("button, [href], input, select, textarea, [tabindex]:not([tabindex=\"-1\"])");
    firstFocusable?.focus();
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", positionInChat);
      if (dialog.open) dialog.close();
      const restore = restoreFocusRef.current;
      restoreFocusRef.current = null;
      if (restore?.isConnected) window.requestAnimationFrame(() => restore.focus());
    };
  }, [modal]);
  const label = labelledBy ?? (title ? "conversation-sheet-title" : undefined);
  const handleClose = async () => {
    if (closeDisabled) return;
    if (closingRef.current) return;
    const root = dialogRef.current;
    if (!reducedMotion && root?.animate && sheetRef.current?.animate) {
      closingRef.current = true;
      const options = { duration: 140, easing: "cubic-bezier(0.23, 1, 0.32, 1)", fill: "forwards" as const };
      const animations = [
        root.animate([{ opacity: 1 }, { opacity: 0 }], options),
        sheetRef.current.animate([{ transform: "translateY(0)" }, { transform: "translateY(8px)" }], options),
      ];
      await Promise.allSettled(animations.map((animation) => animation.finished));
    }
    onClose();
  };
  const content = (
        <section
          ref={sheetRef}
          className={styles.frameSheet}
          role={modal ? undefined : "dialog"}
          aria-modal={modal ? undefined : true}
          aria-labelledby={modal ? undefined : label}
        >
        {hideHeader ? null : <div className={styles.frameSheetTop}>
          {headerContent ?? (title ? <h2 id={labelledBy ?? "conversation-sheet-title"}>{title}</h2> : <span />)}
          <button type="button" className={styles.frameSheetClose} aria-label="Close" disabled={closeDisabled} onClick={() => void handleClose()}><CloseIcon /></button>
        </div>}
        {children}
      </section>
  );
  return modal ? <dialog ref={dialogRef} style={style} className={`${styles.frameOverlay} ${styles.frameNativeSheet} ${className}`} aria-labelledby={label} onCancel={(event) => { event.preventDefault(); if (onEscape?.()) return; void handleClose(); }}>{content}</dialog>
    : <div className={`${styles.frameOverlay} ${className}`} style={style} role="presentation">{content}</div>;
}

export function ApprovalSheet({
  onClose,
  onReject,
  onApprove,
}: {
  onClose: () => void;
  onReject: () => void;
  onApprove: () => void;
}) {
  return (
    <BottomSheet onClose={onClose} labelledBy="approval-title" className={styles.frameApprovalOverlay}>
      <h2 id="approval-title" className={styles.frameSheetQuestion}>Allow Sally perform this specific action that requires manual approval?</h2>
      <div className={styles.frameSheetActions}>
        <button type="button" className={styles.frameNeutralAction} onClick={onReject}>Reject</button>
        <button type="button" className={styles.frameAccentAction} onClick={onApprove}>Approve</button>
      </div>
    </BottomSheet>
  );
}

export type FilePreviewState = "loading" | "ready" | "error";

export function ImageLightbox({
  onClose,
  alt,
  fileName,
  mime,
  sizeBytes,
  state = "ready",
  src,
  text,
  onRetry,
}: {
  onClose: () => void;
  alt: string;
  fileName?: string;
  mime?: string;
  sizeBytes?: number;
  state?: FilePreviewState;
  src?: string;
  text?: string;
  onRetry?: () => void;
}) {
  const normalizedMime = mime?.split(";")[0]?.trim().toLowerCase() ?? "";
  const isImage = normalizedMime.startsWith("image/");
  const isPdf = normalizedMime === "application/pdf";
  const isAudio = normalizedMime.startsWith("audio/");
  const isVideo = normalizedMime.startsWith("video/");
  const isTextLike =
    normalizedMime.startsWith("text/") ||
    normalizedMime === "application/json" ||
    normalizedMime === "text/markdown" ||
    normalizedMime === "text/csv";
  const label = fileName ? `${fileName} preview` : "Image preview";
  const isLegacyPlaceholder = !fileName && !src && !mime;
  const isUnsupported = !isLegacyPlaceholder && (
    (!isImage || !src) && (!isPdf || !src) && (!isAudio || !src) && (!isVideo || !src) && !(isTextLike && text !== undefined)
  );
  return (
    <div className={styles.frameLightbox} role="dialog" aria-modal="true" aria-label={label} aria-busy={state === "loading"}>
      {state === "loading" ? (
        <div className={styles.framePreviewSkeleton} role="status" aria-label="Loading preview" />
      ) : state === "error" ? (
        <div className={styles.framePreviewUnsupported} role="alert">
          <strong>{fileName ?? alt}</strong>
          {sizeBytes !== undefined ? <span>{formatFileSize(sizeBytes)}</span> : null}
          <span>Preview failed to load.</span>
          {onRetry ? <button type="button" className={styles.frameAccentAction} onClick={onRetry}>Try again</button> : null}
        </div>
      ) : isImage && src ? (
        <img className={styles.framePreviewImage} src={src} alt={alt} />
      ) : isPdf && src ? (
        <iframe className={styles.framePreviewFrame} src={src} title={fileName ?? alt} sandbox="allow-same-origin" />
      ) : isAudio && src ? (
        <audio className={styles.framePreviewMedia} src={src} controls aria-label={fileName ?? alt} />
      ) : isVideo && src ? (
        <video className={styles.framePreviewMedia} src={src} controls aria-label={fileName ?? alt} />
      ) : isTextLike && text !== undefined ? (
        <pre className={styles.framePreviewText}>{text}</pre>
      ) : isUnsupported ? (
        <div className={styles.framePreviewUnsupported}>
          <strong>{fileName ?? alt}</strong>
          {sizeBytes !== undefined ? <span>{formatFileSize(sizeBytes)}</span> : null}
          {src ? (
            <span className={styles.frameSheetActions}>
              <a className={styles.frameNeutralAction} href={src} target="_blank" rel="noopener noreferrer">Open</a>
              <a className={styles.frameAccentAction} href={src} download={fileName}>Download</a>
            </span>
          ) : (
            <span>No preview available for this file type.</span>
          )}
        </div>
      ) : (
        <div className={styles.frameLargeImage} role="img" aria-label={alt}>
          <span className={styles.frameLargeImageShape} aria-hidden="true" />
        </div>
      )}
      {fileName && state === "ready" && !isUnsupported ? (
        <p className={styles.framePreviewMeta}>
          <strong>{fileName}</strong>
          {sizeBytes !== undefined ? <span>{formatFileSize(sizeBytes)}</span> : null}
        </p>
      ) : null}
      <button type="button" className={styles.frameLightboxClose} aria-label="Close preview" onClick={onClose}><CloseIcon /></button>
    </div>
  );
}

export function CartEditor({
  itemCount,
  quantity,
  onQuantityChange,
  onDone,
}: {
  itemCount: number;
  quantity: number;
  onQuantityChange: (next: number) => void;
  onDone: () => void;
}) {
  return (
    <section className={styles.frameCartEditor} aria-label="Cart editor">
      <div className={styles.frameCartEditorHeader}>
        <strong>{itemCount} items</strong>
        <button type="button" aria-label="Close cart editor" onClick={onDone}><CloseIcon /></button>
      </div>
      <div className={styles.frameCartEditorItem}>
        <span className={styles.frameCartThumb} role="img" aria-label="Product image"><span /></span>
        <span className={styles.frameProductMeta}><strong>$20</strong><span>Product name</span></span>
        <span className={styles.frameQuantityControls}>
          <button type="button" aria-label="Decrease quantity" onClick={() => onQuantityChange(Math.max(0, quantity - 1))} disabled={quantity <= 0}><MinusIcon /></button>
          <span aria-live="polite">{quantity}</span>
          <button type="button" aria-label="Increase quantity" onClick={() => onQuantityChange(Math.min(9, quantity + 1))}><PlusIcon /></button>
        </span>
      </div>
      <button type="button" className={styles.frameDoneAction} onClick={onDone}>Done</button>
    </section>
  );
}

export function RoutineDetail({
  onClose,
  onDelete,
  title = "Routine name goes in this text box",
  startsAt = "26 Jun 2026",
  repeats = "Every Monday",
  tool = "Gmail",
}: {
  onClose: () => void;
  onDelete: () => void;
  title?: string;
  startsAt?: string | null;
  repeats?: string | null;
  tool?: string | null;
}) {
  const rows = [
    startsAt ? ["Starts", startsAt] : null,
    repeats ? ["Repeats", repeats] : null,
    tool ? ["Tool", tool] : null,
  ].filter((row): row is [string, string] => row !== null);
  return (
    <section className={styles.frameRoutineDetail} aria-label="Routine details">
      <div className={styles.frameRoutineDetailHeader}>
        <span className={styles.frameRoutineIcon}><RoutineIcon /></span>
        <button type="button" className={styles.frameSheetClose} aria-label="Close routine" onClick={onClose}><CloseIcon /></button>
      </div>
      <h2 id="routine-detail-title">{title}</h2>
      <div className={styles.frameRoutineRows}>
        {rows.map(([label, value]) => <div key={label}><strong>{label}</strong><span>{value}</span></div>)}
      </div>
      <button type="button" className={styles.frameAccentAction} onClick={onDelete}>Delete</button>
    </section>
  );
}

export function RoutineChatDetail({
  title,
  schedule,
  scheduleState,
  nextRunAt,
  executionPrompt,
  startsAt,
  repeats,
  timezone,
  tool,
  canPauseResume,
  canDelete,
  pauseResumeLabel,
  actionPending = false,
  actionSent = false,
  onPauseResume,
  onDelete,
  deleteButtonRef,
}: {
  title: string;
  schedule: string;
  scheduleState: string;
  nextRunAt: string | null;
  executionPrompt: string;
  startsAt?: string | null;
  repeats?: string | null;
  timezone?: string | null;
  tool?: string | null;
  canPauseResume: boolean;
  canDelete: boolean;
  pauseResumeLabel: "Pause" | "Resume" | null;
  actionPending?: boolean;
  actionSent?: boolean;
  onPauseResume: () => void;
  onDelete: () => void;
  deleteButtonRef?: Ref<HTMLButtonElement>;
}) {
  const promptId = useId();
  const reducedMotion = useReducedMotion();
  const [promptOpen, setPromptOpen] = useState(false);
  const actionLocked = actionPending || actionSent;
  const rows = [
    startsAt ? ["Starts", startsAt] : null,
    repeats ? ["Repeats", repeats] : schedule ? ["Schedule", schedule] : null,
    timezone ? ["Timezone", timezone] : null,
    tool ? ["Tool", tool] : null,
    scheduleState ? ["State", scheduleState] : null,
    nextRunAt ? ["Next run", nextRunAt] : null,
  ].filter((row): row is [string, string] => row !== null);
  return (
    <section className={styles.frameRoutineDetail} aria-label="Routine details">
      <div className={styles.frameRoutineDetailHeader}>
        <span className={styles.frameRoutineIcon}><RoutineIcon /></span>
      </div>
      <h2>{title}</h2>
      <div className={styles.frameRoutineRows}>
        {rows.map(([label, value]) => <div key={label}><strong>{label}</strong><span>{value}</span></div>)}
      </div>
      <div className={styles.frameRoutinePrompt}>
        <button type="button" className={styles.frameRoutinePromptTrigger} aria-expanded={promptOpen} aria-controls={promptId} onClick={() => setPromptOpen(value => !value)}>Full prompt<span aria-hidden="true" /></button>
        <motion.div id={promptId} initial={false} animate={{ height: promptOpen ? "auto" : 0, opacity: promptOpen ? 1 : 0 }} transition={{ duration: reducedMotion ? 0 : .2, ease: [.22, 1, .36, 1] }} className={styles.frameRoutinePromptReveal} aria-hidden={!promptOpen}><p>{executionPrompt}</p></motion.div>
      </div>
      <AnimatePresence initial={false}>{actionSent ? <motion.p key="sent" className={styles.frameRoutineActionNotice} role="status" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: reducedMotion ? 0 : .16 }}>Request sent to Ally.</motion.p> : null}</AnimatePresence>
      <div className={styles.frameRoutineActionGroup}>
        {canPauseResume && pauseResumeLabel ? (
          <button type="button" className={styles.frameNeutralAction} onClick={onPauseResume} disabled={actionLocked}>
            <motion.span key={actionPending ? "sending" : pauseResumeLabel} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: reducedMotion ? 0 : .12 }}>{actionPending ? "Sending…" : pauseResumeLabel}</motion.span>
          </button>
        ) : null}
        {canDelete ? (
          <button ref={deleteButtonRef} type="button" className={styles.frameAccentAction} onClick={onDelete} disabled={actionLocked}>
            {actionPending ? "Sending…" : "Delete"}
          </button>
        ) : null}
      </div>
    </section>
  );
}

export function RoutineRunDetail({ title, status, schedule, triggeredAt, reportedAt, failed, text }: {
  title: string; status: string; schedule: string; triggeredAt: string | null;
  reportedAt: string | null; failed: boolean; text: string | null;
}) {
  return <section className={styles.frameRoutineDetail} aria-label="Routine run details">
    <div className={styles.frameRoutineDetailHeader}><span className={styles.frameRoutineIcon}><RoutineIcon /></span></div>
    <h2>{title}</h2>
    <div className={styles.frameRoutineRows}>
      <div><strong>Run status</strong><span>{status}</span></div>
      <div><strong>Schedule</strong><span>{schedule}</span></div>
      <div><strong>Triggered</strong><span>{triggeredAt ?? "Not reported"}</span></div>
      {reportedAt ? <div><strong>Result received</strong><span>{reportedAt}</span></div> : null}
    </div>
    {text ? <p className={styles.frameRoutineProjectionText}>{text}</p> : null}
    {failed ? <p className={styles.frameRoutineProjectionDetail}>The exact failure stage was not reported.</p> : null}
  </section>;
}

export function DeleteRoutineSheet({
  title,
  onCancel,
  onDelete,
  disabled = false,
  embedded = false,
  failed = false,
}: {
  title?: string;
  onCancel: () => void;
  onDelete: () => void;
  disabled?: boolean;
  embedded?: boolean;
  failed?: boolean;
}) {
  const routineTitle = title?.trim() || "routine name goes in here";
  const content = (
    <>
      <span className={styles.frameDeleteIcon}><TrashIcon /></span>
      <h2 id="delete-routine-title" className={styles.frameDeleteQuestion}>Are you sure you want to delete {routineTitle}?</h2>
      {failed ? <p role="alert">The delete request failed. Please try again.</p> : null}
      <div className={styles.frameSheetActions}>
        <button type="button" className={styles.frameNeutralAction} onClick={onCancel} disabled={disabled}>Cancel</button>
        <button type="button" className={styles.frameAccentAction} onClick={onDelete} disabled={disabled}>Delete</button>
      </div>
    </>
  );
  return embedded ? content : <BottomSheet onClose={onCancel} labelledBy="delete-routine-title">{content}</BottomSheet>;
}

export function BackIcon() {
  return <FrameIcon name="back" />;
}

export function SettingsIcon() {
  return <FrameIcon name="settings" className={styles.frameSettingsIcon} />;
}
export function SendIcon() {
  return <FrameIcon name="send" />;
}

function StopGlyph() {
  return <span className={styles.frameStopGlyph} aria-hidden="true" />;
}

export function MicIcon() {
  return <FrameIcon name="mic" />;
}

export function PlusIcon() {
  return <FrameIcon name="plus" />;
}

function MinusIcon() {
  return <FrameIcon name="minus" />;
}

function TrashIcon() {
  return <svg aria-hidden="true" focusable="false" viewBox="0 0 18 18"><use href="/ally/icons/chat-queue-trash.svg#icon" /></svg>;
}

function CloseIcon() {
  return <FrameIcon name="close" />;
}

function ChevronIcon() {
  return <FrameIcon name="chevron" />;
}

function RoutineIcon() {
  return <FrameIcon name="routine" />;
}

function StoreIcon() {
  return <FrameIcon name="store" />;
}

type FrameIconName = "back" | "settings" | "settings-desktop" | "send" | "mic" | "plus" | "minus" | "trash" | "close" | "chevron" | "routine" | "store";

function FrameIcon({ name, className = "" }: { name: FrameIconName; className?: string }) {
  return (
    <svg className={className} aria-hidden="true" focusable="false" viewBox="0 0 24 24">
      <use href={`/ally/icons/chat-${name}.svg#icon`} />
    </svg>
  );
}
