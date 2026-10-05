import { ARTWORK, PLAYER_SCRIPT } from './generated';

export type AllyMotionState = 'idle' | 'thinking' | 'sleeping';
export type AllyMotionShape = 'boxy' | 'ghosty' | 'rocky' | 'rolly';
export type AllyPlayback = { state: AllyMotionState; reduced: boolean; paused?: boolean; skipWakeTransition?: boolean };

export function desaturateAllyColor(color: string): string {
  const hex = color.replace(/^#/, '');
  const expanded = hex.length === 3 ? [...hex].map(value => value + value).join('') : hex;
  if (!/^[\da-f]{6}$/i.test(expanded)) return color;
  const channels = [0, 2, 4].map(offset => parseInt(expanded.slice(offset, offset + 2), 16));
  const gray = channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
  return `#${channels.map(value => Math.round(value * 0.55 + gray * 0.45).toString(16).padStart(2, '0')).join('')}`;
}

export function createAllyDocument(shape: AllyMotionShape, playback: AllyPlayback): string {
  const config = JSON.stringify({ assets: ARTWORK[shape], ...playback }).replace(/</g, '\\u003c');
  return `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'"><style>html,body{margin:0;width:100%;height:100%;overflow:hidden;background:transparent}svg{display:block;width:100%;height:100%;shape-rendering:geometricPrecision}*{pointer-events:none}</style></head><body><script>${PLAYER_SCRIPT}\nstartAlly(${config});</script></body></html>`;
}

export function allyPlaybackScript(playback: AllyPlayback): string {
  return `window.setAllyPlayback && window.setAllyPlayback(${JSON.stringify(playback)});true;`;
}
