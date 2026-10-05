"use client";

import { useEffect, useId, useState, useSyncExternalStore } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ActivityDisclosure, BottomSheet, QueueStack, type ActivityDisclosureEntry } from "../../home/conversation-frame-primitives";
import { ActivityIcon } from "../../home/activity-icon";
import frame from "../../home/conversation-frame.module.css";
import styles from "./transitions.module.css";
import { extraCases, MoreExperiment, type ExtraId } from "./more-experiments";

const cases = [
  { id: "sheet", title: "Sheets", number: "01", subtitle: "A softer arrival.", description: "Approval, Ally settings and routine details all share the same sheet. Keep its shape; give opening and closing a little continuity.", before: "Appears and disappears immediately.", after: "A 220 ms fade and 16 px rise. No bounce.", source: "BottomSheet", note: "The actual shared sheet is embedded here using its existing debug presentation. These previews do not submit approvals or change settings." },
  { id: "activity", title: "Activity", number: "02", subtitle: "Make room for the details.", description: "The label and chevron already animate. Smooth the expanding space so the answer below follows the activity instead of jumping.", before: "Native disclosure; entries fade, height changes instantly.", after: "Height opens and closes over 200 ms. Existing visual style.", source: "ActivityDisclosure", note: "The Before column imports the current disclosure, including its scroll-into-view behavior. The proposal keeps the content anchored and animates the space beneath it." },
  { id: "queue", title: "Queued messages", number: "03", subtitle: "Let the next message settle in.", description: "When another thought joins the queue, make its arrival clear. When one leaves, close the gap gently.", before: "Items and the space around them change immediately.", after: "A short entrance, quiet exit and smooth layout changes.", source: "QueueStack", note: "Both columns share the same sample queue. Remove a message from either side to compare the same change. Nothing is sent to an Ally." },
  ...extraCases,
] as const;
type CaseId = typeof cases[number]["id"];
type Item = { id: string; content: string };
const entries: ActivityDisclosureEntry[] = [
  { id: "1", text: "Looked through the relevant files", activityKind: "file_read", durationMs: 2400, tone: "muted" },
  { id: "2", text: "Researched weekend options", activityKind: "web_search", durationMs: 6100, tone: "muted" },
  { id: "3", text: "Prepared your shortlist", activityKind: "file_write", durationMs: 3100, tone: "muted" },
];
const messages = ["Keep it under €100 per person.", "Include somewhere we can walk to.", "A vegetarian option would be great.", "Send me the shortlist when it’s ready."];

function subscribeReducedMotion(update: () => void) {
  const media = window.matchMedia("(prefers-reduced-motion: reduce)");
  media.addEventListener("change", update);
  return () => media.removeEventListener("change", update);
}
const getReducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function SheetContent() {
  return <><p className={styles.sheetLabel}>SALLY · TRAVEL ALLY</p><h3 className={styles.sheetTitle}>A little help with your weekend.</h3><p className={styles.sheetText}>Find thoughtful places to eat, stay and explore. Keep the plans easy to follow.</p><div className={styles.savedRow}><span>Label</span><strong>Weekend planner</strong></div></>;
}

function ProposedActivity({ open, onToggle, duration }: { open: boolean; onToggle: () => void; duration: number }) {
  const id = useId();
  return <div className={frame.frameActivity} data-ongoing="false">
    <button className={styles.activityTrigger} aria-expanded={open} aria-controls={id} onClick={onToggle}>
      <span className={frame.frameActivityLabel}>3 activities</span>
      <motion.span className={frame.frameActivityChevron} animate={{ rotate: open ? 180 : 0 }} transition={{ duration }}><svg viewBox="0 0 12 12" aria-hidden="true"><path d="m3 4.5 3 3 3-3" fill="none" stroke="currentColor" strokeWidth="1.5" /></svg></motion.span>
    </button>
    <motion.div id={id} initial={false} animate={{ height: open ? "auto" : 0, opacity: open ? 1 : 0 }} transition={{ duration, ease: [0.22, 1, 0.36, 1] }} className={styles.clip} aria-hidden={!open}>
      <div className={frame.frameActivityEntries}>{entries.map(entry => <div className={`${frame.frameActivityEntry} ${frame.frameActivityMuted}`} key={entry.id}><ActivityIcon kind={entry.activityKind} tone="muted" /><span>{entry.text}</span><small>{Math.round((entry.durationMs ?? 0) / 1000)}s</small></div>)}</div>
    </motion.div>
  </div>;
}

