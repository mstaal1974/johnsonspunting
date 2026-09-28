import os

from fastapi import Request
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))


def money(v, signed=False):
    if v is None:
        return "-"
    s = f"${abs(v):,.2f}"
    if v < 0:
        return "-" + s
    return ("+" + s) if signed and v > 0 else s


def pct(v):
    return "-" if v is None else f"{v * 100:+.1f}%"


templates.env.filters["money"] = money
templates.env.filters["pct"] = pct


def is_admin(request: Request) -> bool:
    return bool(request.session.get("is_admin"))


def flash(request: Request, message: str, kind: str = "ok") -> None:
    request.session.setdefault("flash", []).append({"kind": kind, "text": message})


def render(request: Request, name: str, **ctx):
    ctx.setdefault("is_admin", is_admin(request))
    ctx["flashes"] = request.session.pop("flash", [])
    return templates.TemplateResponse(request, name, ctx)
