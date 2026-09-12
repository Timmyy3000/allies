"use client";

import { useId, useRef, useState, type ReactNode } from "react";
import { AnimatePresence, motion } from "motion/react";
import frame from "../../home/conversation-frame.module.css";
import toast from "../../home/recipes-button.module.css";
import styles from "./transitions.module.css";

export const extraCases = [
  { id: "paste", title: "Pasted text", number: "04", subtitle: "Give a long thought some room.", description: "A long paste becomes a compact card in the composer. Ease the card into place and close the space when it is removed.", before: "The pasted-text card mounts immediately.", after: "The card fades in as the composer makes room.", source: "ConversationComposer · pasted-text branch", note: "Source-matched isolated composer fixture. Use Add pasted text, remove it, or open the local text editor. The disabled microphone is omitted.", actions: ["Add pasted text", "Remove pasted text"] },
  { id: "save", title: "Save feedback", number: "05", subtitle: "Make the saved state unmistakable.", description: "Keep the action in one place as it moves from Save to Saving to Saved. Only confirmed success receives a check.", before: "Saving replaces the label; success appears below.", after: "The label changes within a stable button. Success settles into a check.", source: "AllySettingsDetails / account save states", note: "Isolated save-state fixture with a simulated response. Try both success and failure; no account data is changed.", actions: ["Save both", "Saving…", "Save again", "Retry both"] },
  { id: "upload", title: "File status", number: "06", subtitle: "A steady filename. A clearer status.", description: "Move from uploading to checking to ready without moving the file or animating every percentage.", before: "The status text is replaced immediately.", after: "Only the status crossfades; the ready state gets a quiet check.", source: "useConversationFiles · file transfer status", note: "Source-matched file-row fixture. Advance the simulated transfer or try an error. Ready means validation completed, not just that upload reached 100%.", actions: ["Start upload", "Finish upload", "Finish checking", "Restart upload", "Retry upload"] },
  { id: "preview", title: "File preview", number: "07", subtitle: "Bring the file into view.", description: "A quiet overlay entrance, followed by a content fade once the preview is ready. Keep controls in place throughout.", before: "The overlay and loaded content mount directly.", after: "The surface eases in; content fades into a reserved area.", source: "PrivateFilePreview · overlay and loading states", note: "Isolated preview fixture using a local sample illustration. Open it, load its content, or simulate a load failure. No private file is fetched.", actions: ["Open previews", "Load previews", "Close previews", "Retry previews"] },
  { id: "prompt", title: "Routine prompt", number: "08", subtitle: "Unfold the full instructions.", description: "Expand a routine’s Full prompt while keeping its title and schedule anchored.", before: "Native details expands and collapses immediately.", after: "A 200 ms height transition follows the same disclosure pattern as Activity.", source: "RoutineChatDetail · Full prompt", note: "Source-matched routine disclosure, with identical prompt text on both sides. The instructions below are a local example.", actions: ["Expand prompts", "Collapse prompts"] },
  { id: "routine", title: "Routine actions", number: "09", subtitle: "A request is not a result.", description: "Show Sending, then Request sent, and only show Paused after confirmation from the Ally.", before: "Button and request status change directly.", after: "Status changes crossfade without suggesting success early.", source: "RoutineChatDetail · actionPending / actionSent", note: "Simulated pause/resume lifecycle. Request sent remains distinct from confirmed Paused. Use Confirm pause to provide that separate confirmation.", actions: ["Pause both", "Sending…", "Confirm pause", "Resume both", "Retry pause", "Sending…", "Confirm resume"] },
  { id: "toast", title: "Notifications", number: "10", subtitle: "A small notice, lightly delivered.", description: "The Recipes notice rises a few pixels on arrival and fades away on dismissal.", before: "The existing notice appears and disappears immediately.", after: "A short upward fade. Repeated clicks do not replay the entrance.", source: "RecipesButton · notification markup", note: "Source-matched toast embedded in each preview for comparison. Both notices dismiss automatically after four seconds, as the current component does.", actions: ["Show notices", "Dismiss notices"] },
  { id: "deletion", title: "Confirmation", number: "11", subtitle: "Keep the context. Make the choice clear.", description: "Replace settings with the deletion confirmation within the same surface. The warning stays still once it is visible.", before: "Settings and confirmation content replace each other immediately.", after: "The surface stays steady while the contents crossfade. No scaling.", source: "AllySettingsDialog · deletionView", note: "Isolated confirmation fixture. Type DELETE Sally to enable the demonstration button. Its only action is to display a local preview notice; it cannot delete an Ally.", actions: ["Show confirmation", "Back to settings"] },
] as const;
export type ExtraId = typeof extraCases[number]["id"];

const prompt = "Every Friday at 9:00, find three relaxed weekend ideas nearby. Include one place to eat with vegetarian options, one outdoor activity, and a rainy-day alternative. Keep the total below €100 per person and include opening times. Prefer places we can reach on foot or by public transport.";
const pasted = Array.from({ length: 22 }, (_, i) => `${i + 1}. Keep the weekend relaxed, with good food and time outside.`).join("\n");

