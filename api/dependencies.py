from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from core.data_fetcher import SmartDataFetcher


async def get_fetcher(request: Request) -> SmartDataFetcher:
    return request.app.state.fetcher


FetcherDep = Annotated[SmartDataFetcher, Depends(get_fetcher)]
