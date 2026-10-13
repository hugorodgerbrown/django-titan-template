"""What the design page leaves out, and why.

tests/test_design.py fails when a component in app.css isn't on the design
page. A component that can't sit on the page (the page's own frame, a
screen that covers everything) is named here with the reason instead.
"""

# Component (block) class -> why it isn't on the design page.
NOT_ON_PAGE: dict[str, str] = {
    "app-header": "the frame of every page, the design page included",
    "app-main": "the frame of every page, the design page included",
    "offline-banner": "the frame of every page; shown while offline",
    "launch-shell": "covers the whole screen while the app launches",
    "app-launching": "the state the launch screen is in, set on <html>",
    "htmx-indicator": "htmx's own request state",
    "htmx-request": "htmx's own request state",
    "outbox-status": "the frame of every page; shown while writes wait to send",
}

# Classes a framework puts on elements (no template here names them), so the
# dead-CSS check counts them as used.
ADDED_BY_FRAMEWORKS: dict[str, str] = {
    "errorlist": "Django renders it round a form's errors",
}
