"""Authenticated transport only; Orca still owns pairing, E2EE, editor and terminals."""
import asyncio
import base64
import json
import socket
import threading
import time

from fastapi import Depends, HTTPException, WebSocket
from sqlalchemy.orm import Session
from websockets.asyncio.client import connect

from .models import LoginSession, User, OrcaProject, Event
from .security import token_hash
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat()


def live_session(engine, cookie):
    with Session(engine) as db:
        row = db.get(LoginSession, token_hash(cookie))
        return bool(row and row.expires > time.time() and db.get(User, row.user_id))


def obtain_pairing():
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(25)
        connection.connect("/run/kosmos-orca-broker/pair.sock")
        connection.sendall(b"PAIR\n")
        result = bytearray()
        while True:
            chunk = connection.recv(8192)
            if not chunk:
                break
            result.extend(chunk)
            if len(result) > 150000:
                raise ValueError("Invalid broker response")
    parsed = json.loads(result)
    if not parsed.get("deviceToken") or not parsed.get("publicKeyB64"):
        raise ValueError("Broker unavailable")
    return parsed


def install_orca_routes(app, settings, authenticated):
    engine = app.state.engine
    app.state.orca_upstream = "ws://127.0.0.1:6768"
    launch_times = {}
    active = {}
    active_lock = threading.Lock()

    def revoke(cookie):
        with active_lock:
            for event, loop in active.get(token_hash(cookie), []):
                loop.call_soon_threadsafe(event.set)
    app.state.orca_revoke = revoke

    @app.get("/api/orca/authorize", status_code=204)
    def authorize(user=Depends(authenticated)):
        return None

    @app.post("/api/projects/{project_id}/orca")
    def launch(project_id: int, user=Depends(authenticated)):
        with Session(engine) as db:
            mapping = db.get(OrcaProject, project_id)
            if not mapping:
                raise HTTPException(409, "This project has no registered Orca workspace")
            if time.monotonic() - launch_times.get(user["username"], -1000) < 10:
                raise HTTPException(429, "Wait ten seconds before pairing again")
            launch_times[user["username"]] = time.monotonic()
            try:
                offer = obtain_pairing()
            except Exception:
                raise HTTPException(503, "Orca pairing service unavailable")
            scheme = "wss" if settings.origin.startswith("https://") else "ws"
            offer["endpoint"] = scheme + settings.origin[settings.origin.index(":"):] + "/orca/runtime"
            code = base64.urlsafe_b64encode(json.dumps(offer).encode()).decode().rstrip("=")
            label = mapping.label
            db.add(Event(kind="orca-access", state="ok", created=now(), summary=f"{user['username']} opened registered workspace {mapping.label}; shared runtime access"))
            db.commit()
        return {"url": "/orca/web-index.html#pairing=" + code, "workspace": label}

    @app.get("/api/admin/authorize", status_code=204)
    def admin_authorize(user=Depends(authenticated)):
        if user["role"] != "admin":
            raise HTTPException(403, "Administrator required")
        return None

    @app.websocket("/orca/runtime")
    async def runtime(browser: WebSocket):
        cookie = browser.cookies.get("kosmos_session", "")
        async def valid():
            try:
                return await asyncio.wait_for(asyncio.to_thread(live_session, engine, cookie), timeout=1)
            except Exception:
                return False
        if browser.headers.get("origin") != settings.origin or not await valid():
            await browser.close(code=1008)
            return
        ended = asyncio.Event()
        identity = token_hash(cookie)
        entry = (ended, asyncio.get_running_loop())
        with active_lock:
            active.setdefault(identity, []).append(entry)
        await browser.accept()
        tasks = []

        async def transport():
            async with connect(app.state.orca_upstream + "?orca-client=web", proxy=None, origin=settings.origin,
                               max_size=16 * 1024 * 1024, max_queue=8, open_timeout=5, close_timeout=2) as upstream:
                async def outgoing():
                    while True:
                        message = await browser.receive()
                        if message["type"] == "websocket.disconnect":
                            return
                        await upstream.send(message.get("bytes") if message.get("bytes") is not None else message.get("text", ""))

                async def incoming():
                    async for message in upstream:
                        if isinstance(message, bytes):
                            await browser.send_bytes(message)
                        else:
                            await browser.send_text(message)

                forwarding = [asyncio.create_task(outgoing()), asyncio.create_task(incoming())]
                try:
                    done, _ = await asyncio.wait(forwarding, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        task.result()
                finally:
                    for task in forwarding:
                        task.cancel()
                    await asyncio.gather(*forwarding, return_exceptions=True)

        async def revocation():
            while True:
                try:
                    await asyncio.wait_for(ended.wait(), timeout=0.5)
                except TimeoutError:
                    pass
                if ended.is_set() or not await valid():
                    await browser.close(code=1008, reason="Portal session ended")
                    return

        try:
            tasks = [asyncio.create_task(transport()), asyncio.create_task(revocation())]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except Exception:
            # Do not log frames, pairing data or cookies.
            pass
        finally:
            with active_lock:
                active[identity].remove(entry)
                if not active[identity]:
                    del active[identity]
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            try:
                await browser.close(code=1011)
            except RuntimeError:
                pass
