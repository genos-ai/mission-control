"""
Mission Run Digest Repository (Plan 88, contract 3.5.2).

Data access for mission_run_digests. Digests are written from Phase 3.
"""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from modules.backend.models.mission_run_digest import MissionRunDigest
from modules.backend.repositories.base import BaseRepository


class MissionRunDigestRepository(BaseRepository[MissionRunDigest]):
    """Repository for MissionRunDigest rows."""

    model = MissionRunDigest

    async def get_by_run(self, run_id: str) -> MissionRunDigest | None:
        """The digest of a run; mission_run_id is unique."""
        stmt = select(MissionRunDigest).where(MissionRunDigest.mission_run_id == run_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_for_mission(self, mission_id: str, run_id: str) -> MissionRunDigest | None:
        """The digest of a run, only if the run belongs to the mission."""
        stmt = select(MissionRunDigest).where(
            MissionRunDigest.mission_run_id == run_id,
            MissionRunDigest.mission_id == mission_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def insert_if_absent(self, **values: object) -> MissionRunDigest | None:
        """Insert the run's digest; None when the run already has one.

        INSERT ... ON CONFLICT (mission_run_id) DO NOTHING RETURNING *.
        """
        stmt = (
            pg_insert(MissionRunDigest)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[MissionRunDigest.mission_run_id])
            .returning(MissionRunDigest)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()
