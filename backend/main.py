"""AI-Genesis entry point — FastAPI application stub.

This is a minimal stub for Docker build verification.
Full implementation will be done in Phase 1 (Task T-021).
"""

from __future__ import annotations

from fastapi import FastAPI

# Create minimal FastAPI app for build verification
app = FastAPI(
    title="AI-Genesis",
    description="Autonomous evolutionary sandbox powered by LLM",
    version="0.1.0",
)


@app.get("/")
async def root() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok", "message": "AI-Genesis Core — Ready"}


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check for Docker."""
    return {"status": "healthy"}
