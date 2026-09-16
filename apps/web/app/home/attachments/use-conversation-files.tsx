"use client";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useQueryClient } from "@tanstack/react-query";
import { conversationQueryKey } from "../../../lib/allies/queries";
import type {
  MessageFile,
  MessageViewModel,
  FileMetadata,
  FilePublication,
} from "@allies/cloud-client";
import { validateSelectedFiles } from "@allies/cloud-client";
import { useSession } from "../../../lib/session/session-context";
import {
  fileTransfers,
  selectedFile,
  type FileTransfer,
  type SelectedFile,
} from "../../../lib/files/transfers";
import {
  AttachmentPicker,
  AttachmentTray,
  animateAttachments,
  FileIcon,
  middleEllipsis,
} from "./attachment-picker";
import styles from "./attachments.module.css";

const EMPTY: FileTransfer[] = [];
const EMPTY_SELECTED_FILES: SelectedFile[] = [];
export function useConversationFiles(
  userId: string,
  workspaceId: string,
  allyId: string,
  onAccepted?: () => void,
) {
  const session = useSession();
  const queryClient = useQueryClient();
  const scope = `${userId}:${workspaceId}:${allyId}`;
  const manager = useMemo(
    () => fileTransfers(session.client, session.runCloudOperation),
    [session.client, session.runCloudOperation],
  );
  const records = useSyncExternalStore(
    manager.subscribe,
    manager.snapshot,
    () => EMPTY,
  );
  const draftFiles = manager.drafts.get(scope);
  const files = useMemo(() => draftFiles ?? EMPTY_SELECTED_FILES, [draftFiles]);
  const [open, setOpen] = useState(false);
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const [arriving, setArriving] = useState(new Set<string>());
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<MessageFile | null>(null);
  const [restoredDrafts, setRestoredDrafts] = useState(new Set<string>());
  const reduced = useReducedMotion();
  useEffect(() => {
    if (typeof indexedDB !== "undefined")
      void manager
        .restore(scope)
        .catch((error) => setError(
          error instanceof Error
            ? error.message
            : "Saved file drafts could not be read. Retry to continue.",
        ));
  }, [manager, scope]);
  const change = useCallback(
    (next: SelectedFile[]) => {
      const previous = manager.drafts.get(scope) ?? [];
      manager.setDraft(scope, next);
      previous.forEach((file) => manager.releasePreview(file));
    },
    [manager, scope],
  );
  const perform = async (action: () => Promise<unknown>) => {
    try {
      setError("");
      await action();
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "That file action could not be confirmed. Refresh the message and retry.",
      );
    }
  };
  const accept = useCallback(
    (items: SelectedFile[], origin?: DOMRect) => {
      try {
        validateSelectedFiles([...files, ...items]);
        setArriving(new Set(items.map((file) => file.id)));
        change([...files, ...items]);
        onAccepted?.();
        setOpen(false);
        void animateAttachments(items, origin, Boolean(reduced), (id) =>
          setArriving((current) => {
            const next = new Set(current);
            next.delete(id);
            return next;
          }),
        );
        return true;
      } catch (error) {
        items
          .filter((file) => !files.includes(file))
          .forEach((file) => {
            if (file.src) URL.revokeObjectURL(file.src);
          });
        setError(
          error instanceof Error ? error.message : "These files could not be added.",
        );
        return false;
      }
    },
    [change, files, onAccepted, reduced],
  );
  const addFiles = useCallback(
    (incoming: File[], origin?: DOMRect) =>
      accept(incoming.map((file) => selectedFile(file)), origin),
    [accept],
  );
  const active = records.filter(
    (record) => record.scope === scope && record.phase !== "cancelled",
  );
  const progressKey = records
    .filter((record) => record.scope === scope)
    .map(
      (record) =>
        `${record.id}:${record.phase}:${record.reservation?.message.revision}`,
    )
    .join("|");
  const isUploading = records.some(
    (record) =>
      record.scope === scope &&
      ["uploading", "checking"].includes(record.phase),
  );
  useEffect(() => {
    if (!progressKey) return;
    void queryClient.invalidateQueries({
      queryKey: conversationQueryKey(workspaceId, allyId),
    });
    if (!isUploading) return;
    const interval = setInterval(() => {
      void queryClient.invalidateQueries({
        queryKey: conversationQueryKey(workspaceId, allyId),
      });
    }, 2500);
    return () => clearInterval(interval);
  }, [progressKey, isUploading, queryClient, workspaceId, allyId]);
  return {
    manager,
    scope,
    files,
    change,
    active,
    pending: (id: string) => {
      const transfer = manager.find(id);
      return transfer ? (
        <span className={styles.transfer}>
          {transfer.files.map((file) => (
            <span key={file.id} className={styles.transferFile}>
              <FileIcon />
              <span>{file.name}</span>
            </span>
          ))}
        </span>
      ) : null;
    },
    cancelled: records.filter(
      (record) =>
        record.scope === scope &&
        record.phase === "cancelled" &&
        !restoredDrafts.has(record.id),
    ),
    discard: (id: string) => void perform(() => manager.discard(id)),
    restoreDraft: (record: FileTransfer) => {
      change([
        ...record.files.map((f) => ({ ...f, id: crypto.randomUUID() })),
        ...(manager.drafts.get(scope) ?? []),
      ]);
      setRestoredDrafts((current) => new Set(current).add(record.id));
    },
    openFile: (id: string) =>
      setPreview({ id, name: "File", size: 1, state: "ready" }),
    publications: (messageId: string, publications: FilePublication[]) => (
      <FilePublications
        messageId={messageId}
        publications={publications}
        workspaceId={workspaceId}
        allyId={allyId}
        onOpen={setPreview}
      />
    ),
    open: (element: HTMLElement) => {
      setAnchor(element);
      setOpen(true);
    },
    addFiles,
    tray: files.length ? (
      <AttachmentTray
        files={files}
        arriving={arriving}
        onRemove={(id) => {
          change(files.filter((f) => f.id !== id));
        }}
        onReselect={(id, file) =>
          void perform(async () => {
            const next = files.map((f) =>
              f.id === id ? selectedFile(file) : f,
            );
            validateSelectedFiles(next);
            change(next);
          })
        }
      />
    ) : undefined,
    overlays: (accent: string) => (
      <>
        <AnimatePresence>
          {open && (
            <AttachmentPicker
              anchor={anchor}
              accent={accent}
              existing={files}
              onClose={() => setOpen(false)}
              onAdd={(items, origin) => void accept(items, origin)}
            />
          )}
        </AnimatePresence>
        {error && (
          <div
            className={styles.notice}
            role="alert"
            aria-live="assertive"
            aria-atomic="true"
          >
            {error}
            <button
              type="button"
              onClick={() => setError("")}
              aria-label="Dismiss file error"
            >
              ×
            </button>
          </div>
        )}
        <AnimatePresence initial={false}>{preview && (
          <PrivateFilePreview
            key={preview.id}
            file={preview}
            workspaceId={workspaceId}
            allyId={allyId}
            onClose={() => setPreview(null)}
          />
        )}</AnimatePresence>
      </>
    ),
    render: (
      message: MessageViewModel | undefined,
      restoreText: (content: string) => void,
      conversationId: string,
    ) => {
      if (!message) return null;
      const transfer = active.find(
        (record) => record.reservation?.message.id === message.id,
      );
      const remote = message.files ?? [];
      if (!remote.length && !transfer) return null;
      const pending =
        transfer && !["ready", "cancelled"].includes(transfer.phase);
      const canChange =
        message.status === "queued" && message.queueState !== "claimed";
      const displayedFiles = transfer?.files ?? remote;
      const compactSentFiles = displayedFiles.length > 1 && !pending && !canChange;
      const fileRows = displayedFiles.map((file) => {
        const local = transfer?.files.find((f) => f.id === file.id);
        const id = local?.remoteId ?? file.id;
        const ready = file.state === "ready" || file.state === "retained";
        return (
          <span className={styles.transferFile} key={id}>
            <button
              type="button"
              onClick={() =>
                setPreview({
                  id,
                  name: file.name,
                  size: file.size,
                  state: file.state as MessageFile["state"],
                })
              }
              disabled={!ready}
            >
              <FileThumbnail
                id={id}
                name={file.name}
                src={local?.src}
                ready={ready}
                workspaceId={workspaceId}
                allyId={allyId}
              />
              <span>
                <span className={styles.transferFileName} title={file.name}>{middleEllipsis(file.name)}</span>
                <AnimatePresence initial={false} mode="wait"><motion.small
                  key={local && pending ? local.state === "pending" && transfer.phase === "uploading" ? "uploading" : local.state === "validating" || local.state === "receiving" ? "checking" : local.state : "ready"}
                  initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: reduced ? 0 : .14 }}
                >
                  {local && pending
                    ? local.state === "pending" && transfer.phase === "uploading"
                      ? `Uploading ${local.progress}%`
                      : local.state === "validating" || local.state === "receiving"
                        ? "Checking file…"
                        : local.state === "ready"
                          ? "Ready"
                          : "Needs attention"
                    : `${local ? "✓ Ready · " : ""}${(file.size / 1_000_000).toFixed(1)} MB`}
                </motion.small></AnimatePresence>
              </span>
            </button>
            {local &&
              transfer &&
              transfer.phase === "failed" &&
              canChange && (
                <button
                  type="button"
                  aria-label={`Remove ${file.name}`}
                  onClick={() =>
                    void perform(() =>
                      manager.remove(transfer.id, local.id),
                    )
                  }
                >
                  ×
                </button>
              )}
            {local &&
              !local.file &&
              transfer &&
              transfer.phase === "failed" && (
                <label className={styles.reselect}>
                  Choose original
                  <input
                    type="file"
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f)
                        void perform(() =>
                          manager.reselect(transfer.id, local.id, f),
                        );
                      e.target.value = "";
                    }}
                  />
                </label>
              )}
          </span>
        );
      });
      return (
        <span className={styles.transfer}>
          {compactSentFiles ? (
            <FileBundle count={displayedFiles.length} size={displayedFiles.reduce((total, file) => total + file.size, 0)}>{fileRows}</FileBundle>
          ) : fileRows}
          {transfer?.error && (
            <span className={styles.transferError} role="status">
              {transfer.error}
            </span>
          )}
          {transfer && canChange && (
            <span className={styles.transferActions}>
              {transfer.phase === "failed" && transfer.files.length > 0 && (
                <button
                  type="button"
                  onClick={() =>
                    void perform(() => manager.upload(transfer.id, true))
                  }
                >
                  Retry files &amp; send
                </button>
              )}
              {transfer.phase !== "cancelled" && (
                <button
                  type="button"
                  onClick={() =>
                    void perform(async () => {
                      const recovered = await manager.cancel(transfer.id);
                      change([
                        ...recovered.files,
                        ...(manager.drafts.get(scope) ?? []),
                      ]);
                      setRestoredDrafts((current) =>
                        new Set(current).add(transfer.id),
                      );
                      restoreText(recovered.content);
                    })
                  }
                >
                  Cancel
                </button>
              )}
            </span>
          )}
          {!transfer &&
            canChange &&
            message.preparation &&
            !["none", "ready"].includes(message.preparation) && (
              <span className={styles.transferActions}>
                <span>
                  Upload needs its original device. Cancel to restore the
                  message.
                </span>
                <button
                  type="button"
                  onClick={() =>
                    void perform(async () => {
                      const result = await session.runCloudOperation(
                        (signal) =>
                          session.client.files.cancel(
                            workspaceId,
                            conversationId,
                            message.id,
                            message.revision ?? 0,
                            signal,
                          ),
                        { csrf: true },
                      );
                      restoreText(result.draft.content);
                      change([
                        ...result.draft.files.map((f) => ({
                          id: crypto.randomUUID(),
                          name: f.name,
                          size: remote.find((r) => r.id === f.id)?.size ?? 0,
                        })),
                        ...files,
                      ]);
                    })
                  }
                >
                  Cancel
                </button>
              </span>
            )}
        </span>
      );
    },
  };
}

