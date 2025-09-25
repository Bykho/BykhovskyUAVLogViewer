from fastapi import APIRouter
from models.schema import SchemaRequest
from models.database import DataIngestionRequest, DataIngestionResponse
from services.schema_agent import process_schema
from services import db


router = APIRouter()

@router.get("/chat")
async def chat():
    return {"message": "Hello from the backend/routes.py!"}

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