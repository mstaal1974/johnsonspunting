# Vercel entry point: serves the FastAPI app as a Python serverless function.
import os
import sys
import traceback

# Vercel doesn't guarantee the project root is importable from api/
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    from app.main import app  # noqa: F401
except Exception:
    # Show why the app couldn't start instead of Vercel's generic
    # FUNCTION_INVOCATION_FAILED page (it's also printed to the Vercel logs).
    _error = traceback.format_exc()
    print(_error, file=sys.stderr)

    async def app(scope, receive, send):
        if scope["type"] != "http":
            return
        body = ("Johnsons Punt Club couldn't start.\n\n" + _error).encode()
        await send({"type": "http.response.start", "status": 500,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
        await send({"type": "http.response.body", "body": body})
