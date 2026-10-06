"""Tests for apps.core.views."""

from django.test import Client
from django.urls import reverse


def test_healthz_needs_no_sign_in_or_database(client: Client) -> None:
    """Render's health check answers 200 to anyone."""
    response = client.get(reverse("healthz"))
    assert response.status_code == 200
    assert response.content == b"ok"


def test_csrf_failure_is_marked_for_the_outbox(user: object) -> None:
    """A CSRF rejection carries X-CSRF-Failure, so the outbox waits instead of dropping."""
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)  # type: ignore[arg-type]
    response = client.post(reverse("notes:create"), "{}", content_type="application/json")
    assert response.status_code == 403
    assert response["X-CSRF-Failure"] == "1"
