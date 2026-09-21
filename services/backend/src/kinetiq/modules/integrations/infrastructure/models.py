from uuid import uuid4

from django.conf import settings
from django.db import models


class McpToolReceipt(models.Model):
    """Idempotency ledger for mutating MCP tools whose product use case has no
    native idempotency key: the first call with a caller-provided key stores
    its response, and a retry replays it instead of repeating the effect."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    tool = models.CharField(max_length=80)
    key = models.CharField(max_length=160)
    request_fingerprint = models.CharField(max_length=64)
    response = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("owner", "tool", "key"), name="mcp_receipt_owner_tool_key_unique"
            )
        ]
