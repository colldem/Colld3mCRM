// Minimal service worker: enough to make the CRM installable as a PWA.
// No caching — the CRM is data-heavy and always needs a live server.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', () => {});
