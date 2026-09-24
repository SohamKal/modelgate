"""Gateway application entry point for the foundation scaffold."""

from fastapi import FastAPI
from prometheus_client import make_asgi_app

app = FastAPI(title="Modelgate", version="0.0.0")
app.mount("/metrics", make_asgi_app())


@app.get("/health/live")
async def liveness() -> dict[str, str]:
    """Report that the gateway process is serving requests."""
    return {"status": "ok"}
