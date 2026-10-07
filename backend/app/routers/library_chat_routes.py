import ast
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import User, Video, VideoStatus
from app.services.llm import get_client, MODEL_NAME
from app.services.mcp_chroma import chroma_mcp

router = APIRouter(prefix="/library", tags=["library-chat"])

COLLECTION = "transcript_segments"
MIN_RELEVANCE_SCORE = 0.35
MAX_TOOL_ROUNDS = 3
MAX_VIDEOS = 5

SYSTEM_PROMPT = f"""You help learners find videos in a course library.
Use the chroma_query_documents tool to search the collection named "{COLLECTION}".
Each stored item is a short piece of a video transcript; its metadata holds video_id, start_time and end_time.
Call the tool with query_texts set to a list containing the learner's topic, and n_results between 5 and 8.
Then answer in two or three sentences, naming the videos that cover the topic and roughly where.
If the results do not clearly match the question, say you found nothing relevant. Never invent videos."""


class LibraryChatRequest(BaseModel):
    message: str


def _parse_query_result(text: str):
    """The tool returns the query result as text. Try JSON, then a Python literal."""
    for loader in (json.loads, ast.literal_eval):
        try:
            data = loader(text)
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return None


def _hits_from_result(data: dict, db: Session) -> list[dict]:
    ids = (data.get("ids") or [[]])[0]
    docs = (data.get("documents") or [[]])[0]
    metas = (data.get("metadatas") or [[]])[0]
    dists = (data.get("distances") or [[]])[0]

    hits = []
    for i in range(len(ids)):
        meta = (metas[i] if i < len(metas) else None) or {}
        distance = dists[i] if i < len(dists) else None
        score = 1 / (1 + distance) if distance is not None else None
        if score is not None and score < MIN_RELEVANCE_SCORE:
            continue
        hits.append({
            "video_id": meta.get("video_id"),
            "start_time": float(meta.get("start_time") or 0),
            "text": docs[i] if i < len(docs) else "",
            "score": round(score, 4) if score is not None else None,
        })

    # Only videos that are ready may be shown (Chroma also holds failed videos).
    video_uuids = []
    for h in hits:
        try:
            video_uuids.append(uuid.UUID(str(h["video_id"])))
        except (ValueError, TypeError):
            continue
    videos = {}
    if video_uuids:
        rows = db.query(Video).filter(Video.id.in_(video_uuids), Video.status == VideoStatus.ready).all()
        videos = {str(v.id): v for v in rows}

    hits = [h for h in hits if h["video_id"] in videos]
    hits.sort(key=lambda h: h["score"] if h["score"] is not None else 0, reverse=True)

    best_per_video = {}
    for h in hits:
        if h["video_id"] not in best_per_video:
            video = videos[h["video_id"]]
            best_per_video[h["video_id"]] = {**h, "title": video.title, "category": video.category}
    return list(best_per_video.values())[:MAX_VIDEOS]


@router.post("/chat")
def library_chat(
    payload: LibraryChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not chroma_mcp.is_ready():
        raise HTTPException(status_code=503, detail="The Chroma MCP server is not connected.")

    client = get_client()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": payload.message},
    ]
    tools = chroma_mcp.groq_tools()
    sources = []
    mcp_calls = []
    answer = ""

    try:
        for _ in range(MAX_TOOL_ROUNDS):
            response = client.chat.completions.create(
                model=MODEL_NAME, messages=messages, tools=tools, tool_choice="auto",
            )
            msg = response.choices[0].message

            if not msg.tool_calls:
                answer = msg.content or ""
                break

            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls
                ],
            })

            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}

                # The backend, not the model, decides these.
                query_texts = args.get("query_texts") or [payload.message]
                if isinstance(query_texts, str):
                    query_texts = [query_texts]
                args = {
                    "collection_name": COLLECTION,
                    "query_texts": [str(q) for q in query_texts],
                    "n_results": min(int(args.get("n_results") or 6), 10),
                    "include": ["documents", "metadatas", "distances"],
                }
                mcp_calls.append({"tool": tc.function.name, "arguments": args})

                try:
                    raw = chroma_mcp.call(tc.function.name, args)
                    parsed = _parse_query_result(raw)
                    if parsed is None:
                        print(f"[library chat] could not parse tool output: {raw[:300]}")
                        tool_text = "The search result could not be read."
                    else:
                        sources = _hits_from_result(parsed, db)
                        if sources:
                            tool_text = json.dumps([
                                {"video": s["title"], "category": s["category"],
                                 "at_seconds": s["start_time"], "text": s["text"]}
                                for s in sources
                            ])
                        else:
                            tool_text = "No relevant segments found."
                except Exception as e:
                    print(f"[library chat] tool call failed: {e}")
                    tool_text = "The search failed."

                messages.append({"role": "tool", "tool_call_id": tc.id, "content": tool_text})
        else:
            answer = "I couldn't finish that search. Please try again."
    except Exception as e:
        print(f"[library chat failed]: {e}")
        raise HTTPException(status_code=503, detail="Couldn't answer that right now. Please try again in a moment.")

    return {"answer": answer, "sources": sources, "mcp_calls": mcp_calls}