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
