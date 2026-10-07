import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.database import Base, engine
from app.routers import (
    auth_routes, user_routes, video_routes, search_routes,
    chat_routes, quiz_routes, library_chat_routes,
)
from app.services.mcp_chroma import chroma_mcp

Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await asyncio.to_thread(chroma_mcp.start)
        print(f"[MCP] Chroma MCP server connected. Tools: {chroma_mcp.tool_names()}")
    except Exception as e:
        print(f"[MCP] Chroma MCP unavailable, library chat disabled: {e}")
    yield
    chroma_mcp.stop()


app = FastAPI(title="EduAI Platform API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_routes.router)
app.include_router(user_routes.router)
app.include_router(video_routes.router)
app.include_router(search_routes.router)
app.include_router(chat_routes.router)
app.include_router(quiz_routes.router)
app.include_router(library_chat_routes.router)

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")


@app.get("/health")
def health_check():
    return {"status": "ok"}