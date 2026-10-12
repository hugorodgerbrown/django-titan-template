# Visitors are counted by fivebar, and only once the app is live

Status: accepted (2026-10-12)

## Context

Every Titan app needs to know how many people use it and which pages they
open, without a cookie banner and without weakening a CSP that allows
nothing but this origin. fivebar (https://fiveb.ar) counts visits with one
async script tag and no cookies; Traintrackr already uses it. It has no
package and no server code, and no API for adding a site: a site is added
by hand at https://fiveb.ar/sites.

## Decision

- The tag goes in `templates/includes/_head.html`, so every page, public or
  in the app, carries it once. It loads from fiveb.ar as written, never
  bundled or precached: the script sends its counts to the host it came
  from.
- It is off unless `FIVEBAR_DOMAIN` is set. Locally, in CI and in tests
  nothing is drawn and the CSP gains nothing. titan sets it at go-live to
  the app's domain, next to `SITE_URL`, and lists adding the site in
  fivebar as a by-hand step.
- While it is on, `https://fiveb.ar` is added to `script-src` and
  `connect-src` only.
- A page whose route takes values (an emailed sign-in link's token, a
  note's uuid) is counted under its route, `data-path="/signin/link/:token/"`,
  worked out from the URL resolver, so no secret or id reaches fivebar and
  a new route needs nothing added.
- The privacy notice names fivebar, and what it receives, only while it is
  on.

## Consequences

- An app counts nothing until `titan golive`, and nothing before the site
  is added in fivebar.
- Offline, the script and its counts fail quietly; the service worker
  leaves other origins to the browser.
- Events (a sign-up, a purchase) are each app's to add, with
  `tally('Name', {...})` or `data-tally` attributes; see
  https://fiveb.ar/docs/events. Call `tally` directly once the async script
  has loaded, and push onto `window.tally` as a queue before then.
- Error responses are counted as ordinary pages; Safari needs
  `data-status` on the tag to tell them apart, which the template doesn't
  set.
