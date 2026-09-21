from uuid import UUID

from django.contrib.auth import get_user_model


class DjangoSubjectDirectory:
    """`SubjectDirectory` backed by the user table's `cognito_subject`."""

    def active_user_id_for_subject(self, subject: str) -> UUID | None:
        if not subject:
            return None
        user_id: UUID | None = (
            get_user_model()
            .objects.filter(cognito_subject=subject, is_active=True)
            .values_list("id", flat=True)
            .first()
        )
        return user_id
