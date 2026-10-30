import asyncio
import threading
from dataclasses import replace
from typing import cast

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Input, Static, TextArea
from tui_snapshots import assert_snapshot

from gbot.pending import classify
from gbot.service.api import Service
from gbot.service.fake import FakeService, load_fake
from gbot.service.models import Action, Card
from gbot.tui.answering import answer_card
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.screens.draft import DraftEditor
from gbot.tui.theme import GBOT_THEME
from gbot.tui.widgets.prompt import CardPrompt
from groken.client import ConnectError


class Host(App):
    def __init__(self, service: FakeService, card: Card):
        super().__init__()
        self.service = service
        self.card = card
        self.notices = []
        self.results = []
        self.later = False
        self.register_theme(GBOT_THEME)
        self.theme = "gbot"

    def compose(self) -> ComposeResult:
        yield CardPrompt(self.card)

    def notify(self, message, **kwargs):
        self.notices.append(message)

    def on_card_prompt_chosen(self, event: CardPrompt.Chosen):
        async def answer():
            self.results.append(
                await answer_card(
                    self,
                    cast(Service, self.service),
                    event.card,
                    event.action,
                    confirm=event.confirm,
                    effect=event.effect,
                )
            )

        self.run_worker(answer())

    def on_card_prompt_later(self, event: CardPrompt.Later):
        self.later = True


def demo(kind):
    service = load_fake()
    return service, next(card for card in service.pending()[0] if card.type == kind)


def synthetic(kind, body_key, body):
    service = load_fake()
    entry = {
        "id": "synthetic",
        "seq": 100,
        "kind": "send-message",
        "message": {"type": kind, body_key: body},
    }
    service.state.transcripts["demo-inbox"].append(entry)
    card = classify(entry, "demo-inbox", "Inbox", "side-session")
    assert card is not None
    return service, card


@pytest.mark.parametrize(
    "kind,labels",
    [
        ("email-draft", ["Send", "Discard", "Edit"]),
        ("widget", ["City Loft", "Dismiss"]),
        ("auto-review-approval", ["Approve", "Deny"]),
    ],
)
def test_choices_and_snapshots(kind, labels):
    async def exercise():
        service, card = demo(kind)
        app = Host(service, card)
        async with app.run_test(size=(80, 24)) as pilot:
            prompt = app.query_one(CardPrompt)
            assert all(label in [c.label for c in prompt.choices] for label in labels)
            if kind != "auto-review-approval":
                await assert_snapshot(app, pilot, f"prompt-{kind}")
            await pilot.press("escape")
            assert app.later

    asyncio.run(exercise())


def test_widget_answers_without_confirm():
    async def exercise():
        service, card = demo("widget")
        app = Host(service, card)
        async with app.run_test() as pilot:
            await pilot.press("2")
            await asyncio.wait_for(app.workers.wait_for_complete(), timeout=10)
            assert service.answered[-1][2] == Action("respond", value="City Loft")
            assert app.notices == ["Answered City Loft"]

    asyncio.run(exercise())


def test_email_cancel_confirm_and_snapshot():
    async def exercise():
        service, card = demo("email-draft")
        app = Host(service, card)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("1")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen)
            assert app.focused is app.screen.query_one("#cancel", Button)
            await assert_snapshot(app, pilot, "prompt-confirm")
            await pilot.press("enter")
            await asyncio.wait_for(app.workers.wait_for_complete(), timeout=10)
            assert service.answered == []
            await pilot.press("1")
            await pilot.pause()
            await pilot.click("#confirm")
            await asyncio.wait_for(app.workers.wait_for_complete(), timeout=10)
            assert app.results[-1].rpc == "SendGrokBotDraft"
            assert service.answered[-1][2] == Action("approve")

    asyncio.run(exercise())


def test_edit_draft():
    async def exercise():
        service, card = demo("email-draft")
        app = Host(service, card)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.press("3")
            assert isinstance(app.screen, DraftEditor)
            app.screen.query_one("#draft-subject", Input).value = "Updated subject"
            app.screen.query_one(
                "#draft-to", Input
            ).value = "ada@example.com, bob@example.com"
            app.screen.query_one("#draft-body", TextArea).load_text("Edited body")
            await pilot.click("#draft-save")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen)
            await pilot.click("#confirm")
            await asyncio.wait_for(app.workers.wait_for_complete(), timeout=10)
            draft = service.answered[-1][2].draft
            assert draft is not None
            assert draft["subject"] == "Updated subject"
            assert draft["to"] == ["ada@example.com", "bob@example.com"]
            assert draft["body"] == "Edited body"
            assert card.draft is not None
            assert draft["from"] == card.draft["from"]

    asyncio.run(exercise())


@pytest.mark.parametrize("pick,confirm", [("1", True), ("2", False)])
def test_approval(pick, confirm):
    async def exercise():
        service, card = demo("auto-review-approval")
        app = Host(service, card)
        async with app.run_test() as pilot:
            await pilot.press(pick)
            await pilot.pause()
            if confirm:
                assert not service.answered
                assert isinstance(app.screen, ConfirmScreen)
                await pilot.click("#confirm")
            await asyncio.wait_for(app.workers.wait_for_complete(), timeout=10)
            assert service.answered[-1][2].kind == ("approve" if confirm else "deny")

    asyncio.run(exercise())


