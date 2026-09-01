import { describe, expect, it, vi } from "vitest";

import { readActivityStream } from "./activity-stream";

describe("readActivityStream", () => {
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
          'data: {"conversation_id":"conversation","cursor":"cursor-activity","activity":{"id":"activity","message_id":"message","sequence":5,"conversation_turn_ordinal":1,"kind":"assistant_delta","text":"Hello","state":"running","created_at":"2026-01-01T00:00:00Z"}}\n\n',
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
    expect(events[1]).toMatchObject({ type: "activity", cursor: "cursor-activity" });
    expect(onError).toHaveBeenCalledOnce();
    handle.close();
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
