import type { CloudError } from "./errors";

const DEFAULT_TIMEOUT_MS = 10_000;
const DEFAULT_MAX_JSON_BYTES = 256 * 1024;

export interface TransportOptions {
  fetch: typeof globalThis.fetch;
  prepareRequest?: (request: Request) => Request | Promise<Request>;
  timeoutMs?: number;
  maxJsonBytes?: number;
}

function transportError(kind: CloudError["kind"]): CloudError {
  return { kind };
}

async function boundResponse(response: Response, maxBytes: number, signal: AbortSignal): Promise<Response> {
  if (!response.body || response.status === 204 || response.status === 205) return response;

  const declaredLength = Number(response.headers.get("content-length"));
  if (Number.isFinite(declaredLength) && declaredLength > maxBytes) {
    await response.body.cancel();
    throw transportError("contract");
  }

  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  let rejectAbort: ((reason: unknown) => void) | undefined;
  const aborted = new Promise<never>((_resolve, reject) => { rejectAbort = reject; });
  const onAbort = () => rejectAbort?.(new DOMException("Aborted", "AbortError"));
  if (signal.aborted) onAbort();
  signal.addEventListener("abort", onAbort, { once: true });

  try {
    while (true) {
      const { done, value } = await Promise.race([reader.read(), aborted]);
      if (done) break;
      total += value.byteLength;
      if (total > maxBytes) {
        void reader.cancel();
        throw transportError("contract");
      }
      chunks.push(value);
    }
  } catch (error) {
    void reader.cancel().catch(() => undefined);
    throw error;
  } finally {
    signal.removeEventListener("abort", onAbort);
  }

  const body = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }

  return new Response(body, {
    status: response.status,
    statusText: response.statusText,
    headers: response.headers,
  });
}

export function createControlledFetch(options: TransportOptions): typeof globalThis.fetch {
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const maxJsonBytes = options.maxJsonBytes ?? DEFAULT_MAX_JSON_BYTES;

  return async (input, init) => {
    const originalRequest = new Request(input, init);
    const callerSignal = originalRequest.signal;
    const controller = new AbortController();
    let timedOut = false;
    const onCallerAbort = () => controller.abort(callerSignal.reason);
    if (callerSignal.aborted) controller.abort(callerSignal.reason);
    callerSignal.addEventListener("abort", onCallerAbort, { once: true });
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeoutMs);

    try {
      const request = new Request(originalRequest, { signal: controller.signal });
      const prepared = options.prepareRequest ? await options.prepareRequest(request) : request;
      const controlledRequest = new Request(prepared, { signal: controller.signal });
      const response = await options.fetch(controlledRequest);
      return await boundResponse(response, maxJsonBytes, controller.signal);
    } catch (error) {
      if (typeof error === "object" && error !== null && "kind" in error) throw error;
      if (callerSignal.aborted) throw transportError("aborted");
      if (timedOut) throw transportError("timeout");
      throw transportError("network");
    } finally {
      clearTimeout(timer);
      callerSignal.removeEventListener("abort", onCallerAbort);
    }
  };
}
