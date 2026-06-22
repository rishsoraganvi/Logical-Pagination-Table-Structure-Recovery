"""
Web interface router for serving the HTML frontend.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import os

router = APIRouter()

# Setup templates
templates_dir = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=templates_dir)


@router.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Serve the main upload interface."""
    return templates.TemplateResponse("index.html", {"request": request})


@router.get("/interface", response_class=HTMLResponse)
async def interface_redirect(request: Request):
    """Redirect /interface to root for convenience."""
    return templates.TemplateResponse("index.html", {"request": request})