def test_local_tool():
    async def exercise():
        service, card = synthetic(
            "local-tool-permission",
            "ask",
            {
                "status": "pending",
                "requestId": "tool",
                "action": "execute",
                "target": "echo ok",
            },
        )
        app = Host(service, card)
        async with app.run_test() as pilot:
            assert [c.label for c in app.query_one(CardPrompt).choices] == [
                "Allow once",
                "Always allow",
                "Deny",
                "Never allow",
            ]
            await pilot.press("2")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen)
            await pilot.click("#confirm")
            await asyncio.wait_for(app.workers.wait_for_complete(), timeout=10)
            assert service.answered[-1][2] == Action("approve", always=True)

    asyncio.run(exercise())


def test_form_validation_and_input_keys():
    async def exercise():
        service, card = synthetic(
            "user-form",
            "formRequest",
            {
                "fields": [
                    {"id": "name", "label": "Name", "required": True},
                    {"id": "city"},
                ]
            },
        )
        app = Host(service, card)
        async with app.run_test() as pilot:
            await pilot.press("1")
            assert app.notices == ["Fill all required fields"]
            assert not service.answered
            field = app.query_one("#field-0", Input)
            field.focus()
            await pilot.press("A", "1", "e")
            assert field.value == "A1e"
            app.query_one("#field-1", Input).value = "Brisbane"
            await pilot.press("enter")
            await asyncio.wait_for(app.workers.wait_for_complete(), timeout=10)
            assert dict(service.answered[-1][2].fields) == {
                "name": "A1e",
                "city": "Brisbane",
            }

    asyncio.run(exercise())


def test_secret_mask_clear_and_confirm():
    async def exercise():
        service, card = synthetic(
            "secret-request", "secretRequest", {"title": "API key"}
        )
        app = Host(service, card)
        async with app.run_test() as pilot:
            field = app.query_one("#secret-value", Input)
            field.focus()
            await pilot.press(*"private-test-key")
            assert field.password
            assert "private-test-key" not in app.export_screenshot()
            await pilot.press("enter")
            await pilot.pause()
            assert field.value == ""
            assert isinstance(app.screen, ConfirmScreen)
            assert "private-test-key" not in app.export_screenshot()
            await pilot.click("#confirm")
            await asyncio.wait_for(app.workers.wait_for_complete(), timeout=10)
            assert app.results[-1].rpc == "SubmitGrokBotSecret"
            assert "private-test-key" not in str(app.notices)
            assert "private-test-key" not in repr(service.answered)

    asyncio.run(exercise())


def test_stale_and_error_no_retry(monkeypatch):
    async def exercise():
        service, card = demo("widget")
        main_thread = threading.get_ident()
        calls = []

        def stale(card):
            assert threading.get_ident() != main_thread
            return False

        monkeypatch.setattr(service, "still_pending", stale)
        app = Host(service, card)
        async with app.run_test() as pilot:
            await pilot.press("2")
            await asyncio.wait_for(app.workers.wait_for_complete(), timeout=10)
            assert app.notices == ["This card was already answered"]
            assert not service.answered
            monkeypatch.setattr(service, "still_pending", lambda card: True)

            def refused(card, action):
                assert threading.get_ident() != main_thread
                calls.append(action)
                raise ValueError("Refused [link=x]\x1b")

            monkeypatch.setattr(service, "answer", refused)
            await pilot.press("2")
            await asyncio.wait_for(app.workers.wait_for_complete(), timeout=10)
            assert len(calls) == 1
            assert app.notices[-1] == "Refused [link=x]\\u001b"

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "kind", ["slack-draft", "meeting-chat-draft", "permission-request"]
)
def test_other_cards(kind):
    async def exercise():
        service, card = synthetic(
            kind,
            "draft" if "draft" in kind else "permission",
            {"target": "#team", "body": "Hello"},
        )
        app = Host(service, card)
        async with app.run_test() as pilot:
            labels = [choice.label for choice in app.query_one(CardPrompt).choices]
            if kind == "permission-request":
                assert labels == ["Later"]
                assert any(
                    "Answer this in the Grok Bot app" in str(widget.content)
                    for widget in app.query(Static)
                )
            elif kind == "meeting-chat-draft":
                assert labels == ["Discard"]
            else:
                assert labels == ["Send", "Discard", "Edit"]
                await pilot.press("3", "escape")
                assert not service.answered
            await pilot.press("escape")
            assert app.later

    asyncio.run(exercise())


