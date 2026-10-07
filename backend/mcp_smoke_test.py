"""Checks the Chroma MCP connection and shows the raw output format.

Run from the backend folder, venv active, Chroma server running:
    python mcp_smoke_test.py "glue code"
"""
import sys

from dotenv import load_dotenv

load_dotenv()

from app.services.mcp_chroma import chroma_mcp

query = sys.argv[1] if len(sys.argv) > 1 else "glue code"

chroma_mcp.start()
print("Tools offered to the model:", chroma_mcp.tool_names())

raw = chroma_mcp.call("chroma_query_documents", {
    "collection_name": "transcript_segments",
    "query_texts": [query],
    "n_results": 3,
    "include": ["documents", "metadatas", "distances"],
})
print("\nRaw result from the MCP tool:\n")
print(raw)

chroma_mcp.stop()