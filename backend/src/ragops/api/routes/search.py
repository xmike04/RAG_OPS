from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ragops.api.dependencies import get_search_service
from ragops.db.session import get_session
from ragops.schemas.search import ScoreContribution, SearchHit, SearchRequest, SearchResponse

router = APIRouter(tags=["retrieval"])


def _attr(value: Any, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _to_api_hit(hit: Any) -> SearchHit:
    contributions = [
        ScoreContribution.model_validate(item, from_attributes=True)
        for item in _attr(hit, "contributions", ())
    ]
    raw_by_source = {item.source: item.raw_score for item in contributions}
    return SearchHit(
        chunk_id=_attr(hit, "chunk_id"),
        document_id=_attr(hit, "document_id"),
        content=_attr(hit, "content", None) or _attr(hit, "text", ""),
        metadata=dict(_attr(hit, "metadata", {})),
        rank=_attr(hit, "rank"),
        fused_score=_attr(hit, "fused_score"),
        final_score=_attr(hit, "final_score"),
        lexical_score=raw_by_source.get("lexical"),
        vector_score=raw_by_source.get("vector"),
        rerank_score=_attr(hit, "rerank_score"),
        rrf_contributions={item.source: item.rrf_score for item in contributions},
        contributions=contributions,
    )


@router.post("/search", response_model=SearchResponse)
async def hybrid_search(
    payload: SearchRequest,
    session: AsyncSession = Depends(get_session),
    service: Any = Depends(get_search_service),
) -> SearchResponse:
    result = await service.search(
        session,
        payload.workspace_id,
        payload.query,
        top_k=payload.top_k,
        rerank=payload.rerank,
    )
    raw_hits = list(_attr(result, "results", []))
    hits = [_to_api_hit(hit) for hit in raw_hits]
    latency = (
        _attr(result, "latency_ms", None)
        or _attr(result, "timing_ms", None)
        or _attr(result, "stage_ms", {})
    )
    providers = _attr(result, "providers", None) or _attr(result, "provider_metadata", None)
    if providers is None:
        providers = {
            "embedding_provider": _attr(result, "embedding_provider", "unknown"),
            "embedding_model": _attr(result, "embedding_model", "unknown"),
        }
        if _attr(result, "rerank_provider"):
            providers.update(
                rerank_provider=_attr(result, "rerank_provider"),
                rerank_model=_attr(result, "rerank_model", "unknown"),
            )
    return SearchResponse(
        results=hits,
        total=len(hits),
        latency_ms={str(key): float(value) for key, value in dict(latency).items()},
        providers={str(key): str(value) for key, value in dict(providers).items()},
    )
