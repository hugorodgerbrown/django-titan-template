/*
 * static/js/pwa.js — wire each page to the service worker and the outbox.
 *
 * On every page load:
 *   1. Record who is signed in, and the CSRF token, in IndexedDB `meta`
 *      for the outbox and the worker. If the user changed (sign out, or a
 *      different account), drop the cached pages: they show the last
 *      user's data.
 *   2. Register the service worker, and ask it to cache this page so it
 *      opens offline next time.
 *   3. Send queued writes now, when the connection comes back, when the
 *      app returns to the foreground, and when the worker says to.
 *   4. Keep the offline banner and the header's outbox count current.
 */
(function () {
  'use strict';

  const db = self.AppDB;
  const outbox = self.Outbox;

  function metaContent(name) {
    const el = document.querySelector('meta[name="' + name + '"]');
    return el ? el.content : '';
  }

  async function recordPrincipal() {
    const principal = metaContent('app-principal');
    const previous = await db.getMeta('principal');
    await db.setMeta('principal', principal);
    await db.setMeta('csrf', metaContent('csrf-token'));
    if (previous !== undefined && previous !== principal && self.caches) {
      const names = await caches.keys();
      await Promise.all(names.filter((n) => n.includes('-pages-')).map((n) => caches.delete(n)));
    }
  }

  async function registerWorker() {
    if (!('serviceWorker' in navigator)) return;
    const registration = await navigator.serviceWorker.register('/sw.js', { scope: '/' });
    navigator.serviceWorker.addEventListener('message', (event) => {
      if (event.data && event.data.type === 'outbox:changed') {
        document.dispatchEvent(new CustomEvent('outbox:changed', { detail: event.data.detail }));
      }
    });
    const worker = registration.active || registration.waiting || registration.installing;
    if (worker) {
      worker.postMessage({ type: 'cache-page', url: location.pathname + location.search });
    }
  }

  function renderOnline() {
    const banner = document.querySelector('[data-offline-banner]');
    if (banner) banner.hidden = navigator.onLine;
  }

  function renderOutbox(detail) {
    const el = document.querySelector('[data-outbox-status]');
    if (!el) return;
    const parts = [];
    if (detail.pending) parts.push(detail.pending + ' waiting to send');
    if (detail.failed) parts.push(detail.failed + ' not sent');
    el.textContent = parts.join(' · ');
  }

  document.addEventListener('outbox:changed', (event) => {
    renderOutbox(event.detail);
    // htmx listens for this to refresh whatever the sent writes changed.
    if (event.detail.sent > 0) document.body.dispatchEvent(new CustomEvent('outbox:sent'));
  });

  window.addEventListener('online', () => {
    renderOnline();
    outbox.drain();
  });
  window.addEventListener('offline', renderOnline);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') outbox.drain();
  });

  renderOnline();
  recordPrincipal()
    .then(() => outbox.drain())
    .catch((error) => console.error('outbox: could not start', error));
  registerWorker().catch((error) => console.error('service worker: registration failed', error));
})();
