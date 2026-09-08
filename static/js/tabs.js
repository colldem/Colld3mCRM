// Detail-card tabs + "new reminder" / #reminder-add deep links.
(() => {
  const box = document.querySelector('[data-tabs]');
  if (!box) return;
  const tabs = [...box.querySelectorAll('.tab')];
  const panels = [...box.querySelectorAll('.tab-panel')];
  const show = (name) => {
    if (!tabs.some(t => t.dataset.tab === name)) return;
    tabs.forEach(t => t.classList.toggle('is-active', t.dataset.tab === name));
    panels.forEach(p => {
      const on = p.dataset.panel === name;
      p.classList.toggle('is-active', on);
      p.hidden = !on;
    });
  };
  tabs.forEach(t => t.addEventListener('click', () => show(t.dataset.tab)));
  document.querySelectorAll('[data-open-tab]').forEach(el => el.addEventListener('click', event => {
    event.preventDefault();
    show(el.dataset.openTab);
    box.scrollIntoView({ behavior: 'smooth', block: 'start' });
    if (el.dataset.openTab === 'reminders') {
      const add = document.getElementById('reminder-add');
      if (add) { add.open = true; add.querySelector('input:not([type=hidden])')?.focus({ preventScroll: true }); }
    }
  }));
  document.querySelectorAll('.copy-link').forEach(btn => {
    const original = btn.textContent;
    btn.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(btn.dataset.link);
        btn.textContent = gettext('Nukopijuota');
        setTimeout(() => { btn.textContent = original; }, 1200);
      } catch (e) { /* clipboard unavailable */ }
    });
  });
  // Small copy buttons next to contact-info values — copy silently, brief flash only.
  document.querySelectorAll('.copy-value').forEach(btn => btn.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(btn.dataset.copy || '');
      btn.classList.add('copied');
      setTimeout(() => btn.classList.remove('copied'), 700);
    } catch (e) { /* clipboard unavailable */ }
  }));
})();
