// Localize the accessibility helpers created by AdminLTE at DOMContentLoaded.
document.addEventListener('DOMContentLoaded', () => {
  // CRM is a private single-user tool; AdminLTE's skip links are not needed and
  // surface as stray text when focused. Remove the block it injects into <body>.
  document.querySelector('.skip-links')?.remove();
  document.querySelectorAll('.required-indicator').forEach(el => {
    el.textContent = ' (' + gettext('privaloma') + ')';
  });
  const toggle = document.querySelector('[data-lte-toggle="sidebar"]');
  const sync = () => toggle?.setAttribute('aria-expanded', String(document.body.classList.contains('sidebar-open')));
  new MutationObserver(sync).observe(document.body, {attributes:true, attributeFilter:['class']});
  sync();
});
