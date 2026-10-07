import os

import chromadb
from dotenv import load_dotenv

load_dotenv()

CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8100"))
COLLECTION_NAME = "transcript_segments"

_client = None
_collection = None


def get_collection():
    """One collection holding a vector per transcript segment, across all videos.
    It lives in a Chroma server (started with `chroma run`), so the web app,
    the Celery worker and the Chroma MCP server all share it safely."""
    global _client, _collection
    if _collection is None:
        _client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
        _collection = _client.get_or_create_collection(name=COLLECTION_NAME)
    return _collection


def add_segment(segment_id: str, video_id: str, embedding: list[float], text: str, start_time: float, end_time: float):
    collection = get_collection()
    collection.add(
        ids=[segment_id],
        embeddings=[embedding],
        documents=[text],
        metadatas=[{"video_id": video_id, "start_time": start_time, "end_time": end_time}],
    )


def query_segments(query_embedding: list[float], video_id: str | None = None, top_k: int = 10):
    collection = get_collection()
    where_filter = {"video_id": video_id} if video_id else None
    return collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where=where_filter,
    )


def delete_video_segments(video_id: str):
    collection = get_collection()
    collection.delete(where={"video_id": video_id})