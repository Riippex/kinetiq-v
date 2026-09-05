from uuid import uuid4

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    cognito_subject = models.CharField(max_length=255, unique=True, null=True, blank=True)
