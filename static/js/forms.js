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
