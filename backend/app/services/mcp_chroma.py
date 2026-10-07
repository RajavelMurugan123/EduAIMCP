import asyncio
import os
import sys
import threading

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()

CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = os.getenv("CHROMA_PORT", "8100")

# Read-only. The server also offers add, update and delete tools; they are
# never shown to the model and can never be called through this bridge.
ALLOWED_TOOLS = {"chroma_query_documents"}


def _chroma_mcp_command() -> str:
    """The chroma-mcp program installed in this virtual environment."""
    scripts_dir = os.path.dirname(sys.executable)
    for name in ("chroma-mcp.exe", "chroma-mcp"):
        candidate = os.path.join(scripts_dir, name)
        if os.path.exists(candidate):
            return candidate
    return "chroma-mcp"


class ChromaMCPBridge:
    """Runs the MCP client in its own thread and event loop, so it works the same
    under uvicorn --reload on Windows, and lets normal (sync) endpoints call it."""

    def __init__(self):
        self._loop = None
        self._thread = None
        self._ready = threading.Event()
        self._stop_event = None
        self._session = None
        self._tools = []
        self._error = None

    def start(self, timeout: int = 90):
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=timeout):
            raise RuntimeError("Timed out starting the Chroma MCP server")
        if self._error:
            raise RuntimeError(self._error)

    def _run(self):
        if sys.platform == "win32":
            self._loop = asyncio.ProactorEventLoop()
        else:
            self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main())

    async def _main(self):
        self._stop_event = asyncio.Event()
        try:
            params = StdioServerParameters(
                command=_chroma_mcp_command(),
                args=["--client-type", "http", "--host", CHROMA_HOST, "--port", CHROMA_PORT, "--ssl", "false"],
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    self._tools = [t for t in listed.tools if t.name in ALLOWED_TOOLS]
                    self._session = session
                    self._ready.set()
                    await self._stop_event.wait()
        except Exception as e:
            self._error = f"{type(e).__name__}: {e}"
            self._ready.set()
        finally:
            self._session = None

    def stop(self):
        if self._loop and self._stop_event:
            self._loop.call_soon_threadsafe(self._stop_event.set)

    def is_ready(self) -> bool:
        return self._session is not None

    def tool_names(self) -> list[str]:
        return [t.name for t in self._tools]

    def groq_tools(self) -> list[dict]:
        """The allowed MCP tools, described in the format Groq's function calling expects."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or "",
                    "parameters": t.inputSchema,
                },
            }
            for t in self._tools
        ]

    def call(self, name: str, arguments: dict, timeout: int = 60) -> str:
        if name not in ALLOWED_TOOLS:
            raise ValueError(f"Tool not allowed: {name}")
        if self._session is None:
            raise RuntimeError("Chroma MCP is not connected")
        future = asyncio.run_coroutine_threadsafe(self._session.call_tool(name, arguments), self._loop)
        result = future.result(timeout=timeout)
        return "\n".join(c.text for c in result.content if getattr(c, "type", None) == "text")


chroma_mcp = ChromaMCPBridge()