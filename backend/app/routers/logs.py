"""
logs.py — Activity log feed for the active account
==================================================
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_active_account
from ..models import BrokerAccount
from ..schemas import LogOut
from ..services import crud

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("", response_model=list[LogOut])
def get_logs(limit: int = 200, account: BrokerAccount = Depends(get_active_account),
             db: Session = Depends(get_db)):
    return crud.recent_logs(db, account_id=account.id, limit=limit)
