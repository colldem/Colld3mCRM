// Declarative behaviours that used to be inline on* attributes. The Content
// Security Policy allows no inline event handlers, so templates mark elements:
//   data-autosubmit        submit the owning form when the control changes
//   data-confirm="text"    ask before submitting a form or activating a button
//   data-row-href="url"    open the URL when a table row is clicked
//   data-no-row-link       a cell or control inside such a row that is not a link
//   data-select-on-focus   select a read-only field's text for copying
(() => {
  document.addEventListener('change', event => {
    const control = event.target.closest('[data-autosubmit]');
    if (control && control.form) control.form.submit();
  });
  document.addEventListener('submit', event => {
    const form = event.target;
    if (form.matches('[data-confirm]') && !window.confirm(form.dataset.confirm)) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }, true);
  document.addEventListener('click', event => {
    const trigger = event.target.closest('button[data-confirm],a[data-confirm],input[data-confirm]');
    if (trigger && !window.confirm(trigger.dataset.confirm)) {
      event.preventDefault();
      event.stopImmediatePropagation();
      return;
    }
    const row = event.target.closest('[data-row-href]');
    if (!row || event.target.closest('a,button,input,select,textarea,label,summary,[popover],[data-no-row-link]')) return;
    if (String(window.getSelection && window.getSelection())) return;
    window.location.href = row.dataset.rowHref;
  }, true);
  document.addEventListener('focusin', event => {
    if (event.target.matches('[data-select-on-focus]')) event.target.select();
  });
  document.addEventListener('click', event => {
    if (event.target.matches('[data-select-on-focus]')) event.target.select();
  });
})();