function Swap({ value, children, duration }: { value: string | number; children: ReactNode; duration: number }) {
  return <AnimatePresence initial={false} mode="wait"><motion.span key={value} className={styles.swap} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: duration / 2 }}>{children}</motion.span></AnimatePresence>;
}

function PasteExample({ step, setStep, duration }: { step: number; setStep: (step: number) => void; duration: number }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const [text, setText] = useState(pasted);
  return <div className={styles.extraBody}>
    <p className={styles.reply}>Add a longer brief without filling the conversation with a wall of text.</p>
    <div className={styles.pasteComposer}>
      <AnimatePresence initial={false}>{step > 0 ? <motion.div key="paste" initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration }} className={styles.clip}>
        <div className={styles.pasteCard}>
          <button ref={trigger} className={styles.pasteButton} aria-label="Edit pasted text" onClick={() => dialog.current?.showModal()}><span aria-hidden="true">≡</span><span><strong>Pasted text</strong><small>{text.length.toLocaleString()} characters · Click to edit</small></span></button>
          <button className={styles.pasteRemove} aria-label="Remove pasted text" onClick={() => setStep(0)}>×</button>
        </div>
      </motion.div> : null}</AnimatePresence>
      <div className={styles.pasteInputRow}><textarea aria-label="Message Sally" placeholder={step ? "Add a message…" : "Message Sally"} rows={1} /><button className={styles.demoSend} aria-label="Send disabled in preview" disabled>↑</button></div>
    </div>
    <dialog ref={dialog} className={`${frame.framePasteDialog} ${styles.pasteModal}`} aria-label="Edit pasted text" onClose={() => trigger.current?.focus()} onKeyDown={event => { if (event.key === "Escape") event.stopPropagation(); }}>
      <div className={frame.framePasteHeading}><h2>Pasted text</h2><button aria-label="Close pasted text" onClick={() => dialog.current?.close()}>×</button></div>
      <p>Edit your text before sending it to Sally.</p>
      <textarea aria-label="Pasted text content" value={text} maxLength={16000} onChange={event => setText(event.target.value)} />
      <footer><span>{text.length.toLocaleString()} / 16,000</span><button onClick={() => dialog.current?.close()}>Done</button></footer>
    </dialog>
  </div>;
}

