import { activityApprovalSchema, toActivityApproval, activityKindSchema, activityStateSchema, type ActivityState, type ActivityViewModel } from "@allies/cloud-client";

const MAX_STREAM_BUFFER_BYTES = 4 * 1024 * 1024;
const ACTIVITY_ATTEMPT_ID_PATTERN = /^attempt-[0-9a-f]{32}$/;
const ACTIVITY_ID_PATTERN = /^activity-[0-9a-f]{32}$/;
const ACTIVITY_KIND_PATTERN = /^[a-z_]{1,32}$/;
const ACTIVITY_OUTCOMES = ["completed", "failed", "stopped"] as const;

function isOptionalPattern(value: unknown, pattern: RegExp): value is string | null | undefined {
  return value === undefined || value === null || (typeof value === "string" && pattern.test(value));
}

function isOptionalOutcome(value: unknown): value is (typeof ACTIVITY_OUTCOMES)[number] | null | undefined {
  return value === undefined || value === null || (typeof value === "string" && ACTIVITY_OUTCOMES.includes(value as (typeof ACTIVITY_OUTCOMES)[number]));
}

function isOptionalDuration(value: unknown): value is number | null | undefined {
  return value === undefined || value === null || (typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= 86_400_000);
}

export type ActivityStreamEvent =
  | { type: "ready"; conversationId: string; cursor: string; highWaterSequence: number }
  | { type: "activity"; conversationId: string; activity: ActivityViewModel; cursor: string }
  | { type: "terminal"; conversationId: string; state: ActivityState; cursor: string }
  | { type: "error"; conversationId: string; code: string }
  | { type: "heartbeat" };

export interface ActivityStreamOptions {
  baseUrl: string;
  workspaceId: string;
  conversationId: string;
  cursor?: string | null;
  signal?: AbortSignal;
  /** Maximum silence between stream bytes before falling back to replay/polling. */
  idleTimeoutMs?: number;
  onOpen?: () => void;
  onEvent: (event: ActivityStreamEvent) => void;
  onError?: (error: ActivityStreamError) => void;
}

export class ActivityStreamError extends Error {
  readonly status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.name = "ActivityStreamError";
    this.status = status;
  }
}

export interface ActivityStreamHandle {
  close(): void;
}

function parseEvent(eventName: string, eventId: string, data: string): ActivityStreamEvent | null {
  if (!eventName || !data) return eventName === "heartbeat" ? { type: "heartbeat" } : null;
  let value: unknown;
  try {
    value = JSON.parse(data);
  } catch {
    throw new ActivityStreamError("invalid activity stream data");
  }
  if (!value || typeof value !== "object") throw new ActivityStreamError("invalid activity stream event");
  const record = value as Record<string, unknown>;
  const conversationId = typeof record.conversation_id === "string" ? record.conversation_id : "";
  const cursor = typeof record.cursor === "string" ? record.cursor : eventId;
  if (eventName === "ready") {
    if (!conversationId || !cursor || typeof record.high_water_sequence !== "number") {
      throw new ActivityStreamError("invalid activity stream ready event");
    }
    return { type: "ready", conversationId, cursor, highWaterSequence: record.high_water_sequence };
  }
  if (eventName === "activity") {
    const raw = record.activity;
    if (!conversationId || !cursor || !raw || typeof raw !== "object") {
      throw new ActivityStreamError("invalid activity stream activity event");
    }
    const activity = raw as Record<string, unknown>;
    const approval = activityApprovalSchema.nullish().safeParse(activity.approval);
    if (
      typeof activity.id !== "string"
      || typeof activity.message_id !== "string"
      || typeof activity.sequence !== "number"
      || typeof activity.conversation_turn_ordinal !== "number"
      || typeof activity.kind !== "string"
      || typeof activity.text !== "string"
      || typeof activity.state !== "string"
      || typeof activity.created_at !== "string"
      || !activityKindSchema.safeParse(activity.kind).success
      || !activityStateSchema.safeParse(activity.state).success
      || !isOptionalPattern(activity.activity_attempt_id, ACTIVITY_ATTEMPT_ID_PATTERN)
      || !isOptionalPattern(activity.activity_id, ACTIVITY_ID_PATTERN)
      || !isOptionalPattern(activity.activity_kind, ACTIVITY_KIND_PATTERN)
      || !isOptionalOutcome(activity.outcome)
      || !isOptionalDuration(activity.duration_ms)
      || !approval.success
    ) throw new ActivityStreamError("invalid activity stream activity payload");
    return {
      type: "activity",
      conversationId,
      cursor,
      activity: {
        id: activity.id,
        messageId: activity.message_id,
        sequence: activity.sequence,
        conversationTurnOrdinal: activity.conversation_turn_ordinal,
        kind: activity.kind as ActivityViewModel["kind"],
        text: activity.text,
        state: activity.state as ActivityViewModel["state"],
        createdAt: activity.created_at,
        activityAttemptId: activity.activity_attempt_id,
        activityId: activity.activity_id,
        activityKind: activity.activity_kind,
        outcome: activity.outcome,
        durationMs: activity.duration_ms,
        approval: approval.data ? toActivityApproval(approval.data) : approval.data,
      },
    };
  }
  if (eventName === "terminal") {
    if (
      !conversationId
      || !cursor
      || typeof record.state !== "string"
      || !activityStateSchema.safeParse(record.state).success
    ) {
      throw new ActivityStreamError("invalid activity stream terminal event");
    }
    return { type: "terminal", conversationId, state: record.state as ActivityState, cursor };
  }
  if (eventName === "error" || eventName === "stream.error") {
    if (!conversationId || typeof record.code !== "string") {
      throw new ActivityStreamError("invalid activity stream error event");
    }
    throw new ActivityStreamError(`activity stream error: ${record.code}`);
  }
  if (eventName === "heartbeat") return { type: "heartbeat" };
  throw new ActivityStreamError("unknown activity stream event");
}

