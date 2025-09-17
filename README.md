# UAV Log Viewer

![log seeking](preview.gif "Logo Title Text 1")

 This is a Javascript based log viewer for Mavlink telemetry and dataflash logs.
 [Live demo here](http://plot.ardupilot.org).

## Quick Start (local, no Docker)

```bash
# 1) Clone + submodules
git clone <your-fork-url>
cd UAVLogViewer
git submodule update --init --recursive

# 2) Create env files from examples and paste your keys
cp .env.example .env
cp backend/.env.example backend/.env

# 3) Backend (terminal 1)
python3 -m venv backend/.venv
source backend/.venv/bin/activate  # Windows: backend\.venv\Scripts\activate
pip install -r backend/requirements.txt
uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload

# 4) Frontend (terminal 2)
npm install
# Optional:
# export VUE_APP_CESIUM_TOKEN=<your_cesium_token>
# export VUE_APP_GROQ_API_KEY=<your_groq_key>
npm run dev

# App: http://localhost:8080
```

Notes:
- The frontend calls the backend at `http://127.0.0.1:8000` (wired in code).
- Use "Open Sample" to load the bundled VTOL log quickly, or upload your own `.tlog`/`.bin`.

## Build Setup

``` bash
# initialize submodules
git submodule update --init --recursive

# install dependencies
npm install

# enter Cesium token
export VUE_APP_CESIUM_TOKEN=<your token>

# serve with hot reload at localhost:8080
npm run dev

# build for production with minification
npm run build

# run unit tests
npm run unit

# run e2e tests
npm run e2e

# run all tests
npm test
```

# Docker

run the prebuilt docker image:

``` bash
docker run -p 8080:8080 -d ghcr.io/ardupilot/uavlogviewer:latest

```

or build the docker file locally:

``` bash

# Build Docker Image
docker build -t <your username>/uavlogviewer .

# Run Docker Image
docker run -e VUE_APP_CESIUM_TOKEN=<Your cesium ion token> -it -p 8080:8080 -v ${PWD}:/usr/src/app <your username>/uavlogviewer

# Navigate to localhost:8080 in your web browser

# changes should automatically be applied to the viewer

```
