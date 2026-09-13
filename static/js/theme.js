// A directory session past its re-check interval answers background GET requests
// with 403 and a "refresh_url" header (contacts/oidc.py DirectorySessionRefresh).
// Reloading lets the page itself go through the silent sign-in round trip.
(() => {
  const nativeFetch = window.fetch.bind(window);
  window.fetch = async (...args) => {
    const response = await nativeFetch(...args);
    if (response.status === 403 && response.headers.get('refresh_url')) window.location.reload();
    return response;
  };
})();

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
