import type { ComponentProps, ReactNode } from "react";
import styles from "./conversation-frame.module.css";

const uuid = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const routineLink = new RegExp(`^#routine/(${uuid})$`, "i");
const sharedFileLink = new RegExp(`^/files/(${uuid})$`, "i");

function sharedFileId(href?: string) {
  if (!href || typeof window === "undefined") return undefined;
  try {
    const url = new URL(href, window.location.href);
    if (url.origin !== window.location.origin) return undefined;
    return url.pathname.match(sharedFileLink)?.[1];
  } catch {
    return undefined;
  }
}

export function RoutineMention({ id, children, onOpen }: { id: string; children: ReactNode; onOpen?: (id: string) => void }) {
  return <button type="button" className={styles.frameRoutineMention} onClick={() => onOpen?.(id)} disabled={!onOpen}>
    <svg aria-hidden="true" viewBox="0 0 24 24"><use href="/ally/icons/chat-routine.svg#icon" /></svg>
    <span>{children}</span>
  </button>;
}

export function FileMention({ id, href, children, onOpen, ...props }: ComponentProps<"a"> & { id: string; onOpen?: (id: string) => void }) {
  const label = children === "shared-file" ? "Open file" : children;
  return <a
    {...props}
    href={href}
    className={`${styles.frameFileMention}${props.className ? ` ${props.className}` : ""}`}
    data-file-reference=""
    onClick={(event) => {
      props.onClick?.(event);
      if (!event.defaultPrevented && onOpen) {
        event.preventDefault();
        onOpen(id);
      }
    }}
  >
    <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M6 3h8l4 4v14H6zM14 3v5h4M9 13h6M9 16h4" /></svg>
    <span>{label}</span>
  </a>;
}

export function routineLinkComponents(onOpen?: (id: string) => void, onOpenFile?: (id: string) => void) {
  return { a: ({ href, children, ...props }: ComponentProps<"a">) => {
    const fileId = sharedFileId(href);
    if (fileId) return <FileMention {...props} id={fileId} href={href} onOpen={onOpenFile}>{children}</FileMention>;
    const match = href?.match(routineLink);
    return match ? <RoutineMention id={match[1]} onOpen={onOpen}>{children}</RoutineMention>
      : <a {...props} href={href}>{children}</a>;
  } };
}

export function RoutineUserText({ text, onOpen }: { text: string; onOpen?: (id: string) => void }) {
  const legacy = text.match(new RegExp(`^Please start the confirmation flow to delete the routine "([^"\\n]+)"\\.\\s+routine_id=(${uuid}); expected_revision=\\d+;\\s+title_snapshot="([^"\\n]+)"$`, "i"));
  if (legacy && legacy[1] === legacy[3]) return <>Please delete the routine <RoutineMention id={legacy[2]} onOpen={onOpen}>{legacy[1]}</RoutineMention>.</>;
  const pattern = /\[((?:\\.|[^\]\\\n])+)\]\(#routine\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\)/gi;
  const parts: ReactNode[] = [];
  let offset = 0;
  for (const match of text.matchAll(pattern)) {
    parts.push(text.slice(offset, match.index));
    parts.push(<RoutineMention key={match.index} id={match[2]} onOpen={onOpen}>{match[1].replace(/\\(.)/g, "$1")}</RoutineMention>);
    offset = match.index + match[0].length;
  }
  parts.push(text.slice(offset));
  return <>{parts}</>;
}
