"""ProfileScreen — user profile and API key management.

Accessible via Ctrl+U. Shows display name, email, role info.
For non-service accounts, includes password change section.
API key management with create/revoke.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Static,
)

from modules.backend.core.logging import get_logger
from modules.backend.models.base import SYSTEM_CLI_ID

logger = get_logger(__name__)


class ProfileScreen(Screen):
    """Current user profile and API key management."""

    BINDINGS = [
        Binding("escape", "go_back", "Back"),
    ]

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._is_service_account = True
        self._user_id = SYSTEM_CLI_ID

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="profile-body"):
            yield Label(
                "[bold]PROFILE[/bold]",
                markup=True,
                id="profile-title",
            )

            # ── Profile info ──────────────────────────────────────
            with Horizontal(id="profile-name-row"):
                yield Label("Display Name: ", id="profile-name-label")
                yield Input(
                    "",
                    id="profile-name-input",
                    placeholder="Display name",
                )
                yield Button(
                    "Save",
                    id="profile-save-name-btn",
                    variant="default",
                )
            yield Static(
                "",
                id="profile-info",
                markup=True,
            )

            # ── Change password (hidden for service accounts) ─────
            yield Label(
                "[bold]── CHANGE PASSWORD ──[/bold]",
                markup=True,
                id="profile-pw-heading",
            )
            yield Input(
                "",
                id="profile-pw-current",
                placeholder="Current password",
                password=True,
            )
            yield Input(
                "",
                id="profile-pw-new",
                placeholder="New password (min 12 characters)",
                password=True,
            )
            yield Input(
                "",
                id="profile-pw-confirm",
                placeholder="Confirm new password",
                password=True,
            )
            yield Button(
                "Change Password",
                id="profile-change-pw-btn",
                variant="warning",
            )

            # ── API keys ──────────────────────────────────────────
            yield Label(
                "[bold]── API KEYS ──[/bold]",
                markup=True,
                id="profile-keys-heading",
            )
            yield DataTable(id="profile-keys-table")
            with Horizontal(id="profile-keys-actions"):
                yield Input(
                    "",
                    id="profile-key-name",
                    placeholder="Key name",
                )
                yield Button(
                    "+ Create Key",
                    id="profile-create-key-btn",
                    variant="primary",
                )
        yield Footer()

    async def on_mount(self) -> None:
        table = self.query_one("#profile-keys-table", DataTable)
        table.add_columns("Name", "Prefix", "Expires", "Status")
        self.run_worker(self._load_profile(), thread=False)

    async def _load_profile(self) -> None:
        """Load user profile and API keys."""
        try:
            profile = await self.app.bridge.get_profile()
            self._is_service_account = profile.get(
                "is_service_account", True,
            )
            self._user_id = profile.get("id", SYSTEM_CLI_ID)

            # Populate display name
            try:
                name_input = self.query_one(
                    "#profile-name-input", Input,
                )
                name_input.value = profile.get("display_name", "")
            except Exception:
                pass

            # Show profile info
            try:
                info = self.query_one("#profile-info", Static)
                email = profile.get("email", "")
                role = profile.get("system_role", "")
                info.update(
                    f"Email: {email}\n"
                    f"Role: {role}\n"
                    f"Account type: {'Service account' if self._is_service_account else 'User'}",
                )
            except Exception:
                pass

            # Hide password section for service accounts
            if self._is_service_account:
                self._hide_password_section()

        except Exception as exc:
            logger.warning("Could not load profile", exc_info=True)

        # Load API keys
        try:
            keys = await self.app.bridge.list_api_keys()
            self._render_keys(keys)
        except Exception as exc:
            logger.warning("Could not load API keys", exc_info=True)

    def _hide_password_section(self) -> None:
        """Hide password change widgets for service accounts."""
        ids_to_hide = [
            "profile-pw-heading",
            "profile-pw-current",
            "profile-pw-new",
            "profile-pw-confirm",
            "profile-change-pw-btn",
        ]
        for widget_id in ids_to_hide:
            try:
                widget = self.query_one(f"#{widget_id}")
                widget.display = False
            except Exception:
                pass

    def _render_keys(self, keys: list[dict[str, Any]]) -> None:
        try:
            table = self.query_one("#profile-keys-table", DataTable)
            table.clear()
            for k in keys:
                table.add_row(
                    k.get("name", ""),
                    k.get("prefix", ""),
                    k.get("expires_at", "never"),
                    "Active" if k.get("is_active") else "Revoked",
                    key=k.get("id", ""),
                )
        except Exception:
            pass

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "profile-save-name-btn":
            await self._save_display_name()
        elif event.button.id == "profile-change-pw-btn":
            await self._change_password()
        elif event.button.id == "profile-create-key-btn":
            await self._create_api_key()

    async def _save_display_name(self) -> None:
        try:
            inp = self.query_one("#profile-name-input", Input)
            name = inp.value.strip()
            if not name:
                self.app.notify("Name cannot be empty", severity="warning")
                return
            await self.app.bridge.update_display_name(display_name=name)
            self.app.notify("Display name updated", severity="information")
        except Exception as exc:
            logger.error("Failed to save display name", exc_info=True)
            self.app.notify(f"Save failed: {exc}", severity="error")

    async def _change_password(self) -> None:
        try:
            current = self.query_one(
                "#profile-pw-current", Input,
            ).value
            new_pw = self.query_one(
                "#profile-pw-new", Input,
            ).value
            confirm = self.query_one(
                "#profile-pw-confirm", Input,
            ).value

            if not current or not new_pw:
                self.app.notify(
                    "All password fields required", severity="warning",
                )
                return
            if new_pw != confirm:
                self.app.notify(
                    "New passwords do not match", severity="warning",
                )
                return
            if len(new_pw) < 12:
                self.app.notify(
                    "Password must be at least 12 characters",
                    severity="warning",
                )
                return

            await self.app.bridge.change_password(
                current_password=current,
                new_password=new_pw,
            )
            self.app.notify(
                "Password changed successfully", severity="information",
            )

            # Clear inputs
            for wid in [
                "#profile-pw-current",
                "#profile-pw-new",
                "#profile-pw-confirm",
            ]:
                try:
                    self.query_one(wid, Input).value = ""
                except Exception:
                    pass
        except Exception as exc:
            logger.error("Failed to change password", exc_info=True)
            self.app.notify(f"Password change failed: {exc}", severity="error")

    async def _create_api_key(self) -> None:
        try:
            name_input = self.query_one("#profile-key-name", Input)
            name = name_input.value.strip()
            if not name:
                self.app.notify(
                    "Enter a key name first", severity="warning",
                )
                return

            result = await self.app.bridge.create_api_key(name=name)
            full_key = result.get("full_key", "")
            name_input.value = ""

            self.app.notify(
                f"Key created: {full_key[:20]}...\n"
                f"Copy this key — it won't be shown again!",
                severity="warning",
            )

            # Refresh key list
            keys = await self.app.bridge.list_api_keys()
            self._render_keys(keys)
        except Exception as exc:
            logger.error("Failed to create API key", exc_info=True)
            self.app.notify(f"Key creation failed: {exc}", severity="error")

    def action_go_back(self) -> None:
        self.app.pop_screen()
