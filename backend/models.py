from pydantic import BaseModel
from typing import Dict, Any, List, Optional, Union



class ChatRequest(BaseModel):
    question: str
    digest: Dict[str, Any]

class ChatReply(BaseModel):
    reply: str

# New tool-calling models
class ToolCallRequest(BaseModel):
    sessionId: str
    messages: List[Dict[str, Any]]

class ToolCallReply(BaseModel):
    reply: str
    debug: Optional[Dict[str, Any]] = None

class ToolReplyRequest(BaseModel):
    call_id: str
    tool: str
    sessionId: str
    result: Dict[str, Any]

class ToolReplyResponse(BaseModel):
    status: str
    message: str
    debug: Optional[dict] = None

class MetricResult(BaseModel):
    name: str
    ok: bool
    value: Optional[Union[float, int]] = None
    units: Optional[str] = None
    t_ms: Optional[int] = None
    method: Optional[str] = None
    source: Optional[str] = None
    notes: Optional[str] = None

class SessionBundle(BaseModel):
    sessionId: str
    meta: Dict[str, Any]
    index: Dict[str, Any]
    downsample1Hz: Dict[str, Any]
    events: List[Dict[str, Any]]
    gaps: Optional[Dict[str, Any]] = None

class SessionResponse(BaseModel):
    sessionId: str
    status: str
    message: str