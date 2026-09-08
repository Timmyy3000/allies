import { useEffect, useLayoutEffect, useRef, useState, type ClipboardEvent, type CSSProperties, type ReactNode, type Ref, type UIEvent } from "react";
import Link from "next/link";

import { AllyAvatar, type AllyShape } from "../../components/ally-avatar";
import { ShinyText } from "../../components/text-animations/shiny-text";

import styles from "./conversation-frame.module.css";
import { useIsMobileHome } from "./use-is-mobile-home";
import { ActivityIcon } from "./activity-icon";

export type FrameAvatar = ReactNode;

export function readableAccentForeground(accent: string) {
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
  sleeping = false,
  statusContent,
}: {
  name: string;
  subtitle: string;
  avatar: FrameAvatar;
  sleepingAvatar?: FrameAvatar;
  homeHref?: string;
  settingsHref?: string;
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
      <Link className={`${styles.frameIconHit} ${styles.frameSettingsMobile}`} href={settingsHref} aria-label="Account settings">
        <SettingsIcon />
      </Link>
        <span className={styles.frameSettingsDesktop}>
          <FrameIcon name="settings-desktop" className={styles.frameSettingsIcon} />
        <span>{name} settings</span>
      </span>
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
      {timestamp ? <time className={styles.frameMessageTimestamp} data-visible={timestamp.visible} dateTime={createdAt}>{timestamp.label}</time> : null}
    </article>
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
  return <article className={`${styles.frameAssistantMessage} ${className}`} data-testid={testId} tabIndex={timestamp ? 0 : undefined} onClick={timestamp?.reveal} onFocus={timestamp?.reveal} onKeyDown={(event) => {
    if (event.target !== event.currentTarget || !timestamp || !["Enter", " "].includes(event.key)) return;
    event.preventDefault();
    timestamp.reveal();
  }}>
    <div>{children}</div>
    {timestamp ? <time className={styles.frameMessageTimestamp} data-visible={timestamp.visible} dateTime={createdAt}>{timestamp.label}</time> : null}
  </article>;
}

function useTimestampReveal(createdAt?: string) {
  const date = createdAt ? new Date(createdAt) : null;
  const valid = date && !Number.isNaN(date.getTime());
  const [visible, setVisible] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  if (!valid) return null;
  return {
    label: new Intl.DateTimeFormat([], { dateStyle: "medium", timeStyle: "medium" }).format(date),
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
        <span role={ongoing ? "status" : undefined} aria-live={ongoing ? "polite" : undefined} aria-atomic={ongoing ? true : undefined}>
          <span key={label} className={styles.frameActivityLabel}>
            {ongoing ? <ShinyText color="var(--chat-accent)">{label}</ShinyText> : label}
          </span>
        </span>
        <span className={styles.frameActivityChevron} aria-hidden="true"><ChevronIcon /></span>
      </summary>
      <div className={styles.frameActivityEntries}>
        {entries.map((entry) => (
          <div className={`${styles.frameActivityEntry} ${entry.tone === "accent" ? styles.frameActivityAccent : entry.tone === "muted" ? styles.frameActivityMuted : ""}`} key={entry.id}>
            <ActivityIcon kind={entry.activityKind} tone={entry.tone} />
            <span>{entry.text}</span>
            {entry.durationMs != null ? <small>{entry.durationMs > 0 && entry.durationMs < 1000 ? "<1" : Math.round(entry.durationMs / 1000)}s</small> : null}
          </div>
        ))}
      </div>
    </details>
  );
}

