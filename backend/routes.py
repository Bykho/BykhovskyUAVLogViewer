from fastapi import APIRouter, WebSocket
import asyncio
import json
from models.schema import SchemaRequest
from models.database import DataIngestionRequest, DataIngestionResponse
from services.schema_agent import process_schema
from services import db
from services.planner_agent import planner_agent


router = APIRouter()

# Global WebSocket connections for broadcasting plan updates
active_connections = []

@router.get("/chat")
async def chat():
    return {"message": "Hello from the backend/routes.py!"}

@router.post("/chat")
async def chat_post(request: dict):
    """Handle chat messages and return LLM responses"""
    user_message = request.get("message", "")
    
    if not user_message:
        return {"response": "Please provide a message."}
    
    # Use continuous conversation with tools
    response = await planner_agent.generate_response(user_message, broadcast_plan_update)
    
    return {"response": response}

@router.post("/schema")
async def schema(req: SchemaRequest):
    result = process_schema(req)
    return result.dict()

@router.post("/data")
async def ingest_data(req: DataIngestionRequest):
    try:
        print(f"Received data for {req.messageType}: {len(req.rows)} rows")
        rows_inserted = db.ingest_telemetry_data(req.messageType, req.rows)
        print(f"Successfully inserted {rows_inserted} rows for {req.messageType}")
        return DataIngestionResponse(
            status="ok",
            message=f"Successfully ingested {rows_inserted} rows for {req.messageType}",
            rowsInserted=rows_inserted
        ).dict()
    except Exception as e:
        print(f"Error in ingest_data: {e}")
        import traceback
        traceback.print_exc()
        raise

@router.websocket("/ws/plan")
async def websocket_plan(websocket: WebSocket):
    """WebSocket endpoint for live plan updates from Planner"""
    await websocket.accept()
    print("✅ WebSocket connection accepted")
    print(f"Total connections before: {len(active_connections)}")
    
    # Add this connection to the active connections list
    active_connections.append(websocket)
    print(f"Total connections after: {len(active_connections)}")
    print(f"Connection added: {websocket}")
    
    try:
        # Send current plan (if any) to client on connect
        plan = planner_agent.get_current_plan()
        await websocket.send_text(json.dumps(plan))
        print(f"Sent current plan to frontend: {len(plan)} steps")
        
        # Keep connection alive and listen for messages
        while True:
            try:
                # Wait for a message from the client (or timeout)
                message = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                print(f"Received message from client: {message}")
            except asyncio.TimeoutError:
                # Send a ping to keep connection alive
                await websocket.send_text(json.dumps({"type": "ping"}))
                continue
        
    except Exception as e:
        print(f"❌ WebSocket error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Remove this connection from active connections
        print(f"🧹 Cleaning up WebSocket connection")
        print(f"Total connections before cleanup: {len(active_connections)}")
        if websocket in active_connections:
            active_connections.remove(websocket)
            print(f"✅ Connection removed from active_connections")
        else:
            print(f"⚠️ Connection was not in active_connections list")
        print(f"Total connections after cleanup: {len(active_connections)}")
        print("🔌 Closing WebSocket connection")
        await websocket.close()

async def broadcast_plan_update(extra: dict = None):
    """Broadcast plan updates to all connected clients"""
    print(f"📡 broadcast_plan_update called with {len(active_connections)} active connections")
    
    if not active_connections:
        print("❌ No active WebSocket connections to broadcast to")
        return
    
    current_plan = planner_agent.get_current_plan()
    payload = {"plan": current_plan}
    
    if extra:
        payload.update(extra)
    
    print(f"📤 Broadcasting plan update to {len(active_connections)} clients")
    print(f"Payload being broadcast: {payload}")
    
    for i, connection in enumerate(active_connections[:]):  # Copy list to avoid modification during iteration
        try:
            print(f"📤 Sending to connection {i+1}/{len(active_connections)}")
            await connection.send_text(json.dumps(payload))
            print(f"✅ Successfully sent plan to client {i+1}")
        except Exception as e:
            print(f"❌ Error broadcasting to client {i+1}: {e}")
            # Remove dead connections
            if connection in active_connections:
                active_connections.remove(connection)
                print(f"🗑️ Removed dead connection {i+1}")