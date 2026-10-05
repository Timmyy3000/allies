"use client";

import {
  ActivityDisclosure,
  AllyFrameAvatar,
  ApprovalSheet,
  AssistantIdentity,
  AssistantMessage,
  BottomSheet,
  CartEditor,
  CartSummary,
  ConversationCanvas,
  ConversationComposer,
  ConversationHeader,
  ConversationRail,
  ConversationShell,
  DateDivider,
  DeleteRoutineSheet,
  FrameError,
  ImageLightbox,
  ProductCarousel,
  QueueStack,
  RoutineCard,
  RoutineDetail,
  ThinkingStatus,
  UserBubble,
} from "../../home/conversation-frame-primitives";
import type {
  DebugConversationFrameActions,
  DebugConversationFrameModel,
  DebugRichItem,
  DebugTimelineItem,
} from "./debug-conversation-frame-model";
import styles from "./chat-frame-debug.module.css";
import frameStyles from "../../home/conversation-frame.module.css";

export interface DebugConversationFrameProps {
  model: DebugConversationFrameModel;
  actions: DebugConversationFrameActions;
}

export function DebugConversationFrame({ model, actions }: DebugConversationFrameProps) {
  const firstAssistantId = model.timeline.find(
    (item): item is Extract<DebugTimelineItem, { kind: "message" }> => (
      item.kind === "message" && item.sender === "assistant"
    ),
  )?.id;

  return (
    <ConversationShell accent={model.ally.accent} safeArea={{ top: "44px", bottom: "34px" }}>
      <ConversationHeader
        name={model.ally.name}
        subtitle={model.ally.job}
        homeHref="/home"
        settingsHref="/account"
        avatar={(
          <AllyFrameAvatar
            shape={model.ally.shape}
            accent={model.ally.accent}
            size={40}
            label={`${model.ally.name} avatar`}
          />
        )}
      />

      <DateDivider sticky>{model.dateLabel}</DateDivider>
      <ConversationCanvas>
        <ConversationRail className={styles.debugRail}>
          {model.deleted ? <FrameError role="status">Routine deleted</FrameError> : null}
          {model.acknowledgement ? (
            <div className={`${styles.debugStatus} ${styles.debugStatusSuccess}`} role="status">
              <span className={styles.debugStatusCopy}>{model.acknowledgement}</span>
            </div>
          ) : null}
          {model.timeline.map((item) => (
            <DebugTimelineBlock
              key={item.id}
              item={item}
              firstAssistantId={firstAssistantId}
              model={model}
              actions={actions}
            />
          ))}
        </ConversationRail>
      </ConversationCanvas>

      <footer className={frameStyles.frameComposerArea}>
        {model.queue.length > 0 ? (
          <QueueStack
            items={model.queue}
            actionLabel={model.queueAction === "push" ? "Push" : undefined}
            onAction={model.queueAction ? () => actions.onAction("push") : undefined}
            onRemove={actions.onRemoveQueue}
          />
        ) : null}
        <ConversationComposer
          allyName={model.ally.name}
          value={model.composer.draft}
          placeholder={model.composer.placeholder}
          disabled={false}
          sending={false}
          onChange={actions.onComposerChange}
          onSubmit={actions.onComposerSubmit}
        />
      </footer>

      {model.overlay ? <DebugOverlay overlay={model.overlay} actions={actions} /> : null}
    </ConversationShell>
  );
}

