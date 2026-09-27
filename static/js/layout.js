// Personal page layouts (contacts/layouts.py). "Keisti išdėstymą" switches the
// page into edit mode: every block can be dragged with the mouse (on a touch
// screen by its ⠿ grip), moved with its arrows or switched off. Switched-off
// blocks are listed in the bar at the bottom, one click brings one back, and
// "Numatytasis vaizdas" forgets the user's choices for the page. Every change
// is saved at once.
(() => {
  const toggles = [...document.querySelectorAll('[data-layout-edit]')];
  const roots = [...document.querySelectorAll('[data-layout]')];
  if (!toggles.length || !roots.length) return;
  const url = toggles[0].dataset.layoutEdit;
  const RESUME = 'crm-layout-editing';

  const rootOf = el => el.closest('[data-layout]');
  const zonesOf = root => [root, ...root.querySelectorAll('[data-layout-zone]')]
    .filter(zone => zone.hasAttribute('data-layout-zone') && rootOf(zone) === root);
  const itemsOf = zone => [...zone.children].filter(el => el.hasAttribute('data-layout-item'));
  const markersOf = root => [...root.querySelectorAll('template[data-layout-hidden]')].filter(marker => rootOf(marker) === root);
  const isItem = el => el.hasAttribute('data-layout-item') && !!el.parentElement?.hasAttribute('data-layout-zone');
  const editing = () => document.body.classList.contains('layout-editing');

  let bar = null;
  const say = text => { const status = bar?.querySelector('[role=status]'); if (status) status.textContent = text; };

  const post = async body => {
    const response = await fetch(url, {
      method: 'POST', credentials: 'same-origin', body: JSON.stringify(body),
      headers: {'Content-Type': 'application/json', 'X-CSRFToken': document.body.dataset.csrf || ''},
    });
    if (!response.ok) throw new Error(String(response.status));
  };
  const save = async root => {
    const zones = {};
    zonesOf(root).forEach(zone => { zones[zone.dataset.layoutZone] = itemsOf(zone).map(item => item.dataset.layoutItem); });
    try {
      await post({key: root.dataset.layout, zones, hidden: markersOf(root).map(marker => marker.dataset.layoutHidden)});
      say(gettext('Išdėstymas išsaugotas.'));
    } catch (error) {
      say(gettext('Nepavyko išsaugoti. Bandykite dar kartą.'));
      throw error;
    }
  };
  const reloadEditing = () => {
    try { sessionStorage.setItem(RESUME, '1'); } catch (error) { /* private mode: reopen by hand */ }
    location.reload();
  };

  // --- per-block tools: grip, arrows, hide ---
  const button = (text, title, action) => {
    const control = document.createElement('button');
    control.type = 'button';
    control.textContent = text;
    control.title = title;
    control.addEventListener('click', event => { event.preventDefault(); event.stopPropagation(); action(control); });
    return control;
  };
  const move = (item, step, control) => {
    const root = rootOf(item);
    const zones = zonesOf(root);
    const siblings = itemsOf(item.parentElement);
    const next = siblings[siblings.indexOf(item) + step];
    if (next) {
      if (step < 0) next.before(item); else next.after(item);
    } else {
      const other = zones[zones.indexOf(item.parentElement) + step];
      if (!other) return;
      const items = itemsOf(other);
      if (step < 0) { if (items.length) items[items.length - 1].after(item); else other.append(item); }
      else if (items.length) items[0].before(item); else other.append(item);
    }
    control.focus();
    save(root).catch(() => {});
  };
  const hide = item => {
    const root = rootOf(item);
    const marker = document.createElement('template');
    marker.dataset.layoutHidden = item.dataset.layoutItem;
    marker.dataset.layoutLabel = item.dataset.layoutLabel || item.dataset.layoutItem;
    root.prepend(marker);
    item.remove();
    renderHidden();
    save(root).catch(() => {});
  };
  const addTools = item => {
    const label = item.dataset.layoutLabel || '';
    const across = item.getBoundingClientRect().width < item.parentElement.getBoundingClientRect().width * 0.75;
    const tools = document.createElement('div');
    tools.className = 'layout-tools';
    const grip = document.createElement('span');
    grip.className = 'layout-grip';
    grip.textContent = '⠿';
    grip.title = gettext('Tempkite');
    grip.setAttribute('aria-hidden', 'true');
    const back = button(across ? '←' : '↑', across ? gettext('Perkelti kairėn') : gettext('Perkelti aukštyn'), control => move(item, -1, control));
    const forward = button(across ? '→' : '↓', across ? gettext('Perkelti dešinėn') : gettext('Perkelti žemyn'), control => move(item, 1, control));
    const off = button('✕', gettext('Paslėpti'), () => hide(item));
    [back, forward, off].forEach(control => control.setAttribute('aria-label', `${control.title}: ${label}`));
    tools.append(grip, back, forward, off);
    const host = item.tagName === 'DETAILS' ? item.querySelector(':scope > summary') || item : item;
    host.append(tools);
  };

  // --- the bar: hidden blocks, default view, done ---
  const renderHidden = () => {
    if (!bar) return;
    const list = bar.querySelector('.layout-bar-hidden');
    list.replaceChildren();
    const entries = roots.filter(root => root.isConnected)
      .flatMap(root => markersOf(root).map(marker => ({root, marker})));
    if (!entries.length) {
      const none = document.createElement('span');
      none.className = 'muted';
      none.textContent = gettext('nėra');
      list.append(none);
    }
    entries.forEach(({root, marker}) => {
      const chip = button(`＋ ${marker.dataset.layoutLabel}`, gettext('Rodyti vėl'), () => {
        marker.remove();
        save(root).then(reloadEditing, () => {});
      });
      chip.className = 'btn sm';
      list.append(chip);
    });
  };
  const showBar = () => {
    bar = document.createElement('div');
    bar.className = 'layout-bar';
    bar.setAttribute('role', 'region');
    bar.setAttribute('aria-label', gettext('Išdėstymo keitimas'));
    const hint = document.createElement('p');
    hint.className = 'layout-bar-hint';
    hint.textContent = gettext('Tempkite blokus pele į norimą vietą arba naudokite rodykles; ✕ paslepia bloką. Viskas išsaugoma iškart jūsų profilyje.');
    const hidden = document.createElement('div');
    hidden.className = 'layout-bar-row';
    const title = document.createElement('strong');
    title.textContent = gettext('Paslėpti:');
    const list = document.createElement('div');
    list.className = 'layout-bar-hidden';
    hidden.append(title, list);
    const status = document.createElement('p');
    status.className = 'layout-bar-status';
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    const actions = document.createElement('div');
    actions.className = 'layout-bar-row';
    const reset = button(gettext('Numatytasis vaizdas'), gettext('Numatytasis vaizdas'), async () => {
      if (!window.confirm(gettext('Grąžinti numatytąjį šio puslapio vaizdą? Jūsų pakeitimai šiame puslapyje bus pamiršti.'))) return;
      try {
        await post({reset: [...new Set(roots.map(root => root.dataset.layout))]});
        reloadEditing();
      } catch (error) { say(gettext('Nepavyko išsaugoti. Bandykite dar kartą.')); }
    });
    reset.className = 'btn sm';
    const done = button(gettext('Baigti'), gettext('Baigti'), stop);
    done.className = 'btn sm primary';
    actions.append(reset, done);
    bar.append(hint, hidden, status, actions);
    document.body.append(bar);
    placeBar();
    renderHidden();
  };
  // Centred on the page content, not the window, so the side menu never covers it.
  const placeBar = () => {
    const main = document.querySelector('.crm-content');
    if (!bar || !main) return;
    const box = main.getBoundingClientRect();
    bar.style.left = `${box.left + box.width / 2}px`;
    bar.style.width = `${Math.min(720, box.width - 32)}px`;
  };
  window.addEventListener('resize', placeBar);

  const start = () => {
    if (editing()) return;
    document.body.classList.add('layout-editing');
    roots.forEach(root => zonesOf(root).forEach(zone => itemsOf(zone).forEach(addTools)));
    showBar();
    toggles.forEach(toggle => { toggle.setAttribute('aria-pressed', 'true'); toggle.closest('details')?.removeAttribute('open'); });
  };
  function stop() {
    document.body.classList.remove('layout-editing');
    document.querySelectorAll('.layout-tools').forEach(tools => tools.remove());
    bar?.remove();
    bar = null;
    toggles.forEach(toggle => toggle.setAttribute('aria-pressed', 'false'));
  }
  toggles.forEach(toggle => toggle.addEventListener('click', () => (editing() ? stop() : start())));

  // --- while editing, a block is something to move, not to use ---
  const inert = event => editing() && event.target.closest?.('[data-layout-item]') && !event.target.closest('.layout-tools');
  ['click', 'dblclick', 'dragstart'].forEach(type => document.addEventListener(type, event => {
    if (inert(event)) { event.preventDefault(); event.stopPropagation(); }
  }, true));
  document.addEventListener('keydown', event => {
    if (!editing()) return;
    if (event.key === 'Escape' && !drag) { stop(); return; }
    if ((event.key === 'Enter' || event.key === ' ') && inert(event)) { event.preventDefault(); event.stopPropagation(); }
  }, true);

  // --- dragging ---
  let drag = null;
  const place = (x, y) => {
    const {item, root} = drag;
    const zones = zonesOf(root);
    const el = document.elementFromPoint(x, y);
    let zone = el?.closest('[data-layout-zone]');
    while (zone && !zones.includes(zone)) zone = zone.parentElement?.closest('[data-layout-zone]');
    if (!zone) return;
    let target = el.closest('[data-layout-item]');
    while (target && target.parentElement !== zone) target = target.parentElement?.closest('[data-layout-item]');
    if (target === item) return;
    if (target) {
      const rect = target.getBoundingClientRect();
      const across = rect.width < zone.getBoundingClientRect().width * 0.75;
      const after = across ? x > rect.left + rect.width / 2 : y > rect.top + rect.height / 2;
      if (after && target.nextElementSibling !== item) target.after(item);
      else if (!after && target.previousElementSibling !== item) target.before(item);
      return;
    }
    const rest = itemsOf(zone).filter(other => other !== item);
    const last = rest[rest.length - 1];
    if (!last) { if (item.parentElement !== zone) zone.append(item); }
    else if (y > last.getBoundingClientRect().bottom && last.nextElementSibling !== item) last.after(item);
  };
  document.addEventListener('pointerdown', event => {
    if (!editing() || event.button !== 0 || event.target.closest('.layout-tools button')) return;
    const item = event.target.closest('[data-layout-item]');
    if (!item || !isItem(item)) return;
    // A finger drags by the grip only, so the page still scrolls under it.
    if (event.pointerType !== 'mouse' && !event.target.closest('.layout-grip')) return;
    event.preventDefault();
    drag = {item, root: rootOf(item), x: event.clientX, y: event.clientY, moved: false};
  });
  document.addEventListener('pointermove', event => {
    if (!drag) return;
    if (!drag.moved) {
      if (Math.hypot(event.clientX - drag.x, event.clientY - drag.y) < 5) return;
      drag.moved = true;
      drag.item.classList.add('layout-item-dragging');
      document.body.classList.add('layout-dragging');
    }
    event.preventDefault();
    place(event.clientX, event.clientY);
    if (event.clientY < 60) window.scrollBy(0, -16);
    else if (event.clientY > window.innerHeight - 60) window.scrollBy(0, 16);
  });
  const finish = () => {
    if (!drag) return;
    const {item, root, moved} = drag;
    drag = null;
    if (!moved) return;
    item.classList.remove('layout-item-dragging');
    document.body.classList.remove('layout-dragging');
    save(root).catch(() => {});
  };
  document.addEventListener('pointerup', finish);
  document.addEventListener('pointercancel', finish);

  try {
    if (sessionStorage.getItem(RESUME)) { sessionStorage.removeItem(RESUME); start(); }
  } catch (error) { /* storage unavailable: start in the normal view */ }
})();
