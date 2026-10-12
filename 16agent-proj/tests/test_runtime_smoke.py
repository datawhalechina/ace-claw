import asyncio
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch


class ClientSmokeTests(unittest.TestCase):
    def test_configured_client_completes_a_local_request(self):
        from math_agent_mcp.llm_client import build_openai_compatible_client

        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                body = json.dumps({
                    "id": "offline-completion", "object": "chat.completion", "created": 0,
                    "model": "offline-model", "choices": [{
                        "index": 0, "message": {"role": "assistant", "content": "4"},
                        "finish_reason": "stop",
                    }],
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict(os.environ, {
                "OPENAI_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
                "OPENAI_API_KEY": "offline-test", "MODEL_PRIMARY": "offline-model",
            }), patch("math_agent_mcp.llm_client._load_env_files"):
                client, model = build_openai_compatible_client()
                with client:
                    reply = client.chat.completions.create(
                        model=model, messages=[{"role": "user", "content": "2+2"}],
                    )
            self.assertEqual(reply.choices[0].message.content, "4")
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0][0], "/v1/chat/completions")
            self.assertEqual(requests[0][1]["model"], "offline-model")
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()


class McpSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_server_keeps_session_objects_between_tool_calls(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        async def exercise():
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "math_agent_mcp.mcp_server"],
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            async with (
                stdio_client(params) as (reader, writer),
                ClientSession(reader, writer) as session,
            ):
                await session.initialize()
                tools = {tool.name for tool in (await session.list_tools()).tools}
                self.assertTrue({"create_session", "define_expression", "sympy_canonicalise_object"} <= tools)

                async def call(name, arguments):
                    result = await session.call_tool(name, arguments)
                    self.assertFalse(result.isError, result)
                    return json.loads(result.content[0].text)

                created = await call("create_session", {})
                sid = created["session_id"]
                await call("define_expression", {
                    "name": "identity", "expr_str": "sin(x)**2 + cos(x)**2", "session_id": sid,
                })
                simplified = await call("sympy_canonicalise_object", {"name": "identity", "session_id": sid})
                self.assertEqual(simplified["output"], "1")
                objects = await call("list_session_objects", {"session_id": sid})
                self.assertEqual(objects["objects"]["identity"], "str")
                exported = await call("export_session_json", {"session_id": sid})
                self.assertEqual(exported["objects"]["identity"], "1")

        await asyncio.wait_for(exercise(), timeout=20)


if __name__ == "__main__":
    unittest.main()
