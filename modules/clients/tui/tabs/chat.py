"""ChatTab — threaded agent conversations.

Two-column layout: thread list on left, conversation on right with
message input at bottom. Supports streaming responses via TuiEventBus.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Input, Label, RichLog, Static

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


class _ThreadItem(Static):
    """Clickable thread entry in the chat list."""

    class Selected(Message):
        def __init__(self, session_id: str, agent_name: str) -> None:
            super().__init__()
            self.session_id = session_id
            self.agent_name = agent_name

    def __init__(self, session: dict, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._session = session

    def compose(self) -> ComposeResult:
        agent = self._session.get("agent_name", "Unknown")
        last_msg = (self._session.get("last_message", "") or "")[:30]
        created = self._session.get("created_at", "")[:16]
        yield Static(
            f"  [bold]{agent}[/bold]\n"
            f"  [dim]{last_msg or 'No messages'}[/dim]\n"
            f"  [dim]{created}[/dim]",
            markup=True,
        )

    def on_click(self) -> None:
        self.post_message(
            self.Selected(
                session_id=self._session.get("session_id", ""),
                agent_name=self._session.get("agent_name", ""),
            )
        )


class ChatTab(Static):
    """Agent conversations with threaded messages."""

    def compose(self) -> ComposeResult:
        with Horizontal(id="chat-container"):
            # ── Left: Thread list ─────────────────────────────────
            with Vertical(id="chat-threads-panel"):
                yield Label(
                    "[bold]THREADS[/bold]",
                    markup=True,
                    classes="sidebar-heading",
                )
                yield Button(
                    "+ New Chat",
                    id="chat-new-btn",
                    variant="default",
                )
                yield VerticalScroll(
                    Static(
                        "[dim]Loading...[/dim]",
                        id="chat-threads-placeholder",
                        markup=True,
                    ),
                    id="chat-threads-scroll",
                )

            # ── Right: Conversation ───────────────────────────────
            with Vertical(id="chat-conversation-panel"):
                yield Label(
                    "[dim]Select a thread or start a new chat[/dim]",
                    id="chat-agent-label",
                    markup=True,
                )
                yield RichLog(
                    id="chat-messages-log",
                    highlight=True,
                    markup=True,
                )
                with Horizontal(id="chat-input-bar"):
                    yield Input(
                        placeholder="Type message...",
                        id="chat-message-input",
                    )
                    yield Button(
                        "Send",
                        id="chat-send-btn",
                        variant="primary",
                    )

    async def on_mount(self) -> None:
        self.run_worker(self._load_sessions(), thread=False)

    async def _load_sessions(self) -> None:
        """Fetch existing chat sessions."""
        mission_id = self.app.state.current_mission_id
        if not mission_id:
            return

        try:
            sessions = await self.app.bridge.list_sessions(
                mission_id=mission_id,
            )
            self.app.state.chat.sessions = sessions
            self._render_thread_list(sessions)
        except Exception as exc:
            logger.warning("Could not load sessions", exc_info=True)
            scroll = self.query_one(
                "#chat-threads-scroll",
                VerticalScroll,
            )
            scroll.remove_children()
            scroll.mount(
                Static(f"[dim]{exc}[/dim]", markup=True),
            )

    def _render_thread_list(self, sessions: list[dict]) -> None:
        scroll = self.query_one(
            "#chat-threads-scroll",
            VerticalScroll,
        )
        scroll.remove_children()

        if not sessions:
            scroll.mount(
                Static(
                    "Start a conversation with any\n"
                    "agent on your team.\n"
                    "[dim]Press [bold]+ New Chat[/bold] above[/dim]",
                    markup=True,
                    classes="placeholder-panel",
                ),
            )
            return

        for session in sessions:
            scroll.mount(
                _ThreadItem(session, classes="mission-item"),
            )

    async def on__thread_item_selected(
        self,
        event: _ThreadItem.Selected,
    ) -> None:
        """Load conversation when thread is clicked."""
        self.app.state.chat.active_session_id = event.session_id
        try:
            label = self.query_one("#chat-agent-label", Label)
            label.update(f"[bold]{event.agent_name}[/bold]")
        except Exception:
            logger.debug("chat agent label update failed", exc_info=True)

        self.run_worker(
            self._load_messages(event.session_id),
            thread=False,
        )

    async def _load_messages(self, session_id: str) -> None:
        """Fetch and display message history."""
        try:
            messages = await self.app.bridge.get_session_messages(
                session_id=session_id,
            )
            self.app.state.chat.messages = messages
            self._render_messages(messages)
        except Exception as exc:
            logger.warning("Could not load messages", exc_info=True)

    def _render_messages(self, messages: list[dict]) -> None:
        """Render messages in the RichLog."""
        try:
            log = self.query_one("#chat-messages-log", RichLog)
            log.clear()
            for msg in messages:
                role = msg.get("role", "")
                content = msg.get("content", "")
                cost = msg.get("cost_usd", 0.0)
                if role == "user":
                    log.write(f"[bold]You:[/bold] {content}")
                else:
                    log.write(f"[bold]{role}:[/bold] {content}")
                    if cost:
                        log.write(f"  [dim]${cost:.4f}[/dim]")
                log.write("")
        except Exception:
            logger.debug("chat messages render failed", exc_info=True)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "chat-new-btn":
            await self._create_new_chat()
        elif event.button.id == "chat-send-btn":
            await self._send_message()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "chat-message-input":
            await self._send_message()

    async def _create_new_chat(self) -> None:
        """Create a new chat session with a team agent."""
        mission_id = self.app.state.current_mission_id
        if not mission_id:
            return

        # Use first team member as default agent
        team = self.app.state.team.members
        if not team:
            self.app.notify(
                "No agents on team. Add agents first (Alt+2).",
                severity="warning",
            )
            return

        agent_name = team[0].get("agent_name", "")
        try:
            result = await self.app.bridge.create_session(
                mission_id=mission_id,
                agent_name=agent_name,
            )
            self.app.state.chat.active_session_id = result["session_id"]
            self.app.notify(
                f"Chat started with {agent_name}",
                severity="information",
            )
            await self._load_sessions()
        except Exception as exc:
            logger.error("Failed to create chat", exc_info=True)
            self.app.notify(f"Chat error: {exc}", severity="error")

    async def _send_message(self) -> None:
        """Send message in current thread."""
        session_id = self.app.state.chat.active_session_id
        if not session_id:
            self.app.notify("Select a thread first", severity="warning")
            return

        try:
            inp = self.query_one("#chat-message-input", Input)
            content = inp.value.strip()
            if not content:
                return
            inp.value = ""

            # Show user message immediately
            try:
                log = self.query_one("#chat-messages-log", RichLog)
                log.write(f"[bold]You:[/bold] {content}")
                log.write("")
            except Exception:
                logger.debug("chat user message display failed", exc_info=True)

            await self.app.bridge.send_message(
                session_id=session_id,
                content=content,
            )
        except Exception as exc:
            logger.error("Failed to send message", exc_info=True)
            self.app.notify(f"Send failed: {exc}", severity="error")
