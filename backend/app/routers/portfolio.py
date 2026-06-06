"""
portfolio.py — Portfolio view for the active account
====================================================
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_active_account, get_current_user
from ..models import BrokerAccount, User
from ..schemas import PortfolioRow
from ..services import portfolio as pf
from ..services.settrade_manager import manager as settrade_manager

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


def _client_for(account: BrokerAccount):
    try:
        return settrade_manager.get_or_connect(account)
    except ImportError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "settrade-v2 not installed on the server")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Connection failed: {e}")


@router.get("", response_model=list[PortfolioRow])
def get_portfolio(account: BrokerAccount = Depends(get_active_account),
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    client = _client_for(account)
    rows = pf.fetch_portfolio(client.equity_ctx, client.deriv_ctx)
    return [PortfolioRow(**r) for r in rows]
