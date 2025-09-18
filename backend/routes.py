from fastapi import APIRouter, HTTPException
from typing import List
from models import SessionBundle, SessionResponse, ToolCallRequest, ToolCallReply, ToolReplyRequest, ToolReplyResponse
from services import (
    create_session_service, get_session_service, delete_session_service, list_sessions_service,
    chat_with_tools_service, tool_reply_batch_service, tool_reply_service, sessions
)

router = APIRouter()

@router.get("/health")
def health_check():
    return {"status": "healthy", "sessions": len(sessions)}

@router.post("/session", response_model=SessionResponse)
def create_session(bundle: SessionBundle):
    try:
        return create_session_service(bundle)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/session/{session_id}", response_model=SessionBundle)
def get_session(session_id: str):
    try:
        return get_session_service(session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.delete("/session/{session_id}", response_model=SessionResponse)
def delete_session(session_id: str):
    try:
        return delete_session_service(session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/sessions", response_model=List[str])
def list_sessions():
    return list_sessions_service()

@router.post("/chat-tools", response_model=ToolCallReply)
def chat_with_tools(req: ToolCallRequest):
    try:
        return chat_with_tools_service(req)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/tool-reply-batch", response_model=ToolReplyResponse)
def tool_reply_batch(req: dict):
    try:
        return tool_reply_batch_service(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/tool-reply", response_model=ToolReplyResponse)
def tool_reply(req: ToolReplyRequest):
    try:
        return tool_reply_service(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
