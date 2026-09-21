"""Standalone background companion server for PersonaStudio."""
from __future__ import annotations

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.api import router

app = FastAPI(title="Hermes PersonaStudio Backend", version="0.1.0-mvp")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=17495)
