"""Audit logging service: async background writer for protected endpoint access.

Writes to the audit_logs table with who/what/when/result.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from app.core.db import async_session_factory
from app.models import AuditLog

logger = structlog.get_logger()


async def log_audit(
    action: str,
    user_id: str | None,
    venue_id: str | None,
    result: str,
    status_code: int | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Write an audit log entry asynchronously (best-effort, non-blocking)."""
    try:
        async with async_session_factory() as session:
            entry = AuditLog(
                action=action,
                user_id=user_id,
                venue_id=venue_id,
                result=result,
                status_code=status_code,
                ip_address=ip_address,
                user_agent=user_agent,
                request_id=request_id,
                resource_type=resource_type,
                resource_id=resource_id,
                details_json=json.dumps(details) if details else None,
            )
            session.add(entry)
            await session.commit()
    except Exception:
        logger.warning("audit_log_failed", action=action, user_id=user_id, exc_info=True)
