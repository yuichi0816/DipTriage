from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/manual")
async def get_manual(request: Request):
    return templates.TemplateResponse(request, "manual.html")