function ProposedQueue({ items, remove, duration }: { items: Item[]; remove: (id: string) => void; duration: number }) {
  return <ol className={`${frame.frameQueue} ${styles.smoothQueue}`} aria-label="Queued messages">
    <AnimatePresence initial={false}>
      {items.map((item, index) => <motion.li key={item.id} initial={{ height: 0, marginTop: 0 }} animate={{ height: 48, marginTop: index === 0 ? 0 : 8 }} exit={{ height: 0, marginTop: 0 }} transition={{ duration, ease: [0.25, 1, 0.5, 1] }} className={styles.queueItem}>
        <motion.div initial={{ opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -3 }} transition={{ duration: duration * 0.65, ease: [0.25, 1, 0.5, 1] }} className={frame.frameQueuePill}><span title={item.content}>{item.content}</span><button type="button" aria-label={`Remove queued message: ${item.content}`} onClick={() => remove(item.id)}><svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true"><use href="/ally/icons/chat-queue-trash.svg#icon" /></svg></button></motion.div>
      </motion.li>)}
    </AnimatePresence>
  </ol>;
}

export function TransitionsLab() {
  const [selected, setSelected] = useState<CaseId>("sheet");
  const [slow, setSlow] = useState(false);
  const [motionOff, setMotionOff] = useState(false);
  const systemReduced = useSyncExternalStore(subscribeReducedMotion, getReducedMotion, () => false);
  const reduced = motionOff || Boolean(systemReduced);
  const [sheet, setSheet] = useState({ before: false, after: false });
  const [activity, setActivity] = useState({ before: false, after: false });
  const [items, setItems] = useState<Item[]>([{ id: "0", content: messages[0] }]);
  const [nextId, setNextId] = useState(1);
  const [step, setStep] = useState(0);
  const [failure, setFailure] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const [editing, setEditing] = useState(false);
  const current = cases.find(item => item.id === selected)!;
  const duration = reduced ? 0 : slow ? 0.8 : selected === "queue" ? 0.32 : selected === "sheet" ? 0.22 : 0.2;
  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") { setSheet({ before: false, after: false }); setStep(0); setEditing(false); } };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, []);
  useEffect(() => {
    if ((step !== 1 && !(selected === "routine" && step === 5)) || !["save", "routine", "toast"].includes(selected)) return;
    const timer = setTimeout(() => setStep(selected === "toast" ? 0 : step === 5 ? 6 : selected === "save" && failure ? 3 : 2), selected === "toast" ? 4000 : 900);
    return () => clearTimeout(timer);
  }, [selected, step, failure]);
  const reset = () => { setSheet({ before: false, after: false }); setActivity({ before: false, after: false }); setItems([{ id: "0", content: messages[0] }]); setNextId(1); setStep(0); setFailure(false); setConfirmation(""); setEditing(false); };
  const remove = (id: string) => setItems(value => value.filter(item => item.id !== id));
  const add = () => { if (items.length >= 4) return; setItems(value => [...value, { id: String(nextId), content: messages[nextId % messages.length] }]); setNextId(value => value + 1); };
  const toggleBoth = () => {
    if (selected === "sheet") { const open = !(sheet.before || sheet.after); setSheet({ before: open, after: open }); }
    else if (selected === "activity") { const open = !(activity.before || activity.after); setActivity({ before: open, after: open }); }
    else if (selected === "queue") add();
    else if (selected === "save") setStep(1);
    else if (selected === "routine") setStep(step === 2 ? 3 : step === 3 ? 5 : step === 6 ? 0 : 1);
    else if (selected === "upload") setStep(step >= 3 ? 1 : step + 1);
    else if (selected === "preview") setStep(step === 2 ? 0 : step === 3 ? 1 : step + 1);
    else { setStep(step ? 0 : 1); setEditing(false); setConfirmation(""); }
  };
  const action = "actions" in current ? current.actions[step] : selected === "sheet" ? (sheet.before || sheet.after ? "Close both" : "Open both") : selected === "activity" ? (activity.before || activity.after ? "Collapse both" : "Expand both") : "Add a message";

  return <main className={styles.lab} data-motion-off={reduced}>
    <header className={styles.masthead}><a href="/transitions" className={styles.brand}>allies<span> / motion lab</span></a><span className={styles.devTag}>LOCAL EXPERIMENT</span></header>
    <section className={styles.intro}><div><p className={styles.eyebrow}>SMALL CHANGES, BETTER FEEL</p><h1>A little motion.<br /><span>A clearer interaction.</span></h1></div><p>Current components on the left. <br />A restrained next step on the right.<br /><span>Same content. Feel the difference.</span></p></section>
    <div className={styles.toolbar}>
      <nav aria-label="Transition examples" className={styles.tabs}>{cases.map(item => <button key={item.id} type="button" aria-pressed={selected === item.id} onClick={() => { reset(); setSelected(item.id); }}><span>{item.number}</span>{item.title}</button>)}</nav>
      <div className={styles.options}><label><input type="checkbox" checked={slow} disabled={reduced} onChange={event => setSlow(event.target.checked)} />Slow motion</label><label><input type="checkbox" checked={motionOff} onChange={event => setMotionOff(event.target.checked)} />Motion off</label></div>
    </div>
    <section className={styles.experiment} aria-labelledby="experiment-title">
      <div className={styles.experimentHeader}><div><p className={styles.eyebrow}>EXPERIMENT {current.number}</p><h2 id="experiment-title">{current.subtitle}</h2><p>{current.description}</p></div><div className={styles.actions}><button className={styles.reset} onClick={reset}>Reset</button><button className={styles.play} onClick={toggleBoth} disabled={(selected === "queue" && items.length >= 4) || (["save", "routine"].includes(selected) && (step === 1 || step === 5))}>{action}<span aria-hidden="true">↗</span></button></div></div>
      <div className={styles.comparison}>
        {(["before", "after"] as const).map(side => <section key={`${selected}-${side}`} className={styles.column} aria-label={side === "before" ? "Before comparison" : "After comparison"}>
          <div className={styles.columnHeading}><h3>{side === "before" ? "Before" : "After"}</h3><span>{side === "before" ? ("actions" in current ? "CURRENT BEHAVIOR FIXTURE" : "CURRENT COMPONENT") : "PROPOSED MOTION"}</span></div>
          <div className={styles.stage} data-case={selected} data-testid={`${side}-stage`}>
            <div className={styles.chatHeader}><div className={styles.avatar} aria-hidden="true">s.</div><div><strong>Sally</strong><small>Weekend planner</small></div><span className={styles.online}>Your Ally</span></div>
            <div className={styles.scene}>
              {"actions" in current ? <MoreExperiment id={selected as ExtraId} after={side === "after"} step={step} setStep={setStep} duration={duration} failure={failure} setFailure={setFailure} confirmation={confirmation} setConfirmation={setConfirmation} editing={editing} setEditing={setEditing} /> : <div className={styles.userBubble}>Help me plan a relaxed weekend.</div>}
              {selected === "sheet" ? <><p className={styles.reply}>A slower start, a good lunch, and somewhere new to explore. That sounds like a plan.</p><button className={styles.openSheet} onClick={() => setSheet(value => ({ ...value, [side]: true }))}>Open Ally settings <span aria-hidden="true">↗</span></button></> : null}
              {selected === "activity" ? <><div className={styles.activityWrap}>{side === "before" ? <ActivityDisclosure label="3 activities" entries={entries} open={activity.before} onToggle={open => setActivity(value => value.before === open ? value : { ...value, before: open })} /> : <ProposedActivity open={activity.after} onToggle={() => setActivity(value => ({ ...value, after: !value.after }))} duration={duration} />}</div><p className={styles.reply}>I found three places that fit. Here’s a relaxed plan for Saturday, with plenty of room to wander.</p></> : null}
              {selected === "queue" ? <><p className={styles.reply}>I’m putting together a few ideas. Add anything else you’d like me to keep in mind.</p><div className={styles.queueWrap}>{side === "before" ? <QueueStack items={items} onRemove={remove} /> : <ProposedQueue items={items} remove={remove} duration={duration} />}</div></> : null}
              {"actions" in current ? null : <div className={styles.composer}><span>Message Sally</span><span aria-hidden="true">↑</span></div>}
            </div>
            {selected === "sheet" && side === "before" && sheet.before ? <BottomSheet title="Sally settings" onClose={() => setSheet(value => ({ ...value, before: false }))} labelledBy="before-sheet-title"><SheetContent /></BottomSheet> : null}
            {selected === "sheet" && side === "after" ? <AnimatePresence>{sheet.after ? <motion.div className={`${frame.frameOverlay} ${styles.proposedOverlay}`} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration }}>
              <motion.section role="dialog" aria-labelledby="after-sheet-title" className={frame.frameSheet} initial={{ y: 16 }} animate={{ y: 0 }} exit={{ y: 12 }} transition={{ duration, ease: [0.22, 1, 0.36, 1] }}><div className={frame.frameSheetTop}><h2 id="after-sheet-title">Sally settings</h2><button className={frame.frameSheetClose} aria-label="Close" onClick={() => setSheet(value => ({ ...value, after: false }))}><svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true"><use href="/ally/icons/chat-close.svg#icon" /></svg></button></div><SheetContent /></motion.section>
            </motion.div> : null}</AnimatePresence> : null}
          </div>
          <p className={styles.caption}><span className={side === "after" ? styles.greenDot : styles.grayDot} />{current[side]}</p>
        </section>)}
      </div>
      <div className={styles.note}><span>THE DETAIL</span><p>{current.note}</p></div>
    </section>
    <footer className={styles.footer}><span>Based on <code>origin/dev · 733a137</code> · {current.source}</span><span>{systemReduced ? "System reduced motion is active" : reduced ? "Motion disabled for comparison" : slow ? "Proposed motion slowed to 800 ms" : "Production styling. Local prototypes."}</span><a href="https://transitions.dev/" target="_blank" rel="noreferrer">Inspired by transitions.dev ↗</a></footer>
  </main>;
}
