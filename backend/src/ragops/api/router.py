from fastapi import APIRouter, Depends

from ragops.api.routes import documents, ingestions, ops, query, search, traces
from ragops.security import require_api_key

api_router = APIRouter(prefix="/v1", dependencies=[Depends(require_api_key)])
api_router.include_router(documents.router)
api_router.include_router(ingestions.router)
api_router.include_router(search.router)
api_router.include_router(query.router)
api_router.include_router(traces.router)
api_router.include_router(ops.router)
