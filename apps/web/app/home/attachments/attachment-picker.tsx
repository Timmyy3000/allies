"use client";

import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { FILE_EXTENSIONS, validateSelectedFiles } from "@allies/cloud-client";
import { selectedFile, type SelectedFile } from "../../../lib/files/transfers";
import styles from "./attachments.module.css";

type Mode = "menu" | "photos" | "files" | "camera";
const paths = {
  camera: "M8 5l1-2h6l1 2h4v15H4V5h4M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0",
  photos: "M4 4h16v16H4zM4 16l5-5 4 4 3-3 4 4M8 8h.01",
  files: "M6 3h8l4 4v14H6zM14 3v5h4M9 13h6M9 16h4",
  back: "m14 6-6 6 6 6",
  close: "m6 6 12 12M18 6 6 18",
};
export function FileIcon({ name = "files" }: { name?: keyof typeof paths }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d={paths[name]} />
    </svg>
  );
}

export function middleEllipsis(value: string, maximum = 36) {
  const characters = Array.from(value);
  if (characters.length <= maximum) return value;
  const retained = maximum - 1;
  const start = Math.ceil(retained * .6);
  return `${characters.slice(0, start).join("")}…${characters.slice(-(retained - start)).join("")}`;
}

export function AttachmentTray({
  files,
  arriving,
  onRemove,
  onReselect,
}: {
  files: SelectedFile[];
  arriving: Set<string>;
  onRemove: (id: string) => void;
  onReselect?: (id: string, file: File) => void;
}) {
  const reduced = useReducedMotion();
  return (
    <div className={styles.tray}>
      <AnimatePresence initial={false} mode="popLayout">
        {files.map((file) => (
          <motion.span
            layout="position"
            transition={{
              type: "spring",
              duration: reduced ? 0 : 0.46,
              bounce: 0,
            }}
            exit={{
              opacity: 0,
              scale: 0.96,
              transition: { duration: reduced ? 0 : 0.16 },
            }}
            className={styles.thumb}
            style={{ visibility: arriving.has(file.id) ? "hidden" : "visible" }}
            data-attachment={file.id}
            key={file.id}
          >
            {file.src ? (
              <img src={file.src} alt={file.name} />
            ) : (
              <span className={styles.documentThumb}>
                <FileIcon />
                <small title={file.name}>{middleEllipsis(file.name, 24)}</small>
              </span>
            )}
            <button
              type="button"
              aria-label={`Remove ${file.name}`}
              onClick={() => onRemove(file.id)}
            >
              ×
            </button>
            {!file.file && onReselect && (
              <label className={styles.reselect}>
                Choose again
                <input
                  type="file"
                  aria-label={`Choose ${file.name} again`}
                  onChange={(e) => {
                    const next = e.target.files?.[0];
                    if (next) onReselect(file.id, next);
                    e.target.value = "";
                  }}
                />
              </label>
            )}
          </motion.span>
        ))}
      </AnimatePresence>
    </div>
  );
}

