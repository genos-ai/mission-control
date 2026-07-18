"""Tests for store_artifact tool (Plan 79 §9.1 extension).

The extension lets the tool accept str/dict/list content and JSON-encode
non-string content. Fails loud on type/content_type mismatch.

These tests don't exercise the actual DB persistence — they verify the
content-encoding and validation layer added by Plan 79.
"""

from __future__ import annotations

import pytest


class TestStoreArtifactContentValidation:
    """Plan 79 §9.1 — the type/content_type validation gate."""

    @pytest.mark.asyncio
    async def test_dict_with_markdown_content_type_raises(self):
        from modules.backend.tools.store_artifact import store_artifact

        with pytest.raises(ValueError, match="structured content requires"):
            await store_artifact(
                mission_id="m1",
                title="X",
                content={"a": 1},
                content_type="markdown",
            )

    @pytest.mark.asyncio
    async def test_list_with_text_content_type_raises(self):
        from modules.backend.tools.store_artifact import store_artifact

        with pytest.raises(ValueError, match="structured content requires"):
            await store_artifact(
                mission_id="m1",
                title="X",
                content=[1, 2, 3],
                content_type="text",
            )

    @pytest.mark.asyncio
    async def test_int_content_raises_type_error(self):
        from modules.backend.tools.store_artifact import store_artifact

        with pytest.raises(TypeError, match="must be str/dict/list"):
            await store_artifact(
                mission_id="m1",
                title="X",
                content=42,
                content_type="json",  # type: ignore[arg-type]
            )

    def test_json_encodes_dict_content(self):
        # Verify the JSON-encoding step in isolation. We import the
        # encoding logic by inspecting the function's behaviour on
        # the validation path (raises before DB) when content_type
        # is wrong, AND on the success path when content_type=json.
        # We can't easily call store_artifact() without a real DB —
        # but we can check that the json encoding contract holds via
        # a small spy that captures content_text.
        import json

        from modules.backend.tools import store_artifact as mod

        captured: dict = {}

        class _FakeService:
            def __init__(self, db):
                pass

            async def create_artifact(self, **kwargs):
                captured.update(kwargs)

                class _A:
                    id = "fake-id"

                return _A()

        # Patch the DB + service to a no-op.
        class _FakeDB:
            async def commit(self):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        original_get_async_session = None
        try:
            from modules.backend.core import database as db_mod
            from modules.backend.services import mission_artifact as art_mod

            original_get_async_session = db_mod.get_async_session
            db_mod.get_async_session = lambda: _FakeDB()
            art_mod.MissionArtifactService = _FakeService

            async def _run():
                payload = {"cruxes": [{"q": "a"}, {"q": "b"}], "confidence": 0.7}
                await mod.store_artifact(
                    mission_id="m1",
                    title="T",
                    content=payload,
                    artifact_type="deliberation_deliverable",
                    content_type="json",
                )

            import asyncio

            asyncio.run(_run())

            assert "content_text" in captured
            decoded = json.loads(captured["content_text"])
            assert decoded == {
                "cruxes": [{"q": "a"}, {"q": "b"}],
                "confidence": 0.7,
            }
        finally:
            if original_get_async_session is not None:
                from modules.backend.core import database as db_mod

                db_mod.get_async_session = original_get_async_session
