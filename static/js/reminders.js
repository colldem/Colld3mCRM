document.querySelectorAll('.bell-tabs').forEach(tabs => {
  const buttons = [...tabs.querySelectorAll('[role=tab]')];
  function select(button) {
    buttons.forEach(item => {
      const selected = item === button;
      item.setAttribute('aria-selected', String(selected)); item.tabIndex = selected ? 0 : -1;
      document.getElementById(item.getAttribute('aria-controls')).hidden = !selected;
    });
  }
  buttons.forEach((button, index) => {
    button.addEventListener('click', () => select(button));
    button.addEventListener('keydown', event => {
      if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === 'Home' ? buttons[0] : event.key === 'End' ? buttons[buttons.length - 1] : buttons[(index + 1) % buttons.length];
      select(next); next.focus();
    });
  });
});

// Refresh only the bell. Unsaved forms and the user's selected tab stay untouched.
(() => {
  const menu = document.querySelector('[data-refresh-url]');
  if (!menu) return;
  let timer, busy = false, stopped = false;
  let delay = 30000;
  const status = menu.querySelector('[data-refresh-status]');
  async function refresh() {
    if (busy || stopped) return;
    clearTimeout(timer);
    if (document.hidden) return;
    busy = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch(menu.dataset.refreshUrl, {cache:'no-store', signal:controller.signal});
      if (response.status === 401) {
        stopped = true;
        status.textContent = gettext('Sesija baigėsi. Prisijunkite iš naujo, kad atsinaujintų priminimai.');
        return;
      }
      if (!response.ok) throw new Error('Refresh failed');
      const result = await response.json();
      const content = document.createElement('template'); content.innerHTML = result.html;
      for (const id of ['bell-active','bell-scheduled']) {
        const panel = menu.querySelector('#' + id);
        const fresh = content.content.querySelector('#' + id);
        // Do not remove a link while it is focused or being used.
        if (panel.innerHTML !== fresh.innerHTML && !panel.contains(document.activeElement) && !panel.matches(':hover')) {
          const scroll = panel.scrollTop;
          panel.innerHTML = fresh.innerHTML; panel.scrollTop = scroll;
        }
      }
      const bell = menu.querySelector('.bell');
      let badge = bell.querySelector('b');
      if (result.count > 0) {
        if (!badge) { badge = document.createElement('b'); bell.append(badge); }
        badge.textContent = result.count;
      } else badge?.remove();
      bell.setAttribute('aria-label', result.count > 0 ? interpolate(gettext('Atidaryti priminimus (%s neperskaityti)'), [result.count]) : gettext('Atidaryti priminimus'));
      status.textContent = ''; delay = 30000;
    } catch (_) {
      status.textContent = gettext('Nepavyko atnaujinti priminimų. Bandysime dar kartą.');
      delay = Math.min(delay * 2, 120000);
    } finally {
      clearTimeout(timeout); busy = false;
      if (!stopped && !document.hidden) timer = setTimeout(refresh, delay);
    }
  }
  document.addEventListener('visibilitychange', () => {
    clearTimeout(timer); if (!document.hidden) refresh();
  });
  window.addEventListener('online', refresh);
  menu.addEventListener('toggle', () => { if (menu.open) refresh(); });
  window.addEventListener('pagehide', () => clearTimeout(timer));
  window.addEventListener('pageshow', refresh);
  timer = setTimeout(refresh, delay);
})();
