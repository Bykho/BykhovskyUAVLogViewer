# Arena UAV Log Viewer Chatbot

## Overview
This is a minimal, working agentic chatbot for UAVLogViewer that demonstrates full-stack integration with AI-powered flight data analysis.

## Features
- **Real-time Flight Data Analysis**: Parses UAV logs and creates compact digests
- **AI-Powered Q&A**: Ask natural language questions about flight data
- **Structured Output**: Returns both human-readable answers and structured JSON data
- **Local Processing**: No raw logs sent to external services (privacy-focused)

## Quick Start

### 1. Start the Backend
```bash
cd /Users/nicodevelopment/Desktop/ArenaAI/UAVLogViewer
source backend/.venv/bin/activate
uvicorn backend.app:app --reload --host 127.0.0.1 --port 8000
```
Backend runs on: http://127.0.0.1:8000

### 2. Start the Frontend
```bash
npm run dev
```
Frontend runs on: http://localhost:8080

### 3. Test the Chatbot
1. Click "Open Sample" to load the VTOL flight log
2. Wait for processing to complete
3. Click the "Chat" tab in the sidebar
4. Ask questions like:
   - "What was the highest altitude?"
   - "Were there any critical errors?"
   - "How long was the flight?"
   - "Any GPS issues?"

## Architecture

### Backend (`backend/app.py`)
- **FastAPI** server with CORS enabled
- **OpenAI Integration** using GPT-4o-mini
- **Structured Prompts** for consistent flight data analysis
- **JSON Output** with metrics, events, and anomalies

### Frontend Components
- **`ChatPanel.vue`**: Chat interface with preset questions
- **`telemetryDigest.js`**: Converts global store data to compact digest
- **Global Store**: Centralized state management for flight data

### Data Flow
1. **Log Upload** → Worker parses → Global store populated
2. **User Question** → Digest built from store → Sent to backend
3. **AI Analysis** → Structured response → Displayed in chat

## Key Features for Arena Demo

### ✅ Full-Stack Integration
- Frontend Vue.js + Backend FastAPI + OpenAI API
- Real-time communication between components

### ✅ Agentic Behavior
- Stateful Q&A on parsed flight data
- Context-aware responses based on actual telemetry

### ✅ Privacy-Focused
- No raw logs sent to external services
- Compact digest (1Hz downsampling) keeps payloads small

### ✅ Structured Output
- Human-readable answers + JSON metadata
- Ready for metrics extraction and analysis

## Sample Questions to Try
- "What was the maximum altitude reached?"
- "Were there any critical system failures?"
- "How long did the flight last?"
- "Did the GPS signal drop at any point?"
- "What anomalies occurred during the flight?"

## Technical Details

### Digest Format
```json
{
  "alt": [{"t": 1234567890, "alt_m": 150.5}],
  "gps": [{"t": 1234567890, "fix": 3, "sats": 12}],
  "gpos": [{"t": 1234567890, "lat": 37.7749, "lon": -122.4194, "rel_alt_m": 100.0}],
  "events": [{"t": 1234567890, "severity": 2, "text": "GPS signal lost"}],
  "meta": {"start_ms": 1234567890, "end_ms": 1234567890}
}
```

### Response Format
- **Natural Language**: 2-6 sentence analysis
- **JSON Block**: Structured metrics, events, and anomalies
- **Citations**: Specific timestamps and data points

## Environment Setup
Make sure you have:
- `OPENAI_API_KEY` in your `backend/.env` file
- Python dependencies: `fastapi`, `uvicorn`, `openai`, `python-dotenv` (installed in `backend/.venv`)
- Node.js dependencies: Already installed via `npm install`

### File Structure
```
UAVLogViewer/
├── backend/
│   ├── .venv/          # Python virtual environment
│   ├── .env            # Backend environment variables (OPENAI_API_KEY)
│   └── app.py          # FastAPI backend
├── .env                # Frontend environment variables
└── src/
    ├── components/
    │   └── ChatPanel.vue
    └── tools/
        └── telemetryDigest.js
```

## Next Steps for Production
1. **Database Integration**: Store chat history and flight analysis
2. **Advanced Analytics**: More sophisticated anomaly detection
3. **Multi-Flight Comparison**: Compare multiple flights
4. **Export Features**: Download analysis reports
5. **Real-time Monitoring**: Live flight data streaming

This implementation proves the concept for Arena's requirements: parsing real UAV logs, creating intelligent summaries, and providing agentic Q&A capabilities with a clean UX.
