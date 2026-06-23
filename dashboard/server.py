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
                        for client in list(websockets):
                            if not client.closed:
                                await client.send_json(data)
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