function FileBundle({ count, size, children }: { count: number; size: number; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const reducedMotion = useReducedMotion();
  return (
    <span className={styles.transferBundle}>
      <button type="button" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        <span className={styles.transferBundleIcon}><FileIcon name="attachments" /></span>
        <span className={styles.transferBundleLabel}>
          <strong>Work attachments</strong>
          <small>{count} files · {(size / 1_000_000).toFixed(1)} MB</small>
        </span>
        <motion.span
          className={styles.transferBundleChevron}
          animate={{ rotate: open ? 180 : 0 }}
          transition={{ duration: reducedMotion ? 0 : .2, ease: [.22, 1, .36, 1] }}
          aria-hidden="true"
        >
          <svg viewBox="0 0 12 12"><path d="m3 4.5 3 3 3-3" /></svg>
        </motion.span>
      </button>
      <AnimatePresence initial={false}>
        {open ? (
          <motion.span
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: reducedMotion ? 0 : .22, ease: [.22, 1, .36, 1] }}
            className={styles.transferBundleReveal}
          >
            <span className={styles.transferBundleFiles}>{children}</span>
          </motion.span>
        ) : null}
      </AnimatePresence>
    </span>
  );
}

function PrivateFilePreview({
  file,
  workspaceId,
  allyId,
  onClose,
}: {
  file: MessageFile;
  workspaceId: string;
  allyId: string;
  onClose: () => void;
}) {
  const session = useSession();
  const reducedMotion = useReducedMotion();
  const [metadata, setMetadata] = useState<FileMetadata | null>(null),
    [url, setUrl] = useState(""),
    [text, setText] = useState(""),
    [error, setError] = useState("");
  const [previewReady, setPreviewReady] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const downloadController = useRef<AbortController | null>(null);
  useEffect(() => () => downloadController.current?.abort(), []);
  useEffect(() => {
    const controller = new AbortController();
    let objectUrl = "";
    void (async () => {
      try {
        setError("");
        setMetadata(null);
        setUrl("");
        setText("");
        setPreviewReady(false);
        const info = await session.runCloudOperation(
          (signal) =>
            session.client.files.metadata(workspaceId, allyId, file.id, signal),
          { signal: controller.signal },
        );
        if (controller.signal.aborted) return;
        setMetadata(info);
        if (info.preview_kind !== "none") {
          let blob: Blob;
          try {
            blob = await session.runCloudOperation(
              (signal) =>
                session.client.files.content(
                  workspaceId,
                  allyId,
                  file.id,
                  true,
                  signal,
                ),
              { signal: controller.signal },
            );
          } catch (previewError) {
            if (controller.signal.aborted) return;
            try {
              blob = await session.runCloudOperation(
                (signal) =>
                  session.client.files.content(
                    workspaceId,
                    allyId,
                    file.id,
                    false,
                    signal,
                  ),
                { signal: controller.signal },
              );
            } catch {
              throw previewError;
            }
          }
          if (controller.signal.aborted) return;
          if (info.preview_kind === "text") {
            const body = await blob.text();
            if (controller.signal.aborted) return;
            setText(body);
            setPreviewReady(true);
          }
          else {
            objectUrl = URL.createObjectURL(blob);
            setUrl(objectUrl);
            setPreviewReady(true);
          }
        }
      } catch {
        if (!controller.signal.aborted)
          setError(
            "We couldn’t open the preview. Try again or download the file.",
          );
      }
    })();
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [
    session.client,
    session.runCloudOperation,
    workspaceId,
    allyId,
    file.id,
    attempt,
  ]);
  const download = async () => {
    downloadController.current?.abort();
    const controller = new AbortController();
    downloadController.current = controller;
    try {
      const blob = await session.runCloudOperation(
        (signal) =>
          session.client.files.content(
            workspaceId,
            allyId,
            file.id,
            false,
            signal,
          ),
        { signal: controller.signal },
      );
      if (controller.signal.aborted) return;
      const objectUrl = URL.createObjectURL(blob),
        link = document.createElement("a");
      link.href = objectUrl;
      link.download = metadata?.name ?? file.name;
      link.click();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 30_000);
    } catch {
      if (!controller.signal.aborted)
        setError("Download failed. Please try again.");
    }
  };
  const previewState = error ? "error" : !metadata ? "loading" : metadata.preview_kind === "none" ? "none" : previewReady ? metadata.preview_kind : "loading";
  return (
    <motion.div className={styles.overlay} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: reducedMotion ? 0 : .18 }}>
      <motion.button
        className={styles.backdrop}
        onClick={onClose}
        aria-label="Close preview"
        tabIndex={-1}
      />
      <motion.section
        className={styles.filePreview}
        initial={{ opacity: 0, y: reducedMotion ? 0 : 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: reducedMotion ? 0 : 4 }} transition={{ duration: reducedMotion ? 0 : .2, ease: [.22, 1, .36, 1] }}
        role="dialog"
        aria-modal="true"
        aria-label={metadata?.name ?? file.name}
        onKeyDown={(e) => {
          if (e.key === "Escape") onClose();
          if (e.key === "Tab") {
            const buttons = [
              ...e.currentTarget.querySelectorAll<HTMLButtonElement>(
                "button:not(:disabled)",
              ),
            ];
            if (e.shiftKey && document.activeElement === buttons[0]) {
              e.preventDefault();
              buttons.at(-1)?.focus();
            } else if (
              !e.shiftKey &&
              document.activeElement === buttons.at(-1)
            ) {
              e.preventDefault();
              buttons[0]?.focus();
            }
          }
        }}
      >
        <header>
          <strong>{metadata?.name ?? file.name}</strong>
          <button
            autoFocus
            type="button"
            onClick={onClose}
            aria-label="Close file"
          >
            ×
          </button>
        </header>
        <p>
          {metadata
            ? `${metadata.type} · ${(metadata.size / 1_000_000).toFixed(1)} MB`
            : "Loading file…"}
        </p>
        <div className={styles.previewBody}><AnimatePresence initial={false} mode="wait"><motion.div key={previewState} className={styles.previewContent} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: reducedMotion ? 0 : .16 }}>
          {error ? (
            <p role="alert" className={styles.previewError}>
              <span>{error}</span>
              <button type="button" onClick={() => setAttempt((a) => a + 1)}>Retry</button>
            </p>
          ) : previewState === "loading" ? <p role="status">Loading preview…</p> : metadata?.preview_kind === "none" ? (
            <p>Preview isn’t available for this file. You can download it.</p>
          ) : metadata?.preview_kind === "text" ? (
            <pre>{text}</pre>
          ) : url && metadata?.preview_kind === "image" ? (
            <img src={url} alt={file.name} />
          ) : url && metadata?.preview_kind === "pdf" ? (
            <iframe sandbox="" src={url} title={file.name} />
          ) : null}
        </motion.div></AnimatePresence></div>
        <footer>
          <button onClick={() => void download()}>Download</button>
        </footer>
      </motion.section>
    </motion.div>
  );
}

