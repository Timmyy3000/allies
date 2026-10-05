"use client";

import { createAllyDocument, type AllyMotionShape, type AllyPlayback } from '@allies/ally-motion';
import { useCallback, useEffect, useRef, useState } from 'react';

export function AllyArtwork({ shape, state, reduced, paused = false, skipWakeTransition = false, onStateChange }: { shape: AllyMotionShape; onStateChange?: (state: string) => void } & AllyPlayback) {
  const ref = useRef<HTMLIFrameElement>(null);
  const visible = useRef(true);
  const playback = useRef({ state, reduced, paused, skipWakeTransition });
  const [html] = useState(() => createAllyDocument(shape, { state, reduced }));
  const sync = useCallback(() => {
    ref.current?.contentWindow?.postMessage({ type: 'ally-playback', playback: { ...playback.current, paused: playback.current.paused || !visible.current } }, '*');
  }, []);

  useEffect(() => {
    const receive = (event: MessageEvent) => {
      if (event.source === ref.current?.contentWindow && event.data?.type === 'ally-state' && ['idle', 'thinking', 'sleeping', 'waking', 'falling-asleep'].includes(event.data.state)) onStateChange?.(event.data.state);
    };
    window.addEventListener('message', receive);
    return () => window.removeEventListener('message', receive);
  }, [onStateChange]);

  useEffect(() => {
    playback.current = { state, reduced, paused, skipWakeTransition };
    sync();
  }, [state, reduced, paused, skipWakeTransition, sync]);

  useEffect(() => {
    const element = ref.current;
    if (!element || typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver(([entry]) => {
      visible.current = entry.isIntersecting;
      sync();
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [sync]);

  return <iframe ref={ref} srcDoc={html} sandbox="allow-scripts" title="Ally animation" aria-hidden="true" tabIndex={-1} onLoad={sync} style={{ colorScheme: 'light', background: 'transparent', border: 0, width: '100%', height: '100%', display: 'block', pointerEvents: 'none' }} />;
}
