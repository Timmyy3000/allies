function startAlly(config) {
  const durations = { idle: 4000, thinking: 4502.083, sleeping: 9600, waking: 1400, 'falling-asleep': 1400 };
  const stable = ['idle', 'thinking', 'sleeping'];
  let requested = stable.includes(config.state) ? config.state : 'idle';
  let state = requested;
  let reduced = Boolean(config.reduced);
  let paused = Boolean(config.paused);
  let elapsed = 0;
  let last = 0;
  let frame = 0;
  let animations = [];
  let bridges = [];
  let bridgeTime = 0;
  let svg;
  const matrix = m => `matrix(${m.a},${m.b},${m.c},${m.d},${m.e},${m.f})`;

  function snapshot() {
    const head = svg.querySelector('#head');
    const eyes = svg.querySelector('#eyes');
    const result = { head: head?.getCTM(), eyes: eyes ? getComputedStyle(eyes).transform : null, zs: [] };
    for (const path of svg.querySelectorAll('.sleep-z path,.z-one path,.z-two path')) {
      let opacity = 1;
      for (let node = path; node && node !== svg; node = node.parentElement) opacity *= Number(getComputedStyle(node).opacity);
      if (opacity < 0.01) continue;
      const copy = path.cloneNode(true);
      const css = getComputedStyle(path);
      copy.removeAttribute('class');
      copy.style.cssText = `animation:none;transform:${matrix(svg.getCTM().inverse().multiply(path.getCTM()))};transform-origin:0 0;fill:${css.fill};stroke:${css.stroke};stroke-width:${css.strokeWidth};stroke-linecap:round;stroke-linejoin:round;opacity:${opacity}`;
      result.zs.push(copy);
    }
    return result;
  }

  function bridge(element, from, to) {
    if (!element) return;
    const animation = element.animate([from, to], { duration: 420, easing: 'cubic-bezier(.22,0,.36,1)', fill: 'both' });
    animation.pause();
    animation.currentTime = 0;
    bridges.push(animation);
  }

  function load(next, blend = false, initial = false) {
    const old = blend && svg ? snapshot() : null;
    bridges.forEach(animation => animation.cancel());
    bridges = [];
    bridgeTime = 0;
    svg?.remove();
    const parsed = new DOMParser().parseFromString(config.assets[next] || config.assets.idle, 'image/svg+xml');
    svg = document.importNode(parsed.documentElement, true);
    document.body.append(svg);
    // The host owns motion preference, including an explicit full-motion override.
    for (const sheet of document.styleSheets) {
      for (let i = sheet.cssRules.length - 1; i >= 0; i--) {
        if (sheet.cssRules[i].type === CSSRule.MEDIA_RULE) sheet.deleteRule(i);
      }
    }
    animations = document.getAnimations();
    state = next;
    elapsed = reduced && next === 'thinking' ? durations.thinking * 0.5
      : initial && !reduced && (next === 'idle' || next === 'sleeping') ? Math.random() * durations[next] : 0;
    svg.pauseAnimations?.();
    svg.setCurrentTime?.(elapsed / 1000);
    animations.forEach(animation => { animation.pause(); animation.currentTime = elapsed; });
    document.body.dataset.state = state;
    if (window.parent !== window) window.parent.postMessage({ type: 'ally-state', state }, '*');
    if (old) {
      const head = svg.querySelector('#head');
      if (head && old.head) {
        const inverse = head.parentElement.getCTM().inverse();
        bridge(head, { transformOrigin: '0px 0px', transform: matrix(inverse.multiply(old.head)) }, { transformOrigin: '0px 0px', transform: matrix(inverse.multiply(head.getCTM())) });
      }
      const eyes = svg.querySelector('#eyes');
      if (eyes && old.eyes) bridge(eyes, { transform: old.eyes }, { transform: getComputedStyle(eyes).transform });
      // Keep the outgoing Zs moving while they disappear from the waking face.
      for (const z of svg.querySelectorAll('.z-one,.z-two')) z.style.display = 'none';
      const departing = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      departing.setAttribute('data-departing', '');
      old.zs.forEach(z => departing.append(z));
      svg.append(departing);
      bridge(departing, { opacity: 1, transform: 'translate(0px,0px)' }, { opacity: 0, transform: 'translate(12px,-14px)' });
    }
    if (next === 'waking') {
      for (const z of svg.querySelectorAll('.z-one,.z-two')) z.style.display = 'none';
    }
    if (next === 'sleeping' && !reduced && !initial) {
      const zs = svg.querySelector('.sleep-z')?.parentElement;
      if (zs) {
        const intro = zs.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 300, fill: 'both' });
        intro.pause(); intro.currentTime = 0; animations.push(intro);
      }
    }
  }

  function advance() {
    if (state === 'waking') load(requested === 'sleeping' ? 'falling-asleep' : requested);
    else if (state === 'falling-asleep') load(requested === 'sleeping' ? 'sleeping' : 'waking');
    else if (requested !== state) load(requested === 'sleeping' ? 'falling-asleep' : requested);
  }

  function tick(now) {
    frame = 0;
    const dt = last ? Math.min(now - last, 64) : 0;
    last = now;
    if (bridges.length) {
      bridgeTime = Math.min(420, bridgeTime + dt);
      bridges.forEach(animation => { animation.currentTime = bridgeTime; });
      if (bridgeTime === 420) {
        bridges.forEach(animation => animation.cancel());
        bridges = [];
        svg.querySelector('[data-departing]')?.remove();
      }
    } else {
      const boundary = (Math.floor(elapsed / durations[state]) + 1) * durations[state];
      const switching = elapsed + dt >= boundary && (!stable.includes(state) || requested !== state);
      elapsed = switching ? boundary : elapsed + dt;
      animations.forEach(animation => { animation.currentTime = elapsed; });
      svg.setCurrentTime?.(elapsed / 1000);
      if (switching) advance();
    }
    schedule();
  }

  function schedule() {
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
    if (!paused && !reduced && !document.hidden) frame = requestAnimationFrame(tick);
    else last = 0;
  }

  window.setAllyPlayback = value => {
    if (!value || !stable.includes(value.state)) return;
    requested = value.state;
    const changedMotion = reduced !== Boolean(value.reduced);
    reduced = Boolean(value.reduced);
    paused = Boolean(value.paused);
    if (changedMotion || (reduced && state !== requested)) load(requested);
    else if (!reduced && state === 'sleeping' && requested !== 'sleeping') load('waking', true);
    schedule();
  };
  window.addEventListener('message', event => {
    if (event.source === window.parent && event.data?.type === 'ally-playback') window.setAllyPlayback(event.data.playback);
  });
  document.addEventListener('visibilitychange', schedule);
  load(state, false, true);
  schedule();
  window.ReactNativeWebView?.postMessage('ally-ready');
}
