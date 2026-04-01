"""Strategy Builder API — Phase 2 STUB. All endpoints return 501 Not Implemented."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

@router.api_route("/{path:path}", methods=["GET","POST","PUT","DELETE"])
async def strategy_builder_stub(path: str):
    return JSONResponse(
        status_code=501,
        content={"detail": "Strategy Builder is coming in Phase 2. Not yet implemented."}
    )
