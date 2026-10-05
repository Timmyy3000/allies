"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { ConversationFrame } from "../../home/conversation-frame";
import type { ProductionConversationFrameModel, ProductionConversationMessageModel } from "../../home/conversation-frame-model";
import styles from "./preview.module.css";

type Attachment = { id: string; name: string; src?: string; size: number };
type Mode = "menu" | "photos" | "files" | "camera" | null;
const paths = {
  camera: "M8 5l1-2h6l1 2h4v15H4V5h4M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0",
  photos: "M4 4h16v16H4zM4 16l5-5 4 4 3-3 4 4M8 8h.01",
  files: "M6 3h8l4 4v14H6zM14 3v5h4M9 13h6M9 16h4",
  back: "m14 6-6 6 6 6", close: "m6 6 12 12M18 6 6 18",
};
function Icon({ name }: { name: keyof typeof paths }) {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d={paths[name]} /></svg>;
}
function scene(i: number) {
  const colors = [["#dcd8ca", "#84916f"], ["#e6d5c4", "#b7836b"], ["#cad7d7", "#668589"], ["#e0d2d8", "#a18392"], ["#d7ddc5", "#889b65"], ["#d4c7b8", "#93816d"]][i % 6];
  return "data:image/svg+xml," + encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800"><rect width="600" height="800" fill="${colors[0]}"/><path d="M0 500 600 380V800H0" fill="${colors[1]}" opacity=".2"/><ellipse cx="310" cy="660" rx="220" ry="45" fill="${colors[1]}" opacity=".15"/><rect x="170" y="350" width="260" height="290" rx="90" fill="${colors[1]}"/><ellipse cx="300" cy="370" rx="130" ry="45" fill="${colors[0]}"/><path d="M300 360Q190 110 320 80Q390 250 300 360M300 340Q480 150 480 270Q440 350 300 340" fill="${colors[1]}"/><circle cx="105" cy="130" r="55" fill="white" opacity=".5"/></svg>`);
}
const samples: Attachment[] = Array.from({ length: 9 }, (_, i) => ({ id: `photo-${i}`, name: `Study ${i + 1}.jpg`, src: scene(i), size: 248000 }));
const documents: Attachment[] = ["Weekend plans.pdf", "Project notes.docx", "A few ideas.md", "Reading list.pdf"].map((name, i) => ({ id: `file-${i}`, name, size: (i + 1) * 42000 }));
const initialMessages: ProductionConversationMessageModel[] = [
  { id: "hello", sender: "assistant", content: "Hey! What are we working on today?", sequence: 1, createdAt: "2026-09-10T14:00:00Z", statusLabel: null, retryable: false },
  { id: "context", sender: "user", content: "I have a few things I’d like to share with you.", sequence: 2, createdAt: "2026-09-10T14:01:00Z", statusLabel: null, retryable: false },
  { id: "reply", sender: "assistant", content: "Of course. Add a photo or a file, and tell me what you have in mind.", sequence: 3, createdAt: "2026-09-10T14:02:00Z", statusLabel: null, retryable: false },
];

