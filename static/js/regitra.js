// The card's Regitra section: a tab loads its first page the first time it is
// shown, and "Show more" is replaced by the next page. Regitra is read live, so
// the card never waits for it and a slow or absent service only affects this box.
(() => {
  const box = document.querySelector('[data-regitra]');
  if (!box) return;
  const fetchInto = async (target, url) => {
    try {
      const response = await fetch(url, {headers: {Accept: 'text/html'}, credentials: 'same-origin'});
      if (!response.ok) throw new Error(String(response.status));
      target.insertAdjacentHTML('beforeend', await response.text());
    } catch (error) {
      const note = document.createElement('p');
      note.className = 'regitra-error';
      note.setAttribute('role', 'alert');
      note.textContent = gettext('Nepavyko įkelti duomenų iš Regitros.');
      target.append(note);
    }
  };
  const load = (panel) => {
    if (panel.dataset.loaded) return;
    panel.dataset.loaded = '1';
    panel.textContent = '';
    fetchInto(panel, panel.dataset.src);
  };
  const tabs = [...box.querySelectorAll('[data-regitra-tab]')];
  const panels = [...box.querySelectorAll('[data-regitra-panel]')];
  const show = (name) => {
    tabs.forEach(tab => {
      const on = tab.dataset.regitraTab === name;
      tab.classList.toggle('is-active', on);
      tab.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    panels.forEach(panel => {
      const on = panel.dataset.regitraPanel === name;
      panel.classList.toggle('is-active', on);
      panel.hidden = !on;
      if (on) load(panel);
    });
  };
  tabs.forEach(tab => tab.addEventListener('click', () => show(tab.dataset.regitraTab)));
  box.addEventListener('click', event => {
    const more = event.target.closest('[data-regitra-more]');
    if (!more) return;
    more.disabled = true;
    const holder = document.createElement('div');
    more.replaceWith(holder);
    fetchInto(holder, more.dataset.regitraMore).then(() => holder.replaceWith(...holder.childNodes));
  });
  const first = panels.find(panel => !panel.hidden);
  if (first) load(first);
})();
