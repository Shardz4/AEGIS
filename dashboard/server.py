import os
import json
import logging
from aiohttp import web

# Configure logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aegis_server")

# Keep track of active WebSocket connections
websockets = set()

async def ws_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    logger.info(f"Dashboard client connected: {request.remote}")
    websockets.add(ws)

    try:
        # Keep connection open and handle incoming messages
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    logger.info(f"Received websocket message: {data}")
                    
                    # If client requests a demo scenario, broadcast the trigger
                    if data.get("type") == "start_demo":
                        logger.info("Demo scenario start request received. Broadcasting to all clients.")
                        current_dir = os.path.dirname(os.path.abspath(__file__))
                        workspace_dir = os.path.dirname(current_dir)
                        override_path = os.path.join(workspace_dir, "control_override.json")
                        if os.path.exists(override_path):
                            try:
                                os.remove(override_path)
                                logger.info(f"Cleaned up {override_path} on demo start")
                            except Exception as ex:
                                logger.error(f"Error removing {override_path}: {ex}")
                        
                        for client in list(websockets):
                            if not client.closed:
                                await client.send_json(data)
                                
                    elif data.get("type") == "mitigate":
                        action = data.get("action")
                        current_dir = os.path.dirname(os.path.abspath(__file__))
                        workspace_dir = os.path.dirname(current_dir)
                        override_path = os.path.join(workspace_dir, "control_override.json")
                        
                        # Load existing overrides
                        overrides = {"isolated_zones": [], "cancelled_permits": []}
                        if os.path.exists(override_path):
                            try:
                                with open(override_path, "r", encoding="utf-8") as f:
                                    content = f.read().strip()
                                    if content:
                                        overrides = json.loads(content)
                            except Exception as ex:
                                logger.error(f"Error reading {override_path}: {ex}")
                                
                        # Update overrides based on action
                        updated = False
                        if action == "cancel_permit":
                            p_id = data.get("permit_id")
                            if p_id and p_id not in overrides.setdefault("cancelled_permits", []):
                                overrides["cancelled_permits"].append(p_id)
                                updated = True
                        elif action == "isolate_feed":
                            z_id = data.get("zone_id")
                            if z_id is not None:
                                try:
                                    z_id = int(z_id)
                                    if z_id not in overrides.setdefault("isolated_zones", []):
                                        overrides["isolated_zones"].append(z_id)
                                        updated = True
                                except ValueError:
                                    pass
                        elif action == "recalibrate":
                            s_id = data.get("sensor_id")
                            if s_id is not None:
                                try:
                                    s_id = int(s_id)
                                    if s_id not in overrides.setdefault("recalibrated_sensors", []):
                                        overrides["recalibrated_sensors"].append(s_id)
                                        updated = True
                                except ValueError:
                                    pass
                        elif action == "ack_cctv":
                            z_id = data.get("zone_id")
                            s_id = data.get("sensor_id")
                            if z_id is not None and s_id is not None:
                                try:
                                    z_id = int(z_id)
                                    s_id = int(s_id)
                                    event_key = f"{z_id}:{s_id}"
                                    if event_key not in overrides.setdefault("acked_cctv_events", []):
                                        overrides["acked_cctv_events"].append(event_key)
                                        updated = True
                                except ValueError:
                                    pass
                                    
                        if updated:
                            try:
                                with open(override_path, "w", encoding="utf-8") as f:
                                    json.dump(overrides, f, indent=2)
                                logger.info(f"Updated control overrides: {overrides}")
                            except Exception as ex:
                                logger.error(f"Error writing {override_path}: {ex}")
                                
                        # Broadcast mitigated event
                        response_data = {
                            "type": "mitigated",
                            "action": action,
                            "permit_id": data.get("permit_id"),
                            "zone_id": data.get("zone_id"),
                            "sensor_id": data.get("sensor_id")
                        }
                        for client in list(websockets):
                            if not client.closed:
                                await client.send_json(response_data)
                except Exception as ex:
                    logger.error(f"Error parsing ws message: {ex}")
            elif msg.type == web.WSMsgType.ERROR:
                logger.error(f"WebSocket connection closed with exception: {ws.exception()}")
    finally:
        websockets.remove(ws)
        logger.info(f"Dashboard client disconnected: {request.remote}")
        
    return ws

async def api_update_handler(request):
    try:
        data = await request.json()
        updates = data if isinstance(data, list) else [data]
        
        # Broadcast each update to all connected WebSockets
        sent_count = 0
        for ws in list(websockets):
            if not ws.closed:
                for update in updates:
                    await ws.send_json(update)
                    sent_count += 1
                    
        return web.Response(text=f"Broadcasted {len(updates)} update(s) to {len(websockets)} client(s)")
    except Exception as e:
        logger.error(f"Error handling update POST: {e}")
        return web.Response(text=str(e), status=400)

def init_app():
    app = web.Application()
    
    # Routes
    app.router.add_get('/ws', ws_handler)
    app.router.add_post('/api/update', api_update_handler)
    
    # Serve static files
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Serve index.html as root
    async def index(request):
        index_path = os.path.join(current_dir, 'index.html')
        if os.path.exists(index_path):
            return web.FileResponse(index_path)
        return web.Response(text="Dashboard index.html not found.", status=404)
        
    app.router.add_get('/', index)
    
    # Make sure subdirectories exist before registering static endpoints
    for sub in ['css', 'js', 'assets']:
        path = os.path.join(current_dir, sub)
        os.makedirs(path, exist_ok=True)
        app.router.add_static(f'/{sub}/', path=path, name=sub)
        
    return app

if __name__ == '__main__':
    logger.info("Starting AEGIS Dashboard Server on http://localhost:8080 ...")
    app = init_app()
    web.run_app(app, host='localhost', port=8080)
