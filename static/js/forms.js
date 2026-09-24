// Warn before leaving a page with unsaved edits in a create/edit or settings form.
(() => {
  const forms = document.querySelectorAll('form.data-form, form.profile-form, form.duplicate-settings-form');
  if (!forms.length) return;

  const snapshot = form => new URLSearchParams(new FormData(form)).toString();
  let submitting = false;

  forms.forEach(form => {
    form.dataset.clean = snapshot(form);
    form.addEventListener('submit', () => { submitting = true; });
  });

  const dirty = () => [...forms].some(form => snapshot(form) !== form.dataset.clean);

  window.addEventListener('beforeunload', event => {
    if (submitting || !dirty()) return;
    event.preventDefault();
    event.returnValue = '';
  });
})();

// Native file inputs look nothing like the rest of the CRM, and their
// "no file chosen" text is the browser's, in the browser's language. Wrap each
// one so the visible control is ours; without JS the plain input still works.
(() => {
  document.querySelectorAll('input[type=file]').forEach(input => {
    if (input.closest('.file-field')) return;
    const field = document.createElement('span');
    field.className = 'file-field';
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'file-btn';
    button.textContent = input.multiple ? gettext('Pasirinkti failus') : gettext('Pasirinkti failą');
    const empty = input.multiple ? gettext('Failai nepasirinkti') : gettext('Failas nepasirinktas');
    const name = document.createElement('span');
    name.className = 'file-name';
    name.textContent = empty;
    input.parentNode.insertBefore(field, input);
    field.append(input, button, name);
    button.addEventListener('click', () => input.click());
    input.addEventListener('change', () => {
      const chosen = [...input.files].map(file => file.name);
      name.textContent = chosen.length ? chosen.join(', ') : empty;
      name.title = name.textContent;
      field.classList.toggle('has-file', chosen.length > 0);
    });
  });
})();

// Company picker (CompanyPicker widget, card "Įmonės" editor): only the chosen
// companies are on the page; typing asks the server for matches and adds them
// as unticked boxes. Delegated, because card editors are re-rendered after save.
(() => {
  const timers = new WeakMap();
  document.addEventListener('keydown', event => {
    if (event.key === 'Enter' && event.target.matches?.('.company-search')) event.preventDefault();
  });
  document.addEventListener('input', event => {
    const input = event.target;
    if (!input.matches?.('.company-search')) return;
    const picker = input.closest('.company-picker');
    const list = picker.querySelector('.company-options');
    clearTimeout(timers.get(picker));
    timers.set(picker, setTimeout(async () => {
      const term = input.value.trim();
      const request = String(Date.now());
      picker.dataset.request = request;
      list.querySelectorAll('label.company-found').forEach(label => {
        if (!label.querySelector('input').checked) label.remove();
      });
      if (term.length < 2) return;
      const response = await fetch(`${picker.dataset.companyLookup}?q=${encodeURIComponent(term)}`,
                                   {headers: {Accept: 'application/json'}});
      if (!response.ok || picker.dataset.request !== request) return;
      const present = new Set([...list.querySelectorAll('input[type=checkbox]')].map(box => box.value));
      (await response.json()).results.forEach(company => {
        if (present.has(String(company.id))) return;
        const label = document.createElement('label');
        label.className = 'company-found';
        const box = document.createElement('input');
        box.type = 'checkbox'; box.name = picker.dataset.name; box.value = company.id;
        label.append(box, company.name);
        list.append(label);
      });
    }, 250));
  });
})();
