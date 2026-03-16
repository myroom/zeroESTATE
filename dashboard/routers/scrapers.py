from datetime import datetime

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db import get_db
from shared.models import Source, ScraperConfig, ScraperRun

import pathlib

router = APIRouter()
templates = Jinja2Templates(directory=str(pathlib.Path(__file__).resolve().parent.parent / "templates"))


@router.get("/scrapers")
async def scrapers_page(request: Request, db: AsyncSession = Depends(get_db)):
    sources_q = await db.execute(
        select(Source, ScraperConfig)
        .outerjoin(ScraperConfig, Source.id == ScraperConfig.source_id)
        .order_by(Source.name)
    )
    sources = sources_q.all()

    scrapers = []
    for src, cfg in sources:
        # Recent runs
        runs_q = await db.execute(
            select(ScraperRun)
            .where(ScraperRun.source_id == src.id)
            .order_by(ScraperRun.started_at.desc())
            .limit(10)
        )
        recent_runs = runs_q.scalars().all()

        scrapers.append({
            "source": src,
            "config": cfg,
            "recent_runs": recent_runs,
        })

    return templates.TemplateResponse("pages/scrapers.html", {
        "request": request,
        "scrapers": scrapers,
        "current_page": "scrapers",
    })


@router.post("/scrapers/{source_id}/toggle")
async def toggle_scraper(source_id: int, db: AsyncSession = Depends(get_db)):
    cfg_q = await db.execute(
        select(ScraperConfig).where(ScraperConfig.source_id == source_id)
    )
    cfg = cfg_q.scalar()
    if cfg:
        cfg.enabled = not cfg.enabled
        await db.commit()

    return RedirectResponse(url="/scrapers", status_code=303)


@router.post("/scrapers/{source_id}/update")
async def update_scraper(
    source_id: int,
    cron_expression: str = Form(""),
    proxy_url: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    cfg_q = await db.execute(
        select(ScraperConfig).where(ScraperConfig.source_id == source_id)
    )
    cfg = cfg_q.scalar()
    if cfg:
        if cron_expression:
            cfg.cron_expression = cron_expression
        cfg.proxy_url = proxy_url
        await db.commit()

    return RedirectResponse(url="/scrapers", status_code=303)


@router.post("/scrapers/{source_id}/run")
async def run_scraper(source_id: int, db: AsyncSession = Depends(get_db)):
    cfg_q = await db.execute(
        select(ScraperConfig).where(ScraperConfig.source_id == source_id)
    )
    cfg = cfg_q.scalar()
    if cfg:
        cfg.next_run_at = datetime.utcnow()
        await db.commit()

    return RedirectResponse(url="/scrapers", status_code=303)
