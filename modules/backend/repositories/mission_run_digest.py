"""
Mission Run Digest Repository (Plan 88, contract 3.5.2).

Data access for mission_run_digests. Digests are written from Phase 3.
"""

from sqlalchemy import select

from modules.backend.models.mission_run_digest import MissionRunDigest
from modules.backend.repositories.base import BaseRepository


class MissionRunDigestRepository(BaseRepository[MissionRunDigest]):
    """Repository for MissionRunDigest rows."""

    model = MissionRunDigest

    async def get_by_run(self, run_id: str) -> MissionRunDigest | None:
        """The digest of a run; mission_run_id is unique."""
        stmt = select(MissionRunDigest).where(MissionRunDigest.mission_run_id == run_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()