export function readActivityStream(options: ActivityStreamOptions): ActivityStreamHandle {
  const controller = new AbortController();
  const abort = () => controller.abort();
  options.signal?.addEventListener("abort", abort, { once: true });
  let closed = false;
  let timedOut = false;
  let idleTimer: ReturnType<typeof setTimeout> | null = null;
  let cursor = options.cursor ?? null;

  const armIdleTimeout = () => {
    if (idleTimer) clearTimeout(idleTimer);
    idleTimer = setTimeout(() => {
      if (closed) return;
      timedOut = true;
      controller.abort();
      options.onError?.(new ActivityStreamError("activity stream timed out"));
    }, options.idleTimeoutMs ?? 20_000);
  };

  const run = async () => {
    const url = new URL(
      `/api/v1/workspaces/${encodeURIComponent(options.workspaceId)}/conversations/${encodeURIComponent(options.conversationId)}/activities/stream`,
      options.baseUrl,
    );
    if (cursor) url.searchParams.set("cursor", cursor);
    let reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
    try {
      const response = await fetch(url, {
        credentials: "include",
        headers: {
          Accept: "text/event-stream",
          ...(cursor ? { "Last-Event-ID": cursor } : {}),
        },
        signal: controller.signal,
      });
      if (!response.ok) throw new ActivityStreamError("activity stream unavailable", response.status);
      if (!response.body) throw new ActivityStreamError("activity stream has no body");
      options.onOpen?.();
      armIdleTimeout();
      reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let eventName = "message";
      let eventId = "";
      let data: string[] = [];
      let eventDataBytes = 0;
      const appendData = (value: string) => {
        eventDataBytes += value.length;
        if (eventDataBytes > MAX_STREAM_BUFFER_BYTES) {
          throw new ActivityStreamError("activity stream frame too large");
        }
        data.push(value);
      };
      const flush = () => {
        if (!data.length && eventName === "message") return;
        const event = parseEvent(eventName, eventId, data.join("\n"));
        eventName = "message";
        eventId = "";
        data = [];
        eventDataBytes = 0;
        if (!event || closed) return;
        if ("cursor" in event) cursor = event.cursor;
        options.onEvent(event);
      };
      while (!closed) {
        const chunk = await reader.read();
        if (chunk.done) break;
        armIdleTimeout();
        buffer += decoder.decode(chunk.value, { stream: true });
        if (buffer.length > MAX_STREAM_BUFFER_BYTES) {
          throw new ActivityStreamError("activity stream frame too large");
        }
        const lines = buffer.split(/\r?\n/);
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (!line) {
            flush();
          } else if (line.startsWith("event:")) {
            eventName = line.slice(6).trim();
          } else if (line.startsWith("id:")) {
            eventId = line.slice(3).trim();
          } else if (line.startsWith("data:")) {
            appendData(line.slice(5).trimStart());
          }
        }
      }
      if (buffer) appendData(buffer);
      flush();
      if (!closed) throw new ActivityStreamError("activity stream closed");
    } catch (error) {
      if (!closed && !controller.signal.aborted && !timedOut) {
        options.onError?.(error instanceof ActivityStreamError ? error : new ActivityStreamError("activity stream failed"));
      }
    } finally {
      // An aborted response can also reject cancellation of its reader.
      if (reader) void reader.cancel().catch(() => undefined);
      if (idleTimer) clearTimeout(idleTimer);
      if (!closed) controller.abort();
      options.signal?.removeEventListener("abort", abort);
    }
  };
  void run();
  return {
    close() {
      if (closed) return;
      closed = true;
      if (idleTimer) clearTimeout(idleTimer);
      controller.abort();
    },
  };
}
