"""Tests for apps.core.task_backends: tasks run on a thread of their own."""

import logging
import threading
from typing import Any

import pytest
from django.core import mail
from django.core.cache import cache
from django.core.mail import send_mail
from django.tasks import task
from django.tasks.base import TaskResultStatus
from django.test import Client
from django.urls import reverse

THREADED = {"default": {"BACKEND": "apps.core.task_backends.ThreadBackend"}}

# Module-level, because a task's arguments must be JSON: the test holds the
# task on ``release`` and reads what it saw from ``seen``.
release = threading.Event()
seen: dict[str, Any] = {}


@task()
def note_thread() -> None:
    """Record the thread this task ran on, once released."""
    release.wait(timeout=5)
    seen["thread"] = threading.current_thread()


@task()
def fail() -> None:
    """Fail, as a send to an unreachable mail relay would."""
    raise ConnectionRefusedError("mail relay unreachable")


@pytest.fixture(autouse=True)
def _threaded(settings: Any) -> None:
    """Use the app's own backend, which tests otherwise swap out."""
    settings.TASKS = THREADED
    release.clear()
    seen.clear()


def join(result: Any) -> None:
    """Wait for the thread running ``result``'s task to finish."""
    thread = next(t for t in threading.enumerate() if t.name == f"task-{result.id}")
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_enqueue_returns_before_the_task_runs() -> None:
    """The caller is not held while the task waits; it runs on another thread."""
    result = note_thread.enqueue()
    assert "thread" not in seen
    release.set()
    join(result)
    assert seen["thread"] is not threading.current_thread()
    assert result.status == TaskResultStatus.SUCCESSFUL


def test_a_failed_task_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    """A task that raises is logged at ERROR with its traceback, not lost."""
    with caplog.at_level(logging.ERROR, logger="django.tasks"):
        result = fail.enqueue()
        join(result)
    assert result.status == TaskResultStatus.FAILED
    [record] = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert record.exc_info
    assert "mail relay unreachable" in caplog.text


@pytest.mark.django_db
def test_the_sign_in_email_is_sent_off_the_request(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sign-in page answers while its email is still sending, and the email still goes."""
    cache.clear()
    send = threading.Event()

    def slow_send_mail(*args: Any, **kwargs: Any) -> int:
        """Hold the send, as a slow mail relay would, then send it."""
        send.wait(timeout=5)
        seen["thread"] = threading.current_thread()
        return send_mail(*args, **kwargs)

    monkeypatch.setattr("apps.accounts.tasks.send_mail", slow_send_mail)
    response = client.post(reverse("accounts:sign_in"), {"email": "walker@example.com"})
    assert response.status_code == 302
    assert not mail.outbox
    send.set()
    [thread] = [t for t in threading.enumerate() if t.name.startswith("task-")]
    thread.join(timeout=5)
    assert seen["thread"] is thread
    assert mail.outbox[0].to == ["walker@example.com"]