function FilePublications({
  messageId,
  publications,
  workspaceId,
  allyId,
  onOpen,
}: {
  messageId: string;
  publications: FilePublication[];
  workspaceId: string;
  allyId: string;
  onOpen: (file: MessageFile) => void;
}) {
  const session = useSession(),
    queryClient = useQueryClient();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const pending = publications.some((p) =>
    ["uploading", "validating", "retry_pending"].includes(p.state),
  );
  const key = publications
    .map((p) => p.publication_id + ":" + p.revision + ":" + p.state)
    .join("|");
  useEffect(() => {
    if (!pending) return;
    let attempts = 0;
    const timer = setInterval(() => {
      void queryClient.invalidateQueries({
        queryKey: conversationQueryKey(workspaceId, allyId),
      });
      if (++attempts >= 30) clearInterval(timer);
    }, 2000);
    return () => clearInterval(timer);
  }, [key, pending, queryClient, workspaceId, allyId]);
  if (!publications.length) return null;
  return (
    <div className={styles.publications}>
      {publications.map((publication) => (
        <div key={publication.publication_id}>
          {publication.state === "ready" ? (
            publication.files.map((file) => (
              <button
                type="button"
                key={file.id}
                className={styles.fileLink}
                onClick={() => onOpen(file)}
              >
                <FileIcon />
                {file.name}
              </button>
            ))
          ) : (
            <span>
              {publication.state === "failed"
                ? "Returning the file failed."
                : publication.state === "cancelled"
                  ? "File return cancelled."
                  : "Preparing files…"}
            </span>
          )}
          {publication.retryable && (
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                setBusy(true);
                setError("");
                void session
                  .runCloudOperation(
                    (signal) =>
                      session.client.files.retryPublication(
                        workspaceId,
                        allyId,
                        messageId,
                        publication.publication_id,
                        publication.revision,
                        signal,
                      ),
                    { csrf: true },
                  )
                  .then(() =>
                    queryClient.invalidateQueries({
                      queryKey: conversationQueryKey(workspaceId, allyId),
                    }),
                  )
                  .catch(() =>
                    setError(
                      "File retry could not be confirmed. Check again before retrying.",
                    ),
                  )
                  .finally(() => setBusy(false));
              }}
            >
              Retry returned file
            </button>
          )}
        </div>
      ))}
      {pending || error ? (
        <button
          type="button"
          onClick={() =>
            void queryClient.invalidateQueries({
              queryKey: conversationQueryKey(workspaceId, allyId),
            })
          }
        >
          Check files again
        </button>
      ) : null}
      {error && <span role="alert">{error}</span>}
    </div>
  );
}