export default function AttachmentPreview() {
  const [mode, setMode] = useState<Mode>(null);
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState(initialMessages);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [sent, setSent] = useState<Record<string, Attachment[]>>({});
  const [selected, setSelected] = useState<string[]>([]);
  const [notice, setNotice] = useState("");
  const [slow, setSlow] = useState(false);
  const [cameraScene, setCameraScene] = useState(0);
  const [live, setLive] = useState(false);
  const [busy, setBusy] = useState(false);
  const [arriving, setArriving] = useState<string[]>([]);
  const reduced = useReducedMotion();
  const surface = useRef<HTMLDivElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const cameraRequest = useRef(0);
  const input = useRef<HTMLInputElement>(null);
  const canvas = useRef<HTMLDivElement>(null);
  const objectUrls = useRef<string[]>([]);
  const trigger = useRef<HTMLElement | null>(null);
  const duration = reduced ? 0 : slow ? 1.25 : .48;
  const spring = { type: "spring" as const, duration, bounce: 0 };
  const stopCamera = () => { cameraRequest.current++; stream.current?.getTracks().forEach(t => t.stop()); stream.current = null; setLive(false); };
  useEffect(() => () => { cameraRequest.current++; stream.current?.getTracks().forEach(t => t.stop()); objectUrls.current.forEach(URL.revokeObjectURL); }, []);
  useEffect(() => { if (live && video.current) video.current.srcObject = stream.current; }, [live]);
  useEffect(() => { if (!notice) return; const t = setTimeout(() => setNotice(""), 4500); return () => clearTimeout(t); }, [notice]);
  useEffect(() => { canvas.current?.scrollTo({ top: canvas.current.scrollHeight, behavior: "smooth" }); }, [messages]);
  function close() { if (busy) return; stopCamera(); setMode(null); trigger.current?.focus(); }
  function open(next: Mode) { stopCamera(); setSelected([]); setMode(next); }
  async function enableCamera() {
    if (!navigator.mediaDevices?.getUserMedia) { setNotice("Live camera needs HTTPS. Try the sample shutter here."); return; }
    const request = ++cameraRequest.current;
    try {
      const media = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
      if (cameraRequest.current !== request) { media.getTracks().forEach(t => t.stop()); return; }
      stream.current = media; setLive(true);
    } catch { setNotice("Camera unavailable. Photos and Files are still available."); }
  }
  async function collect(items: Attachment[], fromCamera = false) {
    if (busy || !items.length) return;
    if (attachments.length + items.length > 10 || items.some(i => i.size > 25 * 1024 * 1024) || [...attachments, ...items].reduce((n, i) => n + i.size, 0) > 50 * 1024 * 1024) {
      setNotice("Up to 10 files, 25 MB each and 50 MB altogether."); return;
    }
    const source = fromCamera ? surface.current?.getBoundingClientRect() : undefined;
    const copies = items.map((a, i) => ({ ...a, id: `attached-${Date.now()}-${i}` }));
    const origins = items.map(a => source ?? document.querySelector(`[data-source="${a.id}"]`)?.getBoundingClientRect() ?? surface.current?.getBoundingClientRect());
    setBusy(true); setArriving(copies.map(a => a.id)); setAttachments(prev => [...prev, ...copies]);
    await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
    const flights = copies.map((a, i) => {
      const target = document.querySelector<HTMLElement>(`[data-attachment="${a.id}"]`);
      if (!target || !origins[i]) return Promise.resolve();
      const start = origins[i]!;
      const end = target.getBoundingClientRect();
      const reveal = target.closest<HTMLElement>("[data-attachment-reveal]");
      const remainingExpansion = reveal ? Math.max(0, reveal.scrollHeight - reveal.getBoundingClientRect().height) : 0;
      const endTop = end.top - remainingExpansion;
      const flyer = document.createElement("div");
      flyer.className = styles.flyer;
      flyer.setAttribute("aria-hidden", "true");
      if (a.src) {
        const image = document.createElement("img"); image.src = a.src; image.alt = ""; flyer.append(image);
      } else {
        const placeholder = target.querySelector(`.${styles.documentThumb}`)?.cloneNode(true);
        if (placeholder) flyer.append(placeholder);
      }
      Object.assign(flyer.style, { left: `${start.left}px`, top: `${start.top}px`, width: `${start.width}px`, height: `${start.height}px` });
      document.body.append(flyer);
      const flightDuration = reduced ? 1 : slow ? 1500 : 620;
      return flyer.animate([
        { transform: "translate(0,0)", width: `${start.width}px`, height: `${start.height}px`, borderRadius: fromCamera ? "30px" : "14px", boxShadow: "0 12px 30px #0002" },
        { transform: `translate(${end.left - start.left}px,${endTop - start.top}px)`, width: `${end.width}px`, height: `${end.height}px`, borderRadius: "18px", boxShadow: "0 0 0 #0000" },
      ], { duration: flightDuration, delay: reduced ? 0 : i * 35, easing: "cubic-bezier(.22,1,.36,1)", fill: "forwards" }).finished.then(async () => {
        setArriving(prev => prev.filter(id => id !== a.id));
        await flyer.animate([{ opacity: 1 }, { opacity: 0 }], { duration: reduced ? 1 : 110, fill: "forwards" }).finished;
      }).finally(() => flyer.remove());
    });
    stopCamera(); setMode(null); await Promise.all(flights); setBusy(false); trigger.current?.focus();
  }
  function capture() {
    let src = scene(cameraScene);
    if (live && video.current) {
      const c = document.createElement("canvas"); c.width = video.current.videoWidth; c.height = video.current.videoHeight;
      if (!c.width) { setNotice("Camera is still starting."); return; }
      c.getContext("2d")?.drawImage(video.current, 0, 0); src = c.toDataURL("image/jpeg", .9);
    }
    void collect([{ id: "capture", name: "Photo.jpg", src, size: Math.ceil(src.length * .75) }], true);
  }
  function send() {
    if (busy || (!draft.trim() && !attachments.length)) return;
    const id = `message-${Date.now()}`;
    setSent(prev => ({ ...prev, [id]: attachments }));
    setMessages(prev => [...prev, { id, sender: "user", content: draft, sequence: prev.length + 1, createdAt: new Date().toISOString(), statusLabel: "Local preview", retryable: false }]);
    setDraft(""); setAttachments([]);
  }
  const model: ProductionConversationFrameModel = {
    ally: { name: "Sally", job: "Your everyday ally", shape: "ghosty", accent: "#FD304F", supportedAppearance: true },
    messages, turns: [], activityGroups: [], activityState: "completed", pendingAssistantText: [],
    timeline: { isLoading: false, loadError: null, accessFailure: null, accessCopy: null, olderMessagesAvailable: false, loadingOlder: false, olderLoadError: null, workspaceRefreshError: false, activityError: null, activityHistoryError: null, activityReplayUnavailable: false, pollBudgetReached: false, retryError: null },
    composer: { draft, placeholder: "Reply Sally", disabled: busy, sending: false, sendError: null, unavailableNotice: null },
    queuedMessages: [], showThinkingState: false, responseStarted: false, gettingReady: false, streaming: false, firstAssistantMessageId: "hello", retriedMessageIds: [], retryingMessageId: null,
  };
  const noop = () => {};
  return <main className={styles.preview}>
    <div className={styles.reviewBar}><span>Attachment preview · stays on this device</span><button onClick={() => setSlow(!slow)}>{slow ? "Normal speed" : "Slow motion"}</button></div>
    <div className={styles.chat} inert={mode ? true : undefined}>
      <ConversationFrame model={model} canvasRef={canvas} actions={{ onDraftChange: setDraft, onSubmit: send, onRetryMessage: noop, onLoadOlder: noop, onRetryConversation: noop, onRetryWorkspace: noop, onRemoveQueuedMessage: noop, onCheckAgain: noop, onRetryActivityHistory: noop, onScroll: noop }}
        onAttach={() => { trigger.current = document.activeElement as HTMLElement; (document.activeElement as HTMLElement)?.blur(); open("menu"); }}
        attachments={attachments.length ? <div className={styles.tray}><AnimatePresence initial={false} mode="popLayout">{attachments.map(a => <motion.span layout="position" transition={spring} exit={{ opacity: 0, scale: .96, transition: { duration: reduced ? 0 : .16 } }} className={styles.thumb} style={{ visibility: arriving.includes(a.id) ? "hidden" : "visible" }} data-attachment={a.id} key={a.id}>{a.src ? <img src={a.src} alt={a.name} /> : <span className={styles.documentThumb}><Icon name="files" /><small>{a.name}</small></span>}<button type="button" disabled={busy} aria-label={`Remove ${a.name}`} onClick={() => setAttachments(prev => prev.filter(item => item.id !== a.id))}>×</button></motion.span>)}</AnimatePresence></div> : undefined}
        messageAttachments={id => sent[id]?.length ? <span className={styles.sentFiles}>{sent[id].map(a => <span key={a.id}>{a.src ? <img src={a.src} alt={a.name} /> : <span className={styles.sentDocument}><Icon name="files" />{a.name}</span>}</span>)}</span> : null}
      />
    </div>
    <AnimatePresence>{mode && <motion.div className={styles.overlay} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: reduced ? 0 : .22 }}>
      <button className={styles.backdrop} onClick={close} aria-label="Dismiss attachments" tabIndex={-1} />
      <motion.div ref={surface} layout className={`${styles.surface} ${mode === "menu" ? styles.menuSurface : styles.expanded} ${mode === "camera" ? styles.cameraSurface : ""}`} transition={spring} initial={{ opacity: 0, y: 12, scale: .96 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 6, scale: .98 }} role="dialog" aria-modal="true" aria-label="Attachments" onKeyDown={e => {
        if (e.key === "Escape") close();
        if (e.key === "Tab") { const buttons = [...(surface.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") ?? [])]; const first = buttons[0], last = buttons.at(-1); if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); } else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); } }
      }}>
        <AnimatePresence mode="popLayout" initial={false}><motion.div key={mode} className={styles.panel} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={{ duration: reduced ? 0 : .18, delay: .04 }}>
          {mode === "menu" ? <div className={styles.menu}>{(["camera", "photos", "files"] as const).map((m, i) => <motion.button autoFocus={i === 0} key={m} onClick={() => open(m)} whileTap={{ scale: .96 }}><span><Icon name={m} /></span>{m[0].toUpperCase() + m.slice(1)}</motion.button>)}</div> : <>
            {mode === "camera" && <>{live ? <video ref={video} autoPlay muted playsInline className={styles.cameraImage} /> : <img className={styles.cameraImage} src={scene(cameraScene)} alt="Sample camera scene" />}</>}
            <div className={styles.heading}><button autoFocus onClick={() => open("menu")} aria-label="Back to attachment options"><Icon name="back" /></button><strong>{mode === "camera" ? live ? "Camera" : "Sample camera" : mode === "photos" ? "Photos" : "Files"}</strong><button onClick={close} aria-label="Close attachments"><Icon name="close" /></button></div>
            {mode === "camera" ? <><div className={styles.cameraNote}>{live ? "Ready when you are" : "Try the shutter, or enable your camera"}</div><div className={styles.cameraControls}><button onClick={enableCamera} aria-label="Enable live camera"><Icon name="camera" /></button><button className={styles.shutter} onClick={capture} aria-label="Take photo" /><button onClick={() => setCameraScene(i => i + 1)} aria-label="Change sample scene">↻</button></div></> : <><div className={styles.body}><button className={styles.browse} onClick={() => input.current?.click()}><Icon name={mode} />Choose from your device</button><p className={styles.sectionLabel}>{mode === "photos" ? "SAMPLE PHOTOS" : "SAMPLE FILES"}</p><div className={mode === "photos" ? styles.grid : styles.list}>{(mode === "photos" ? samples : documents).map(a => <button key={a.id} data-source={a.id} className={`${mode === "photos" ? styles.photo : styles.file} ${selected.includes(a.id) ? styles.selected : ""}`} aria-label={`Select ${a.name}`} aria-pressed={selected.includes(a.id)} onClick={() => setSelected(prev => prev.includes(a.id) ? prev.filter(id => id !== a.id) : [...prev, a.id])}>{a.src ? <img src={a.src} alt={a.name} /> : <><span className={styles.fileIcon}><Icon name="files" /></span><span className={styles.fileName}>{a.name}<small>{Math.round(a.size / 1000)} KB</small></span></>}<span className={styles.check}>{selected.includes(a.id) ? "✓" : ""}</span></button>)}</div></div><div className={styles.footer}><button disabled={!selected.length} onClick={() => void collect([...samples, ...documents].filter(a => selected.includes(a.id)))}>{selected.length ? `Add ${selected.length} attachment${selected.length > 1 ? "s" : ""}` : `Select ${mode}`}</button></div></>}
          </>}
        </motion.div></AnimatePresence>
      </motion.div>
    </motion.div>}</AnimatePresence>
    <input ref={input} type="file" hidden multiple accept={mode === "photos" ? "image/*" : ".pdf,.doc,.docx,.xls,.xlsx,.csv,.ppt,.pptx,.txt,.md,.js,.ts,.html,.css,.json,.py,image/*"} onChange={e => { const items = [...(e.target.files ?? [])].map((f, i) => { const src = f.type.startsWith("image/") ? URL.createObjectURL(f) : undefined; if (src) objectUrls.current.push(src); return { id: `device-${Date.now()}-${i}`, name: f.name, src, size: f.size }; }); void collect(items); e.target.value = ""; }} />
    {notice && <div className={styles.notice} role="status">{notice}</div>}
  </main>;
}
