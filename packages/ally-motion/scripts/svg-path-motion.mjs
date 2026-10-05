// SVG-native path animation preserves the approved morph on WebKit as well as Chromium.
export function normalizePathMotion(svg, state) {
  const definitions = state === 'thinking'
    ? [['skeptical-left-eye', 'lid-l'], ['skeptical-right-eye', 'lid-r']]
    : state === 'waking' || state === 'falling-asleep' ? [['wake-open', 'eye-shape']] : [];
  for (const [name, className] of definitions) {
    const start = svg.indexOf(`@keyframes ${name}`);
    if (start < 0) throw Error(`Missing path animation ${name}`);
    let end = svg.indexOf('{', start) + 1;
    let depth = 1;
    for (; depth; end++) {
      if (svg[end] === '{') depth++;
      if (svg[end] === '}') depth--;
    }
    const block = svg.slice(start, end);
    let frames = [...block.matchAll(/([\d.% ,]+)\s*\{\s*d:path\(['"]([^'"]+)['"]\);?\s*\}/g)].flatMap(match =>
      match[1].split(',').map(offset => ({ offset: parseFloat(offset) / 100, path: match[2] })),
    ).sort((a, b) => a.offset - b.offset);
    if (frames.length < 2) throw Error(`Invalid path animation ${name}`);
    if (state === 'falling-asleep') frames = frames.reverse().map(frame => ({ ...frame, offset: 1 - frame.offset }));
    const duration = state === 'thinking' ? '4.502083s' : '1.4s';
    const animation = `<animate attributeName="d" dur="${duration}" values="${frames.map(frame => frame.path).join(';')}" keyTimes="${frames.map(frame => frame.offset).join(';')}" calcMode="spline" keySplines="${frames.slice(1).map(() => '.37 0 .63 1').join(';')}" fill="freeze" repeatCount="${state === 'thinking' ? 'indefinite' : '1'}" />`;
    svg = svg.slice(0, start) + svg.slice(end);
    svg = svg.replace(new RegExp(`<path([^>]*class="${className}"[^>]*)\\s*/>`, 'g'), `<path$1>${animation}</path>`);
  }
  return svg;
}