function FileThumbnail({
  id,
  name,
  src,
  ready,
  workspaceId,
  allyId,
}: {
  id: string;
  name: string;
  src?: string;
  ready: boolean;
  workspaceId: string;
  allyId: string;
}) {
  const session = useSession(),
    element = useRef<HTMLSpanElement>(null);
  const [url, setUrl] = useState(src ?? "");
  const image = /\.(jpg|jpeg|png|gif|webp|heic|heif)$/i.test(name);
  useEffect(() => {
    if (src || !image || !ready || !element.current) return;
    const controller = new AbortController();
    let objectUrl = "";
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      observer.disconnect();
      void session
        .runCloudOperation(
          (signal) =>
            session.client.files.content(workspaceId, allyId, id, true, signal),
          { signal: controller.signal },
        )
        .then((blob) => {
          if (controller.signal.aborted || !blob.type.startsWith("image/"))
            return;
          objectUrl = URL.createObjectURL(blob);
          setUrl(objectUrl);
        })
        .catch(() => undefined);
    });
    observer.observe(element.current);
    return () => {
      controller.abort();
      observer.disconnect();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [
    src,
    image,
    ready,
    workspaceId,
    allyId,
    id,
    session.client,
    session.runCloudOperation,
  ]);
  return (
    <span ref={element}>
      {src || url ? <img src={src || url} alt="" /> : <FileIcon />}
    </span>
  );
}
