"""Start an ephemeral offline gateway and send one actual HTTP request."""

import asyncio
import json

import httpx
import uvicorn

from app.core.settings import Settings
from app.main import create_app


async def main() -> None:
    # Explicit fake configuration makes this command safe even if real settings are exported.
    settings = Settings(_env_file=".env.example", stable_release="fake")  # type: ignore[call-arg]
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(settings, ephemeral=True),
            host="127.0.0.1",
            port=0,
            access_log=False,
            log_config=None,
            log_level="warning",
        )
    )
    task = asyncio.create_task(server.serve())
    try:
        async with asyncio.timeout(5):
            while not server.started:
                if task.done():
                    await task
                    raise RuntimeError("Gateway did not start.")
                await asyncio.sleep(0.01)
        port = server.servers[0].sockets[0].getsockname()[1]
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}", trust_env=False
        ) as client:
            response = await client.post(
                "/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.client_api_key.get_secret_value()}"},
                json={"messages": [{"role": "user", "content": "Offline smoke request."}]},
            )
            response.raise_for_status()
            print(json.dumps(response.json(), indent=2))
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=5)


if __name__ == "__main__":
    asyncio.run(main())
