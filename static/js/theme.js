// Localize the accessibility helpers created by AdminLTE at DOMContentLoaded.
document.addEventListener('DOMContentLoaded', () => {
  const mainLink = document.querySelector('.skip-link[href="#main"]');
  const navLink = document.querySelector('.skip-link[href="#navigation"]');
  if (mainLink) mainLink.textContent = gettext('Pereiti prie turinio');
  if (navLink) navLink.textContent = gettext('Pereiti prie meniu');
  document.querySelectorAll('.required-indicator').forEach(el => {
    el.textContent = ' (' + gettext('privaloma') + ')';
  });
  const toggle = document.querySelector('[data-lte-toggle="sidebar"]');
  const sync = () => toggle?.setAttribute('aria-expanded', String(document.body.classList.contains('sidebar-open')));
  new MutationObserver(sync).observe(document.body, {attributes:true, attributeFilter:['class']});
  sync();
});