export async function animateAttachments(
  files: SelectedFile[],
  origin: DOMRect | undefined,
  reduced: boolean,
  reveal: (id: string) => void,
) {
  await new Promise<void>((resolve) =>
    requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
  );
  await Promise.all(
    files.map(async (file, index) => {
      const target = document.querySelector<HTMLElement>(
        `[data-attachment="${file.id}"]`,
      );
      if (!target || !origin || index > 3 || reduced) {
        reveal(file.id);
        return;
      }
      const end = target.getBoundingClientRect();
      const container = target.closest<HTMLElement>("[data-attachment-reveal]");
      const expansion = container
        ? Math.max(
            0,
            container.scrollHeight - container.getBoundingClientRect().height,
          )
        : 0;
      const flyer = document.createElement("div");
      flyer.className = styles.flyer;
      flyer.setAttribute("aria-hidden", "true");
      if (file.src) {
        const img = document.createElement("img");
        img.src = file.src;
        img.alt = "";
        flyer.append(img);
      } else {
        const placeholder = target
          .querySelector(`.${styles.documentThumb}`)
          ?.cloneNode(true);
        if (placeholder) flyer.append(placeholder);
      }
      Object.assign(flyer.style, {
        left: `${origin.left}px`,
        top: `${origin.top}px`,
        width: `${origin.width}px`,
        height: `${origin.height}px`,
      });
      document.body.append(flyer);
      try {
        await flyer.animate(
          [
            {
              transform: "translate(0,0)",
              width: `${origin.width}px`,
              height: `${origin.height}px`,
              borderRadius: "30px",
              boxShadow: "0 12px 30px #0002",
            },
            {
              transform: `translate(${end.left - origin.left}px,${end.top - expansion - origin.top}px)`,
              width: `${end.width}px`,
              height: `${end.height}px`,
              borderRadius: "18px",
              boxShadow: "0 0 0 #0000",
            },
          ],
          {
            duration: 620,
            delay: index * 35,
            easing: "cubic-bezier(.22,1,.36,1)",
            fill: "forwards",
          },
        ).finished;
        reveal(file.id);
        await flyer.animate([{ opacity: 1 }, { opacity: 0 }], {
          duration: 110,
          fill: "forwards",
        }).finished;
      } finally {
        flyer.remove();
        reveal(file.id);
      }
    }),
  );
}

