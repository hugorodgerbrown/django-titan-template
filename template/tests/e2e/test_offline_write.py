"""A note written offline is kept, shown at once, and saved when back online.

Scenario: offline write (docs/testing.md, "Journeys").
"""

from playwright.sync_api import Page, expect

from apps.notes.models import Note


def test_note_written_offline_is_saved_when_back_online(signed_in_page: Page) -> None:
    """The whole outbox path: offline page load, queued write, drain on reconnect."""
    page = signed_in_page
    page.context.set_offline(True)
    page.reload()
    expect(page.get_by_role("heading", name="Notes")).to_be_visible()
    expect(page.locator("[data-offline-banner]")).to_be_visible()

    page.get_by_label("New note").fill("Written on the hill")
    page.get_by_role("button", name="Add note").click()
    expect(page.locator(".note--pending")).to_contain_text("Written on the hill")
    expect(page.locator("[data-outbox-status]")).to_have_text("1 waiting to send")
    assert not Note.objects.exists()

    page.context.set_offline(False)
    expect(page.locator("#note-items")).to_contain_text("Written on the hill")
    expect(page.locator(".note--pending")).to_have_count(0)
    assert Note.objects.get().text == "Written on the hill"