def test_hostile_text_and_expand():
    async def exercise():
        service, card = demo("email-draft")
        hostile = "[link=x]literal[/link] \x1b[31m"
        card = replace(card, summary=hostile, tool_text="\n".join([hostile] * 10))
        app = Host(service, card)
        async with app.run_test(size=(100, 40)) as pilot:
            body = app.query_one("#prompt-body", Static)
            text = str(body.content)
            assert "[link=x]literal[/link] \\u001b[31m" in text
            assert "e to expand" in text
            await pilot.press("e")
            assert str(body.content).count("literal") == 10
            await pilot.press("e")
            assert str(body.content).count("literal") == 8

    asyncio.run(exercise())


def test_discard_requires_confirmation_and_navigation():
    async def exercise():
        service, card = demo("email-draft")
        app = Host(service, card)
        async with app.run_test() as pilot:
            await pilot.press("down", "enter")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen)
            assert not service.answered
            await pilot.press("escape")
            await asyncio.wait_for(app.workers.wait_for_complete(), timeout=10)
            assert not service.answered
            await pilot.press("up", "down", "enter")
            await pilot.pause()
            await pilot.click("#confirm")
            await asyncio.wait_for(app.workers.wait_for_complete(), timeout=10)
            assert app.results[-1].rpc == "DiscardGrokBotDraft"

    asyncio.run(exercise())


def test_hostile_draft_editor():
    async def exercise():
        hostile = "[link=x]literal[/link] \x1b[31m"
        service, card = synthetic(
            "email-draft",
            "draft",
            {
                "from": "me@example.com",
                "to": ["ada@example.com"],
                "subject": hostile,
                "body": hostile,
            },
        )
        app = Host(service, card)
        async with app.run_test(size=(100, 40)) as pilot:
            assert "[link=x]literal[/link] \\u001b[31m" in str(
                app.query_one("#prompt-body", Static).content
            )
            await pilot.press("3")
            assert (
                app.screen.query_one("#draft-body", TextArea).text
                == "[link=x]literal[/link] \\u001b[31m"
            )
            assert (
                app.screen.query_one("#draft-subject", Input).value
                == "[link=x]literal[/link] \\u001b[31m"
            )
            await pilot.press("escape")
            assert not service.answered

    asyncio.run(exercise())


def test_secret_error_redacted(monkeypatch):
    async def exercise():
        service, card = synthetic(
            "secret-request", "secretRequest", {"title": "API key"}
        )

        def refused(card, action):
            raise ValueError(action.secret)

        monkeypatch.setattr(service, "answer", refused)
        app = Host(service, card)
        async with app.run_test() as pilot:
            app.query_one("#secret-value", Input).value = "never-display-this"
            await pilot.press("1")
            await pilot.pause()
            await pilot.click("#confirm")
            await asyncio.wait_for(app.workers.wait_for_complete(), timeout=10)
            assert app.results == [None]
            assert app.notices == [
                "Secret was not submitted successfully; no value is displayed."
            ]

    asyncio.run(exercise())


def test_untouched_draft_fields_keep_their_original_text():
    async def exercise():
        service, card = demo("email-draft")
        assert card.draft is not None
        original = {**card.draft, "body": "Paid \u202eok\u202c thanks"}
        card = replace(card, draft=original)
        app = Host(service, card)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.press("3")
            assert isinstance(app.screen, DraftEditor)
            app.screen.query_one("#draft-subject", Input).value = "Updated subject"
            await pilot.click("#draft-save")
            await pilot.pause()
            await pilot.click("#confirm")
            await asyncio.wait_for(app.workers.wait_for_complete(), timeout=10)
            draft = service.answered[-1][2].draft
            assert draft is not None
            assert draft["subject"] == "Updated subject"
            assert draft["body"] == "Paid \u202eok\u202c thanks"
            assert draft["to"] == original["to"]

    asyncio.run(exercise())


def test_unmatched_actions_fall_back_to_the_app():
    async def exercise():
        service, card = demo("auto-review-approval")
        app = Host(service, replace(card, allowed_actions=("respond",)))
        async with app.run_test() as pilot:
            assert [c.label for c in app.query_one(CardPrompt).choices] == ["Later"]
            assert any(
                "Answer this in the Grok Bot app" in str(widget.content)
                for widget in app.query(Static)
            )
            await pilot.press("down", "enter")
            assert app.later
            assert not service.answered

    asyncio.run(exercise())


def test_recheck_after_confirm_and_transport_errors(monkeypatch):
    async def exercise():
        service, card = demo("auto-review-approval")
        checks = iter([True, False])
        monkeypatch.setattr(service, "still_pending", lambda card: next(checks))
        app = Host(service, card)
        async with app.run_test() as pilot:
            await pilot.press("1")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen)
            await pilot.click("#confirm")
            await asyncio.wait_for(app.workers.wait_for_complete(), timeout=10)
            assert app.notices[-1] == "This card was already answered"
            assert not service.answered
            monkeypatch.setattr(service, "still_pending", lambda card: True)

            def offline(card, action):
                raise ConnectError(503, "gateway down")

            monkeypatch.setattr(service, "answer", offline)
            await pilot.press("2")
            await asyncio.wait_for(app.workers.wait_for_complete(), timeout=10)
            assert app.notices[-1].startswith("Could not answer:")

    asyncio.run(exercise())
