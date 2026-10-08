from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_api_key
from app.db.session import get_db
from app.services import analysis_service

DbSession = Annotated[AsyncSession, Depends(get_db)]
ApiKey = Annotated[str, Depends(require_api_key)]


async def get_analysis_or_404(session: DbSession, analysis_id: UUID):
    analysis = await analysis_service.get_analysis(session, analysis_id)
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")
    return analysis