export function AttachmentPicker({
  onClose,
  onAdd,
  existing,
  accent,
  anchor,
}: {
  onClose: () => void;
  onAdd: (files: SelectedFile[], origin?: DOMRect) => void;
  existing: SelectedFile[];
  accent: string;
  anchor: HTMLElement | null;
}) {
  const [mode, setMode] = useState<Mode>("menu");
  const [selection, setSelection] = useState<SelectedFile[]>([]);
  const [error, setError] = useState("");
  const [live, setLive] = useState(false);
  const [placement, setPlacement] = useState<CSSProperties>({
    visibility: "hidden",
  });
  useLayoutEffect(() => {
    const composer = anchor?.closest<HTMLElement>(
      '[data-testid="conversation-composer"]',
    );
    if (!composer) return;
    const place = () => {
      const rect = composer.getBoundingClientRect();
      const viewport = window.visualViewport;
      const leftEdge = (viewport?.offsetLeft ?? 0) + 16;
      const rightEdge = leftEdge + (viewport?.width ?? window.innerWidth) - 32;
      const width = Math.min(
        mode === "menu" ? 222 : 440,
        rect.width,
        rightEdge - leftEdge,
      );
      setPlacement({
        left: Math.max(leftEdge, Math.min(rect.left, rightEdge - width)),
        bottom: window.innerHeight - rect.top + 8,
        width,
        maxHeight: Math.max(0, rect.top - (viewport?.offsetTop ?? 0) - 24),
      });
    };
    place();
    const observer = new ResizeObserver(place);
    observer.observe(composer);
    window.addEventListener("resize", place);
    window.visualViewport?.addEventListener("resize", place);
    window.visualViewport?.addEventListener("scroll", place);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", place);
      window.visualViewport?.removeEventListener("resize", place);
      window.visualViewport?.removeEventListener("scroll", place);
    };
  }, [anchor, mode]);
  const surface = useRef<HTMLDivElement>(null),
    video = useRef<HTMLVideoElement>(null),
    input = useRef<HTMLInputElement>(null),
    nativeCamera = useRef<HTMLInputElement>(null);
  const stream = useRef<MediaStream | null>(null),
    request = useRef(0),
    selectedRef = useRef(selection),
    transferred = useRef(false);
  useEffect(() => {
    selectedRef.current = selection;
  }, [selection]);
  const reduced = useReducedMotion();
  useEffect(() => {
    const focus = document.activeElement as HTMLElement;
    return () => {
      request.current++;
      stream.current?.getTracks().forEach((track) => track.stop());
      if (!transferred.current)
        selectedRef.current.forEach((f) => {
          if (f.src) URL.revokeObjectURL(f.src);
        });
      focus?.focus();
    };
  }, []);
  useEffect(() => {
    if (mode !== "camera") return;
    let disposed = false;
    const current = ++request.current;
    if (!navigator.mediaDevices?.getUserMedia) return;
    void navigator.mediaDevices
      .getUserMedia({ video: { facingMode: "environment" }, audio: false })
      .then((media) => {
        if (disposed || current !== request.current) {
          media.getTracks().forEach((track) => track.stop());
          return;
        }
        stream.current = media;
        setLive(true);
      })
      .catch(() => {
        if (!disposed)
          setError(
            "Camera unavailable. Use your device camera, Photos, or Files.",
          );
      });
    return () => {
      disposed = true;
      stream.current?.getTracks().forEach((track) => track.stop());
      stream.current = null;
      setLive(false);
    };
  }, [mode]);
  useEffect(() => {
    if (live && video.current) video.current.srcObject = stream.current;
  }, [live]);
  function add(files: SelectedFile[]) {
    try {
      validateSelectedFiles([...existing, ...files]);
      selectedRef.current
        .filter((f) => !files.includes(f))
        .forEach((f) => {
          if (f.src) URL.revokeObjectURL(f.src);
        });
      transferred.current = true;
      onAdd(files, surface.current?.getBoundingClientRect());
    } catch (e) {
      files
        .filter((f) => !selectedRef.current.includes(f))
        .forEach((f) => {
          if (f.src) URL.revokeObjectURL(f.src);
        });
      setError(
        e instanceof Error ? e.message : "These files could not be added.",
      );
    }
  }
  async function capture() {
    if (!video.current?.videoWidth) return;
    const canvas = document.createElement("canvas");
    canvas.width = video.current.videoWidth;
    canvas.height = video.current.videoHeight;
    canvas.getContext("2d")?.drawImage(video.current, 0, 0);
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", 0.9),
    );
    if (blob)
      add([
        selectedFile(
          new File([blob], `Photo-${Date.now()}.jpg`, { type: "image/jpeg" }),
        ),
      ]);
  }
  function choose(files: File[]) {
    try {
      validateSelectedFiles([...existing, ...selection, ...files]);
      setSelection((previous) => [...previous, ...files.map(selectedFile)]);
      setError("");
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "These files could not be added.",
      );
    }
  }
  return (
    <motion.div
      className={styles.overlay}
      style={{ "--accent": accent } as CSSProperties}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: reduced ? 0 : 0.22 }}
    >
      <button
        className={styles.backdrop}
        onClick={onClose}
        aria-label="Dismiss attachments"
        tabIndex={-1}
      />
      <motion.div
        layout
        ref={surface}
        style={placement}
        role="dialog"
        aria-modal="true"
        aria-label="Attachments"
        className={`${styles.surface} ${mode === "menu" ? styles.menuSurface : styles.expanded} ${mode === "camera" ? styles.cameraSurface : ""}`}
        transition={{ type: "spring", duration: reduced ? 0 : 0.48, bounce: 0 }}
        initial={{ opacity: 0, y: 12, scale: 0.96 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 6, scale: 0.98 }}
        onKeyDown={(event) => {
          if (event.key === "Escape") onClose();
          if (event.key === "Tab") {
            const buttons = [
              ...(surface.current?.querySelectorAll<HTMLButtonElement>(
                "button:not(:disabled)",
              ) ?? []),
            ];
            const first = buttons[0],
              last = buttons.at(-1);
            if (event.shiftKey && document.activeElement === first) {
              event.preventDefault();
              last?.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
              event.preventDefault();
              first?.focus();
            }
          }
        }}
      >
        <AnimatePresence mode="popLayout" initial={false}>
          <motion.div
            className={styles.panel}
            key={mode}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: reduced ? 0 : 0.18 }}
          >
            {mode === "menu" ? (
              <div className={styles.menu}>
                {(["camera", "photos", "files"] as const).map((item, index) => (
                  <motion.button
                    autoFocus={index === 0}
                    key={item}
                    onClick={() => {
                      setMode(item);
                      setError("");
                    }}
                    whileTap={{ scale: 0.96 }}
                  >
                    <span>
                      <FileIcon name={item} />
                    </span>
                    {item[0].toUpperCase() + item.slice(1)}
                  </motion.button>
                ))}
              </div>
            ) : (
              <>
                {mode === "camera" && live && (
                  <video
                    ref={video}
                    className={styles.cameraImage}
                    autoPlay
                    muted
                    playsInline
                  />
                )}
                <div className={styles.heading}>
                  <button
                    autoFocus
                    onClick={() => setMode("menu")}
                    aria-label="Back to attachment options"
                  >
                    <FileIcon name="back" />
                  </button>
                  <strong>{mode[0].toUpperCase() + mode.slice(1)}</strong>
                  <button onClick={onClose} aria-label="Close attachments">
                    <FileIcon name="close" />
                  </button>
                </div>
                {mode === "camera" ? (
                  <>
                    <p className={styles.cameraNote}>
                      {error ||
                        (live
                          ? "Ready when you are"
                          : "Use your device camera to take a photo.")}
                    </p>
                    <div className={styles.cameraControls}>
                      <button
                        onClick={() => nativeCamera.current?.click()}
                        aria-label="Use device camera"
                      >
                        <FileIcon name="camera" />
                      </button>
                      <button
                        className={styles.shutter}
                        disabled={!live}
                        onClick={() => void capture()}
                        aria-label="Take photo"
                      />
                      <button
                        onClick={() => setMode("photos")}
                        aria-label="Choose photos"
                      >
                        <FileIcon name="photos" />
                      </button>
                    </div>
                  </>
                ) : (
                  <>
                    <div className={styles.body}>
                      <button
                        className={styles.browse}
                        onClick={() => input.current?.click()}
                      >
                        <FileIcon name={mode} />
                        Choose from your device
                      </button>
                      <p className={styles.sectionLabel}>
                        {selection.length
                          ? "SELECTED"
                          : "UP TO 10 FILES · 25 MB EACH"}
                      </p>
                      {error && <p role="alert">{error}</p>}
                      <div
                        className={
                          mode === "photos" ? styles.grid : styles.list
                        }
                      >
                        {selection.map((item) => (
                          <button
                            className={`${mode === "photos" ? styles.photo : styles.file} ${styles.selected}`}
                            key={item.id}
                            onClick={() => {
                              if (item.src) URL.revokeObjectURL(item.src);
                              setSelection((current) =>
                                current.filter((f) => f.id !== item.id),
                              );
                            }}
                            aria-label={`Remove ${item.name}`}
                          >
                            {item.src && mode === "photos" ? (
                              <img src={item.src} alt={item.name} />
                            ) : (
                              <>
                                <span className={styles.fileIcon}>
                                  <FileIcon />
                                </span>
                                <span className={styles.fileName}>
                                  {item.name}
                                  <small>
                                    {(item.size / 1_000_000).toFixed(1)} MB
                                  </small>
                                </span>
                              </>
                            )}
                            <span className={styles.check}>✓</span>
                          </button>
                        ))}
                      </div>
                    </div>
                    <div className={styles.footer}>
                      <button
                        disabled={!selection.length}
                        onClick={() => add(selection)}
                      >
                        {selection.length
                          ? `Add ${selection.length} attachment${selection.length > 1 ? "s" : ""}`
                          : "Choose files to add"}
                      </button>
                    </div>
                  </>
                )}
              </>
            )}
          </motion.div>
        </AnimatePresence>
      </motion.div>
      <input
        type="file"
        ref={input}
        hidden
        multiple
        accept={
          mode === "photos"
            ? ".jpg,.jpeg,.png,.gif,.webp,.heic,.heif"
            : FILE_EXTENSIONS.map((ext) => `.${ext}`).join(",")
        }
        onChange={(e) => {
          choose([...(e.target.files ?? [])]);
          e.target.value = "";
        }}
      />
      <input
        type="file"
        ref={nativeCamera}
        hidden
        accept="image/*"
        capture="environment"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) add([selectedFile(file)]);
          e.target.value = "";
        }}
      />
    </motion.div>
  );
}