export function MoreExperiment({ id, after, step, setStep, duration, failure, setFailure, confirmation, setConfirmation, editing, setEditing }: {
  id: ExtraId; after: boolean; step: number; setStep: (step: number) => void; duration: number;
  failure: boolean; setFailure: (value: boolean) => void; confirmation: string; setConfirmation: (value: string) => void;
  editing: boolean; setEditing: (value: boolean) => void;
}) {
  const fieldId = useId();
  const d = after ? duration : 0;
  const swap = (value: string | number, content: ReactNode) => after ? <Swap value={value} duration={d}>{content}</Swap> : content;
  const button = (label: string, action: () => void, disabled = false) => <button className={styles.openSheet} onClick={action} disabled={disabled}>{label}</button>;

  if (id === "save") return <div className={styles.extraBody}>
    <label className={styles.fieldLabel} htmlFor={fieldId}>Ally label</label><input id={fieldId} className={styles.demoInput} defaultValue="Weekend planner" disabled={step === 1} />
    <button className={styles.demoPrimary} disabled={step === 1} onClick={() => setStep(1)}>{swap(step, step === 1 ? "Saving…" : after && step === 2 ? "Saved ✓" : "Save label")}</button>
    <div className={styles.statusSlot} role="status">{step === 3 ? "We couldn’t save the label. Try again." : !after && step === 2 ? "Label saved" : ""}</div>
    <label className={styles.simulate}><input type="checkbox" checked={failure} onChange={e => setFailure(e.target.checked)} disabled={step === 1} />Simulate failed save</label>
  </div>;

  if (id === "paste") return <PasteExample step={step} setStep={setStep} duration={d} />;

  if (id === "upload") {
    const status = ["Weekend-notes.pdf · 1.2 MB", "Uploading 45%", "Checking file…", "Ready", "Needs attention"][step];
    return <div className={styles.extraBody}><p className={styles.reply}>Here’s the file you shared with Sally.</p><div className={styles.fileRow}><span className={styles.fileIcon} aria-hidden="true">PDF</span><div><strong>Weekend-notes.pdf</strong><div className={styles.statusSlot} role="status">{swap(step, `${after && step === 3 ? "✓ " : ""}${status}`)}</div></div></div>{step === 4 ? <p role="alert">The file couldn’t be checked. Please retry.</p> : null}{button(step === 4 ? "Retry upload" : "Simulate transfer error", () => setStep(step === 4 ? 1 : 4))}</div>;
  }

  if (id === "prompt") return <div className={styles.extraBody}><h3 className={styles.sheetTitle}>Weekend ideas</h3><p className={styles.sheetText}>Every Friday · 09:00 · Europe/Berlin</p>{after ? <div className={frame.frameRoutinePrompt}><button className={styles.activityTrigger} aria-expanded={step === 1} aria-controls={fieldId} onClick={() => setStep(step ? 0 : 1)}>Full prompt <span aria-hidden="true">{step ? "−" : "+"}</span></button><motion.div id={fieldId} initial={false} animate={{ height: step ? "auto" : 0, opacity: step ? 1 : 0 }} transition={{ duration: d }} className={styles.clip} aria-hidden={!step}><p>{prompt}</p></motion.div></div> : <details className={frame.frameRoutinePrompt} open={step === 1} onToggle={e => { if (e.currentTarget.open !== Boolean(step)) setStep(e.currentTarget.open ? 1 : 0); }}><summary>Full prompt</summary><p>{prompt}</p></details>}</div>;

  if (id === "routine") return <div className={styles.extraBody}><h3 className={styles.sheetTitle}>Weekend ideas</h3><p className={styles.sheetText}>Every Friday at 09:00</p><div className={styles.savedRow}><span>State</span><strong>{swap(step === 3 || step >= 5 ? "paused" : "active", step === 3 || step >= 5 ? "Paused" : "Active")}</strong></div><div className={styles.statusSlot} role="status">{swap(step, step === 2 || step === 6 ? "Request sent to Ally." : step === 4 ? "Request failed. Try again." : "")}</div><button className={styles.demoPrimary} disabled={[1, 2, 5, 6].includes(step)} onClick={() => setStep(step === 3 ? 5 : 1)}>{swap(step, step === 1 || step === 5 ? "Sending…" : step === 3 || step === 6 ? "Resume" : "Pause")}</button>{button("Simulate request failure", () => setStep(4), step === 3)}</div>;

  if (id === "toast") return <div className={styles.extraBody}><p className={styles.reply}>Recipes will help you discover new things your Ally can do.</p>{button("Recipes", () => setStep(1))}<div className={styles.inlineNotice} role="status"><AnimatePresence>{step ? <motion.div key="notice" className={toast.toast} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 4 }} transition={{ duration: d }}><span>Recipes are coming soon.</span><button aria-label="Dismiss notification" onClick={() => setStep(0)}>×</button></motion.div> : null}</AnimatePresence></div></div>;

  if (id === "preview") return <div className={styles.extraBody}>{button("Open Weekend-notes.svg", () => setStep(1))}<AnimatePresence>{step > 0 ? <motion.section role="region" aria-label="File preview" className={styles.previewSurface} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 4 }} transition={{ duration: d }}><header><strong>Weekend-notes.svg</strong><button aria-label="Close file" onClick={() => setStep(0)}>×</button></header><div className={styles.previewCanvas}>{step === 1 ? <p role="status">Loading file…</p> : step === 3 ? <p role="alert">Could not load this preview.</p> : <motion.svg initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: d }} viewBox="0 0 360 200" role="img" aria-label="Sample weekend illustration with hills and sun"><rect width="360" height="200" fill="#ecf1df" /><circle cx="275" cy="55" r="25" fill="#f3c870" /><path d="M0 145 90 55 190 155 275 90 360 155V200H0Z" fill="#82936c" /><path d="M0 185 110 130 225 180 360 120V200H0Z" fill="#425e42" /></motion.svg>}</div>{button(step === 3 ? "Retry preview" : "Simulate load error", () => setStep(step === 3 ? 1 : 3))}</motion.section> : null}</AnimatePresence></div>;

  const views = [
    <><h3 className={styles.sheetTitle}>Sally settings</h3><div className={styles.savedRow}><span>Label</span><strong>Weekend planner</strong></div>{button("Delete Ally", () => setStep(1))}</>,
    <><h3 className={styles.sheetTitle}>Delete Sally?</h3><p className={styles.sheetText}>This permanently removes Sally’s conversations, files, memory, and associated work.</p><label className={styles.fieldLabel} htmlFor={fieldId}>Type DELETE Sally to confirm</label><input id={fieldId} className={styles.demoInput} value={confirmation} onChange={e => setConfirmation(e.target.value)} autoComplete="off" /><div className={styles.confirmActions}><button onClick={() => { setStep(0); setConfirmation(""); }}>Cancel</button><button disabled={confirmation !== "DELETE Sally"} onClick={() => setEditing(true)}>Delete Ally</button></div>{editing ? <p role="status">Preview only — no Ally was deleted.</p> : null}</>,
  ];
  return <div className={styles.extraBody}><div className={`${styles.confirmSurface} ${after ? styles.steadyConfirmation : ""}`}>
    {after ? views.map((view, index) => <motion.div key={index} className={styles.confirmView} initial={false} animate={{ opacity: step === index ? 1 : 0 }} transition={{ duration: d, ease: "easeInOut" }} inert={step !== index} aria-hidden={step !== index} style={{ pointerEvents: step === index ? "auto" : "none" }}>{view}</motion.div>) : <div>{views[step === 0 ? 0 : 1]}</div>}
  </div></div>;
}