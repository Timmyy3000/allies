import { describe, expect, it, vi } from "vitest";

import { readActivityStream } from "./activity-stream";

describe("readActivityStream", () => {
  it("handles reader cancellation rejection after the parent aborts", async () => {
    const parent = new AbortController();
    const onError = vi.fn();
    let streamController: ReadableStreamDefaultController<Uint8Array>;
    const stream = new ReadableStream<Uint8Array>({ start(controller) { streamController = controller; } });
    const cancel = vi.spyOn(ReadableStreamDefaultReader.prototype, "cancel");
    vi.stubGlobal("fetch", vi.fn(async (_url, init: RequestInit) => {
      init.signal?.addEventListener("abort", () => streamController.error(new DOMException("BodyStreamBuffer was aborted", "AbortError")), { once: true });
      return new Response(stream);
    }));
    const onOpen = vi.fn();
    const handle = readActivityStream({ baseUrl: "http://localhost:8000", workspaceId: "workspace", conversationId: "conversation", signal: parent.signal, onEvent: vi.fn(), onOpen, onError });
    try {
      await vi.waitFor(() => expect(onOpen).toHaveBeenCalledOnce());
      parent.abort();
      await vi.waitFor(() => expect(cancel).toHaveBeenCalledOnce());
      expect(onError).not.toHaveBeenCalled();
    } finally {
      handle.close();
      cancel.mockRestore();
      vi.unstubAllGlobals();
    }
  });

  it("parses ready and activity frames and sends the accepted cursor on reconnect input", async () => {
    const events: unknown[] = [];
    const onError = vi.fn();
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        [
          "id: cursor-ready\n",
          "event: ready\n",
          'data: {"conversation_id":"conversation","cursor":"cursor-ready","high_water_sequence":4}\n\n',
          "id: cursor-activity\n",
          "event: activity\n",
          'data: {"conversation_id":"conversation","cursor":"cursor-activity","activity":{"id":"activity","message_id":"message","sequence":5,"conversation_turn_ordinal":1,"kind":"assistant_delta","text":"Hello","state":"running","created_at":"2026-01-01T00:00:00Z","activity_attempt_id":"attempt-0123456789abcdef0123456789abcdef","activity_id":"activity-0123456789abcdef0123456789abcdef","activity_kind":"web_search","outcome":"failed","duration_ms":1234,"approval":{"id":"00000000-0000-4000-8000-000000000001","status":"pending","expires_at":"2099-01-01T00:00:00Z"}}}\n\n',
        ].join(""),
        { status: 200, headers: { "Content-Type": "text/event-stream" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const handle = readActivityStream({
      baseUrl: "http://localhost:8000",
      workspaceId: "workspace",
      conversationId: "conversation",
      cursor: "cursor-old",
      onEvent: (event) => events.push(event),
      onError,
    });

    await vi.waitFor(() => expect(events).toHaveLength(2));
    expect(fetchMock).toHaveBeenCalledWith(
      expect.objectContaining({
        search: "?cursor=cursor-old",
      }),
      expect.objectContaining({
        credentials: "include",
        headers: expect.objectContaining({ "Last-Event-ID": "cursor-old" }),
      }),
    );
    expect(events[0]).toMatchObject({ type: "ready", highWaterSequence: 4 });
    expect(events[1]).toMatchObject({
      type: "activity",
      cursor: "cursor-activity",
      activity: {
        activityAttemptId: "attempt-0123456789abcdef0123456789abcdef",
        activityId: "activity-0123456789abcdef0123456789abcdef",
        activityKind: "web_search",
        outcome: "failed",
        durationMs: 1234,
        approval: {
          id: "00000000-0000-4000-8000-000000000001",
          status: "pending",
          expiresAt: "2099-01-01T00:00:00Z",
        },
      },
    });
    expect(onError).toHaveBeenCalledOnce();
    handle.close();
  });

  it.each([
    ["malformed attempt id", "activity_attempt_id", "bad-attempt"],
    ["malformed activity id", "activity_id", "bad-activity"],
    ["malformed activity kind", "activity_kind", "Web Search"],
    ["invalid outcome", "outcome", "unknown"],
    ["out-of-range duration", "duration_ms", 86_400_001],
    ["invalid approval status", "approval", { id: "00000000-0000-4000-8000-000000000001", status: "resumed", expires_at: "2099-01-01T00:00:00Z" }],
  ])("rejects %s in rich activity metadata", async (_label, field, value) => {
    const onError = vi.fn();
    const activity = {
      id: "activity",
      message_id: "message",
      sequence: 5,
      conversation_turn_ordinal: 1,
      kind: "assistant_delta",
      text: "Hello",
      state: "running",
      created_at: "2026-01-01T00:00:00Z",
      [field]: value,
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(`event: activity\ndata: ${JSON.stringify({ conversation_id: "conversation", cursor: "cursor-activity", activity })}\n\n`, { status: 200 }),
    ));

    readActivityStream({
      baseUrl: "http://localhost:8000",
      workspaceId: "workspace",
      conversationId: "conversation",
      onEvent: vi.fn(),
      onError,
    });

    await vi.waitFor(() => expect(onError).toHaveBeenCalledOnce());
    expect(onError.mock.calls[0][0]).toMatchObject({ message: "invalid activity stream activity payload" });
  });

  it("surfaces HTTP status failures without opening a stream", async () => {
    const onOpen = vi.fn();
    const onError = vi.fn();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("unauthorized", { status: 401 })));

    readActivityStream({
      baseUrl: "http://localhost:8000",
      workspaceId: "workspace",
      conversationId: "conversation",
      onOpen,
      onEvent: vi.fn(),
      onError,
    });

    await vi.waitFor(() => expect(onError).toHaveBeenCalledOnce());
    expect(onOpen).not.toHaveBeenCalled();
    expect(onError.mock.calls[0][0]).toMatchObject({ status: 401 });
  });

  it("fails a stalled stream so the caller can resume replay polling", async () => {
    const onError = vi.fn();
    const body = new ReadableStream<Uint8Array>({
      start() {
        // Keep the body open without producing bytes.
      },
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body, { status: 200 })));

    const handle = readActivityStream({
      baseUrl: "http://localhost:8000",
      workspaceId: "workspace",
      conversationId: "conversation",
      idleTimeoutMs: 10,
      onEvent: vi.fn(),
      onError,
    });

    await vi.waitFor(() => expect(onError).toHaveBeenCalledOnce());
    expect(onError.mock.calls[0][0]).toMatchObject({ message: "activity stream timed out" });
    handle.close();
  });

  it.each([
    ["invalid JSON", "event: activity\ndata: {not-json}\n\n"],
    ["invalid activity state", 'event: activity\ndata: {"conversation_id":"conversation","activity":{"id":"a","message_id":"m","sequence":1,"conversation_turn_ordinal":1,"kind":"assistant_delta","text":"x","state":"bogus","created_at":"2026-01-01T00:00:00Z"}}\n\n'],
    ["unknown event", 'event: mystery\ndata: {"conversation_id":"conversation"}\n\n'],
  ])("fails closed for %s", async (_label, frame) => {
    const onError = vi.fn();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(frame, { status: 200 }),
    ));

    readActivityStream({
      baseUrl: "http://localhost:8000",
      workspaceId: "workspace",
      conversationId: "conversation",
      onEvent: vi.fn(),
      onError,
    });

    await vi.waitFor(() => expect(onError).toHaveBeenCalledOnce());
    expect(onError.mock.calls[0][0]).toBeInstanceOf(Error);
  });

  it("surfaces the contract's stream.error event as a typed stream error", async () => {
    const onError = vi.fn();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(
        'event: stream.error\ndata: {"conversation_id":"conversation","code":"stream_unavailable"}\n\n',
        { status: 200 },
      ),
    ));

    readActivityStream({
      baseUrl: "http://localhost:8000",
      workspaceId: "workspace",
      conversationId: "conversation",
      onEvent: vi.fn(),
      onError,
    });

    await vi.waitFor(() => expect(onError).toHaveBeenCalledOnce());
    expect(onError.mock.calls[0][0]).toMatchObject({
      message: "activity stream error: stream_unavailable",
    });
  });

  it("fails closed when a stream frame exceeds the client buffer limit", async () => {
    const onError = vi.fn();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(`event: activity\ndata: ${"x".repeat(4 * 1024 * 1024 + 1)}`, { status: 200 }),
    ));

    readActivityStream({
      baseUrl: "http://localhost:8000",
      workspaceId: "workspace",
      conversationId: "conversation",
      onEvent: vi.fn(),
      onError,
    });

    await vi.waitFor(() => expect(onError).toHaveBeenCalledOnce());
    expect(onError.mock.calls[0][0]).toMatchObject({
      message: "activity stream frame too large",
    });
  });

  it("fails closed when event data accumulates across bounded lines", async () => {
    const onError = vi.fn();
    const encoder = new TextEncoder();
    const line = `data: ${"x".repeat(2 * 1024 * 1024 + 100)}\n`;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(new ReadableStream({
        start(controller) {
          controller.enqueue(encoder.encode(`event: activity\n${line}`));
          controller.enqueue(encoder.encode(line));
          controller.close();
        },
      }), { status: 200 }),
    ));

    readActivityStream({
      baseUrl: "http://localhost:8000",
      workspaceId: "workspace",
      conversationId: "conversation",
      onEvent: vi.fn(),
      onError,
    });

    await vi.waitFor(() => expect(onError).toHaveBeenCalledOnce());
    expect(onError.mock.calls[0][0]).toMatchObject({
      message: "activity stream frame too large",
    });
  });
});