export function QueueStack({
  items,
  onRemove,
  actionLabel = "",
  onAction,
}: {
  items: readonly { id: string; content: string; removable?: boolean; statusLabel?: string | null }[];
  onRemove?: (id: string) => void;
  actionLabel?: string;
  onAction?: () => void;
}) {
  return (
    <ol className={styles.frameQueue} aria-label="Queued messages">
      {items.map((item) => (
        <li className={styles.frameQueuePill} key={item.id}>
          <span title={item.content}>{item.content}</span>
          {actionLabel && onAction ? <button type="button" onClick={onAction}>{actionLabel}</button> : null}
          {item.statusLabel ? <span aria-label={item.statusLabel}>{item.statusLabel}</span> : null}
          {onRemove && item.removable !== false ? (
            <button type="button" aria-label={`Remove queued message: ${item.content}`} onClick={() => onRemove(item.id)}>
              <TrashIcon />
            </button>
          ) : null}
        </li>
      ))}
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
  onCompositionStart,
  onCompositionEnd,
}: {
  allyName: string;
  value: string;
  placeholder: string;
  disabled: boolean;
  sending: boolean;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onCompositionStart?: () => void;
  onCompositionEnd?: (value: string) => void;
}) {
  const isMobileHome = useIsMobileHome();
  const fieldRef = useRef<HTMLTextAreaElement>(null);
  const previewRef = useRef<HTMLDialogElement>(null);
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
  const hasText = Boolean(value.trim());
  const [expanded, setExpanded] = useState(value.includes("\n") || value.length > 48);

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
    <div
      className={styles.frameComposer}
      data-testid="conversation-composer"
      data-expanded={compact || expanded ? "true" : "false"}
      data-has-paste={compact ? "true" : undefined}
    >
      <label className={styles.frameSrOnly} htmlFor="ally-message">Message {allyName}</label>
      <span className={styles.frameComposerPlus} aria-hidden="true">
        <img src="/home/chat/plus.svg" alt="" width={13} height={13} />
      </span>
      <div className={styles.frameComposerContent}>
      {compact ? <div className={styles.framePasteCard}><button
        type="button"
        className={styles.framePastedText}
        disabled={disabled}
        onClick={() => previewRef.current?.showModal()}
        aria-label="Edit pasted text"
      >
        <span aria-hidden="true">≡</span>
        <span><strong>Pasted text</strong><small>{draft.paste.length.toLocaleString()} characters · Click to edit</small></span>
      </button><button type="button" className={styles.frameRemovePaste} aria-label="Remove pasted text" disabled={disabled} onClick={() => updateParts(draft.prompt, "")}><TrashIcon /></button></div> : null}
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
          if (!isMobileHome && event.key === "Enter" && !event.shiftKey) {
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
      <button type="button" aria-label="Send message" onClick={onSubmit} disabled={disabled || !hasText}>
        {hasText
          ? <img src="/home/chat/send.svg" alt="" width={16} height={16} />
          : <MicIcon />}
      </button>
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
      <span className={styles.frameRoutineIcon}><CalendarIcon /></span>
      <span className={styles.frameRoutineCopy}>
        <strong>{name}</strong>
        <span>{schedule}</span>
      </span>
      <ChevronIcon />
    </>
  );
  return onOpen ? <button type="button" className={styles.frameRoutineCard} onClick={onOpen}>{content}</button> : <div className={styles.frameRoutineCard}>{content}</div>;
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
  children,
  onClose,
  labelledBy,
  className = "",
  modal = false,
}: {
  title?: string;
  children: ReactNode;
  onClose: () => void;
  labelledBy?: string;
  className?: string;
  modal?: boolean;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!modal || !dialog) return;
    dialog.showModal();
    return () => dialog.close();
  }, [modal]);
  const label = labelledBy ?? (title ? "conversation-sheet-title" : undefined);
  const content = (
        <section
          className={styles.frameSheet}
          role={modal ? undefined : "dialog"}
          aria-modal={modal ? undefined : true}
          aria-labelledby={modal ? undefined : label}
        >
        <div className={styles.frameSheetTop}>
          {title ? <h2 id={labelledBy ?? "conversation-sheet-title"}>{title}</h2> : <span />}
          <button type="button" className={styles.frameSheetClose} aria-label="Close" onClick={onClose}><CloseIcon /></button>
        </div>
        {children}
      </section>
  );
  return modal ? <dialog ref={dialogRef} className={`${styles.frameOverlay} ${styles.frameNativeSheet} ${className}`} aria-labelledby={label} onCancel={(event) => { event.preventDefault(); onClose(); }}>{content}</dialog>
    : <div className={`${styles.frameOverlay} ${className}`} role="presentation">{content}</div>;
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

export function ImageLightbox({
  onClose,
  alt,
}: {
  onClose: () => void;
  alt: string;
}) {
  return (
    <div className={styles.frameLightbox} role="dialog" aria-modal="true" aria-label="Image preview">
      <div className={styles.frameLargeImage} role="img" aria-label={alt}>
        <span className={styles.frameLargeImageShape} aria-hidden="true" />
      </div>
      <button type="button" className={styles.frameLightboxClose} aria-label="Close image" onClick={onClose}><CloseIcon /></button>
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

export function RoutineDetail({ onClose, onDelete }: { onClose: () => void; onDelete: () => void }) {
  return (
    <section className={styles.frameRoutineDetail} aria-label="Routine details">
      <div className={styles.frameRoutineDetailHeader}>
        <span className={styles.frameRoutineIcon}><CalendarIcon /></span>
        <button type="button" className={styles.frameSheetClose} aria-label="Close routine" onClick={onClose}><CloseIcon /></button>
      </div>
      <h2 id="routine-detail-title">Routine name goes in this text box</h2>
      <div className={styles.frameRoutineRows}>
        <div><strong>Starts</strong><span>26 Jun 2026</span></div>
        <div><strong>Repeats</strong><span>Every Monday</span></div>
        <div><strong>Tool</strong><span>Gmail</span></div>
      </div>
      <button type="button" className={styles.frameAccentAction} onClick={onDelete}>Delete</button>
    </section>
  );
}

export function DeleteRoutineSheet({ onCancel, onDelete }: { onCancel: () => void; onDelete: () => void }) {
  return (
    <BottomSheet onClose={onCancel} labelledBy="delete-routine-title">
      <h2 id="delete-routine-title" className={styles.frameDeleteQuestion}>Are you sure you want to delete routine name goes in here?</h2>
      <div className={styles.frameSheetActions}>
        <button type="button" className={styles.frameNeutralAction} onClick={onCancel}>Cancel</button>
        <button type="button" className={styles.frameAccentAction} onClick={onDelete}>Delete</button>
      </div>
    </BottomSheet>
  );
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

function CalendarIcon() {
  return <FrameIcon name="calendar" />;
}

function StoreIcon() {
  return <FrameIcon name="store" />;
}

type FrameIconName = "back" | "settings" | "settings-desktop" | "send" | "mic" | "plus" | "minus" | "trash" | "close" | "chevron" | "calendar" | "store";

function FrameIcon({ name, className = "" }: { name: FrameIconName; className?: string }) {
  return (
    <svg className={className} aria-hidden="true" focusable="false" viewBox="0 0 24 24">
      <use href={`/ally/icons/chat-${name}.svg#icon`} />
    </svg>
  );
}
