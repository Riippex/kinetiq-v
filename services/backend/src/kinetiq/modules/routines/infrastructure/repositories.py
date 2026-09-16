from __future__ import annotations

from uuid import UUID

from kinetiq.modules.routines.application.ports import RoutineRepository
from kinetiq.modules.routines.domain.entities import Routine
from kinetiq.modules.routines.infrastructure.models import RoutineRecord


class DjangoRoutineRepository(RoutineRepository):
    def save(self, routine: Routine) -> None:
        RoutineRecord.objects.update_or_create(
            id=routine.id,
            defaults={
                "routine_id": routine.routine_id,
                "owner_id": routine.owner_id,
                "version": routine.version,
                "title": routine.title,
                "rationale": routine.rationale,
                "prescription": routine.prescription,
                "accepted": routine.accepted,
            },
        )

    def get_by_id(self, record_id: UUID) -> Routine | None:
        try:
            record = RoutineRecord.objects.get(id=record_id)
            return self._to_entity(record)
        except RoutineRecord.DoesNotExist:
            return None

    def get_by_routine_id(
        self, owner_id: UUID, routine_id: UUID, version: int
    ) -> Routine | None:
        try:
            record = RoutineRecord.objects.get(
                owner_id=owner_id, routine_id=routine_id, version=version
            )
            return self._to_entity(record)
        except RoutineRecord.DoesNotExist:
            return None

    def get_latest_for_owner(self, owner_id: UUID) -> Routine | None:
        record = (
            RoutineRecord.objects.filter(owner_id=owner_id)
            .order_by("-created_at")
            .first()
        )
        if record is None:
            return None
        return self._to_entity(record)

    def get_active_accepted(self, owner_id: UUID) -> Routine | None:
        record = (
            RoutineRecord.objects.filter(owner_id=owner_id, accepted=True)
            .order_by("-created_at")
            .first()
        )
        if record is None:
            return None
        return self._to_entity(record)

    def list_for_owner(self, owner_id: UUID) -> list[Routine]:
        records = RoutineRecord.objects.filter(owner_id=owner_id).order_by(
            "-created_at"
        )
        return [self._to_entity(r) for r in records]

    @staticmethod
    def _to_entity(record: RoutineRecord) -> Routine:
        return Routine(
            id=record.id,
            routine_id=record.routine_id,
            owner_id=record.owner_id,
            version=record.version,
            title=record.title,
            rationale=record.rationale,
            prescription=record.prescription,
            accepted=record.accepted,
            created_at=record.created_at,
        )
