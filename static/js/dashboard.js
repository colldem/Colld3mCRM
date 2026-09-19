// Dashboard: every block opens the list its number is made of, and the agenda
// card filters its rows by event type. Tab switching lives in tabs.js.
(() => {
  // --- the block popups ---
  document.querySelectorAll('[data-dash-open]').forEach(trigger => {
    trigger.addEventListener('click', () => {
      document.getElementById(trigger.dataset.dashOpen)?.showModal();
    });
  });
  document.querySelectorAll('.dash-dialog').forEach(dialog => {
    dialog.querySelector('[data-dash-close]')?.addEventListener('click', () => dialog.close());
    // Clicking the backdrop closes it; clicking a row must not.
    dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
  });

  // --- the agenda's type filter ---
  const card = document.querySelector('[data-dash-events]');
  if (!card) return;
  const hidden = new Set();
  const apply = () => {
    card.querySelectorAll('.event-list > li[data-kind]').forEach(row => {
      row.hidden = hidden.has(row.dataset.kind);
    });
  };
  card.querySelectorAll('[data-dash-kind]').forEach(chip => {
    chip.addEventListener('click', () => {
      const kind = chip.dataset.dashKind;
      const on = hidden.has(kind);
      if (on) hidden.delete(kind); else hidden.add(kind);
      chip.classList.toggle('is-on', on);
      chip.setAttribute('aria-pressed', on ? 'true' : 'false');
      apply();
    });
  });
})();
