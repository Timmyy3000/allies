import { useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode, type Ref, type UIEvent } from "react";
import Link from "next/link";

import { AllyAvatar, type AllyShape } from "../../components/ally-avatar";
import { ShinyText } from "../../components/text-animations/shiny-text";

import styles from "./conversation-frame.module.css";

export type FrameAvatar = ReactNode;

export function ConversationShell({
  accent,
  children,
  className = "",
  safeArea,
  scrolled = false,
}: {
  accent: string;
  children: ReactNode;
  className?: string;
  safeArea?: { top?: string; bottom?: string };
  scrolled?: boolean;
}) {
  const style = {
    "--chat-accent": accent,
    ...(safeArea?.top ? { "--chat-safe-top": safeArea.top } : {}),
    ...(safeArea?.bottom ? { "--chat-safe-bottom": safeArea.bottom } : {}),
  } as CSSProperties;
  return (
    <div
      className={`${styles.frameShell} ${className}`}
      data-testid="conversation-frame-shell"
      style={style}
    >
      {scrolled ? <div className={styles.frameScrollBlur} data-testid="conversation-frame-scroll-blur" aria-hidden="true" /> : null}
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
}: {
  name: string;
  subtitle: string;
  avatar: FrameAvatar;
  sleepingAvatar?: FrameAvatar;
  homeHref?: string;
  settingsHref?: string;
  sleeping?: boolean;
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
      {sleeping ? (
        <div className={styles.frameSleepingStatus} data-testid="ally-sleeping-status">
          <span className={styles.frameSleepingAvatar}>{sleepingAvatar ?? avatar}</span>
          <span>{name} is asleep</span>
        </div>
      ) : null}
      <Link className={`${styles.frameIconHit} ${styles.frameSettingsMobile}`} href={settingsHref} aria-label="Account settings">
        <SettingsIcon />
      </Link>
      <span className={styles.frameSettingsDesktop}>
        <SettingsIcon />
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
  return (
    <div ref={canvasRef} className={`${styles.frameCanvas} ${className}`} onScroll={onScroll} data-testid="conversation-frame-canvas">
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
  status,
  retryable = false,
  retrying = false,
  onRetry,
  className = "",
}: {
  children: ReactNode;
  status?: string | null;
  retryable?: boolean;
  retrying?: boolean;
  onRetry?: () => void;
  className?: string;
}) {
  const textRef = useRef<HTMLParagraphElement>(null);
  const [multiline, setMultiline] = useState(false);

  useLayoutEffect(() => {
    const node = textRef.current;
    if (!node) return;
    setMultiline(node.getBoundingClientRect().height > 20);
  }, [children]);

  return (
    <article
      className={`${styles.frameUserBubble} ${className}`}
      data-multiline={multiline ? "true" : "false"}
    >
      <p ref={textRef}>{children}</p>
      {status ? <span className={styles.frameBubbleStatus}>{status}</span> : null}
      {retryable && onRetry ? (
        <button type="button" className={styles.frameRetryButton} onClick={onRetry} disabled={retrying}>
          {retrying ? "Retrying…" : "Retry"}
        </button>
      ) : null}
    </article>
  );
}

export function AssistantMessage({
  children,
  className = "",
  testId,
}: {
  children: ReactNode;
  className?: string;
  testId?: string;
}) {
  return <article className={`${styles.frameAssistantMessage} ${className}`} data-testid={testId}><div>{children}</div></article>;
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
}

export function ActivityDisclosure({
  label,
  entries,
  open,
  onToggle,
  className = "",
}: {
  label: string;
  entries: readonly ActivityDisclosureEntry[];
  open?: boolean;
  onToggle?: (open: boolean) => void;
  className?: string;
}) {
  return (
    <details
      className={`${styles.frameActivity} ${className}`}
      {...(open === undefined ? {} : { open })}
      onToggle={(event) => onToggle?.(event.currentTarget.open)}
    >
      <summary>
        <span className={styles.frameActivityChevron} aria-hidden="true"><ChevronIcon /></span>
        <span>{label}</span>
      </summary>
      <div className={styles.frameActivityEntries}>
        {entries.map((entry) => (
          <div className={`${styles.frameActivityEntry} ${entry.tone === "accent" ? styles.frameActivityAccent : entry.tone === "muted" ? styles.frameActivityMuted : ""}`} key={entry.id}>
            <span className={styles.frameActivityDot} aria-hidden="true" />
            <span>{entry.text}</span>
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
  items: readonly { id: string; content: string }[];
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
          {onRemove ? (
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
  const fieldRef = useRef<HTMLTextAreaElement>(null);
  const hasText = Boolean(value.trim());
  const [expanded, setExpanded] = useState(value.includes("\n") || value.length > 48);

  useLayoutEffect(() => {
    const field = fieldRef.current;
    if (!field) return;
    field.style.height = "auto";
    const nextHeight = Math.min(field.scrollHeight, 83);
    field.style.height = `${nextHeight}px`;
    setExpanded(value.includes("\n") || value.length > 48 || nextHeight > 36);
  }, [value]);

  return (
    <div
      className={styles.frameComposer}
      data-testid="conversation-composer"
      data-expanded={expanded ? "true" : "false"}
    >
      <label className={styles.frameSrOnly} htmlFor="ally-message">Message {allyName}</label>
      <span className={styles.frameComposerPlus} aria-hidden="true">
        <img src="/home/chat/plus.svg" alt="" width={13} height={13} />
      </span>
      <textarea
        ref={fieldRef}
        id="ally-message"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onCompositionStart={onCompositionStart}
        onCompositionEnd={(event) => onCompositionEnd?.(event.currentTarget.value)}
        onKeyDown={(event) => {
          if (event.nativeEvent.isComposing) return;
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            onSubmit();
          }
        }}
        placeholder={placeholder}
        rows={1}
        maxLength={16_000}
        disabled={disabled}
        aria-busy={sending}
      />
      <button type="button" aria-label="Send message" onClick={onSubmit} disabled={disabled || sending || !hasText}>
        {hasText
          ? <img src="/home/chat/send.svg" alt="" width={16} height={16} />
          : <MicIcon />}
      </button>
    </div>
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
}: {
  title?: string;
  children: ReactNode;
  onClose: () => void;
  labelledBy?: string;
  className?: string;
}) {
  return (
    <div className={`${styles.frameOverlay} ${className}`} role="presentation">
        <section
          className={styles.frameSheet}
          role="dialog"
          aria-modal="true"
          aria-labelledby={labelledBy ?? (title ? "conversation-sheet-title" : undefined)}
        >
        <div className={styles.frameSheetTop}>
          {title ? <h2 id={labelledBy ?? "conversation-sheet-title"}>{title}</h2> : <span />}
          <button type="button" className={styles.frameSheetClose} aria-label="Close" onClick={onClose}><CloseIcon /></button>
        </div>
        {children}
      </section>
    </div>
  );
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
  return <FrameIcon name="trash" />;
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

type FrameIconName = "back" | "settings" | "send" | "mic" | "plus" | "minus" | "trash" | "close" | "chevron" | "calendar" | "store";

function FrameIcon({ name, className = "" }: { name: FrameIconName; className?: string }) {
  return (
    <svg className={className} aria-hidden="true" focusable="false" viewBox="0 0 24 24">
      <use href={`/ally/icons/chat-${name}.svg#icon`} />
    </svg>
  );
}