function DebugTimelineBlock({
  item,
  firstAssistantId,
  model,
  actions,
}: {
  item: DebugTimelineItem;
  firstAssistantId: string | undefined;
  model: DebugConversationFrameModel;
  actions: DebugConversationFrameActions;
}) {
  if (item.kind === "message") {
    if (item.sender === "user") {
      return (
        <UserBubble status={item.status} retryable={Boolean(item.retryable)} onRetry={() => actions.onAction("report")}>
          {item.text}
        </UserBubble>
      );
    }
    return (
      <>
        {item.id === firstAssistantId ? (
          <AssistantIdentity
            name={model.ally.name}
            avatar={(
              <AllyFrameAvatar
                shape={model.ally.shape}
                accent={model.ally.accent}
                size={36}
                label={`${model.ally.name} avatar`}
              />
            )}
          />
        ) : null}
        <AssistantMessage>{item.text}</AssistantMessage>
      </>
    );
  }

  if (item.kind === "activity") {
    return <ActivityDisclosure label={item.label} entries={item.entries} open={item.open} ongoing />;
  }

  if (item.kind === "thinking") {
    return (
      <ThinkingStatus
        label={item.label}
        avatar={(
          <AllyFrameAvatar
            shape={model.ally.shape}
            accent={model.ally.accent}
            size={32}
            state="thinking"
            label={`${model.ally.name} ${item.label.toLowerCase()}`}
          />
        )}
      />
    );
  }

  if (item.kind === "status") {
    return (
      <div className={`${styles.debugStatus} ${item.tone === "success" ? styles.debugStatusSuccess : item.tone === "warning" ? styles.debugStatusWarning : ""}`} role="status">
        {item.tone !== "success" ? (
          <span className={styles.debugStatusAvatar}>
            <AllyFrameAvatar
              shape={model.ally.shape}
              accent={model.ally.accent}
              size={36}
              neutral={item.tone === "default"}
              label={`${model.ally.name} status`}
            />
          </span>
        ) : null}
        <span className={styles.debugStatusCopy}>{item.text}</span>
      </div>
    );
  }

  return <DebugRichBlock item={item} actions={actions} />;
}

function DebugRichBlock({
  item,
  actions,
}: {
  item: DebugRichItem;
  actions: DebugConversationFrameActions;
}) {
  switch (item.kind) {
    case "rich-text":
      return <AssistantMessage>{item.text}</AssistantMessage>;
    case "routine-card":
      return <RoutineCard name={item.name} schedule={item.schedule} onOpen={() => actions.onAction("open-routine")} />;
    case "products":
      return (
        <>
          <AssistantMessage>{item.intro}</AssistantMessage>
          <ProductCarousel items={item.products} onSelect={() => actions.onAction("open-cart")} />
        </>
      );
    case "cart-summary":
      return (
        <CartSummary
          restaurant={item.restaurant}
          itemCount={item.itemCount}
          expanded={item.expanded}
          onOpen={() => actions.onAction("open-cart")}
        />
      );
    case "cart-editor":
      return (
        <CartEditor
          itemCount={item.itemCount}
          quantity={item.quantity}
          onQuantityChange={(next) => actions.onQuantityChange(item.id, next)}
          onDone={() => actions.onAction("done-cart")}
        />
      );
    case "failure":
      return <FrameError action={item.actionLabel} onAction={() => actions.onAction("report")}>{item.text}</FrameError>;
    case "image":
      return (
        <button type="button" className={styles.debugImageButton} onClick={() => actions.onAction("open-image")} aria-label={`Open ${item.alt}`}>
          <span className={styles.debugImageShape} aria-hidden="true" />
        </button>
      );
  }
}

function DebugOverlay({
  overlay,
  actions,
}: {
  overlay: NonNullable<DebugConversationFrameModel["overlay"]>;
  actions: DebugConversationFrameActions;
}) {
  switch (overlay.kind) {
    case "approval":
      return (
        <ApprovalSheet
          onClose={() => actions.onAction("close-overlay")}
          onReject={() => actions.onAction("reject")}
          onApprove={() => actions.onAction("approve")}
        />
      );
    case "image":
      return <ImageLightbox alt={overlay.alt} onClose={() => actions.onAction("close-overlay")} />;
    case "cart":
      return (
        <BottomSheet title={`${overlay.itemCount} items`} onClose={() => actions.onAction("close-overlay")}>
          <ProductCarousel items={overlay.products} onSelect={() => actions.onAction("done-cart")} />
        </BottomSheet>
      );
    case "routine":
      return (
        <BottomSheet
          onClose={() => actions.onAction("close-overlay")}
          labelledBy="routine-detail-title"
          className={frameStyles.frameRoutineDetailOverlay}
          hideHeader
        >
          <RoutineDetail
            onClose={() => actions.onAction("close-overlay")}
            onDelete={() => actions.onAction("delete-routine")}
          />
        </BottomSheet>
      );
    case "delete-routine":
      return (
        <DeleteRoutineSheet
          onCancel={() => actions.onAction("cancel-delete")}
          onDelete={() => actions.onAction("confirm-delete")}
        />
      );
  }
}
