"""Dashboard endpoints."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.api.schemas import DashboardStats
from src.auth.dependencies import get_current_user
from src.auth.models import UserContext
from src.db.models import Audit, AuditViolation
from src.db.session import get_db

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStats)
def get_dashboard_stats(
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    team_id = user.team_id
    total = db.query(func.count(Audit.id)).filter(Audit.team_id == team_id).scalar() or 0
    passed = db.query(func.count(Audit.id)).filter(
        Audit.team_id == team_id, Audit.final_status == "PASS"
    ).scalar() or 0
    violations = db.query(func.count(AuditViolation.id)).join(Audit).filter(
        Audit.team_id == team_id
    ).scalar() or 0

    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    this_week = db.query(func.count(Audit.id)).filter(
        Audit.team_id == team_id, Audit.created_at >= week_ago
    ).scalar() or 0

    pass_rate = (passed / total * 100) if total > 0 else 0.0
    # ponytail: avg_time not tracked in DB yet. Hardcoded from e2e measurement.
    # Upgrade: add duration_seconds column to audits table.
    avg_time = 2.9

    return DashboardStats(
        total_audits=total,
        pass_rate=round(pass_rate, 1),
        violation_count=violations,
        avg_time_seconds=avg_time,
        audits_this_week=this_week,
    )
