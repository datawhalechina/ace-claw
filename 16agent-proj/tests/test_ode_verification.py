import json
import unittest
from unittest.mock import patch

import httpx
from math_agent_mcp.mcp_server import sympy_dsolve_ode
from math_agent_mcp.mcp_tool_executor import MCPToolExecutor
from openai import OpenAI


class OdeVerificationTests(unittest.TestCase):
    def executor(self, arguments):
        requests = []

        def respond(request):
            payload = json.loads(request.content)
            requests.append(payload)
            message = {"role": "assistant", "content": "The tool returned the solution."}
            if len(requests) % 2:
                message["tool_calls"] = [{
                    "id": f"solve-{len(requests)}",
                    "type": "function",
                    "function": {"name": "sympy_dsolve_ode", "arguments": json.dumps(arguments)},
                }]
            return httpx.Response(200, json={
                "id": "offline-completion", "object": "chat.completion", "created": 0,
                "model": payload["model"],
                "choices": [{"index": 0, "message": message,
                             "finish_reason": "tool_calls" if "tool_calls" in message else "stop"}],
            })

        client = OpenAI(api_key="offline-test", base_url="https://offline.invalid/v1",
                        http_client=httpx.Client(transport=httpx.MockTransport(respond)))
        self.addCleanup(client.close)
        with patch("math_agent_mcp.mcp_tool_executor.load_dotenv"), patch(
            "math_agent_mcp.mcp_tool_executor.build_openai_compatible_client",
            return_value=(client, "primary-test"),
        ):
            executor = MCPToolExecutor(max_steps=3)
        executor.fallback_model = "fallback-test"
        return executor, requests

    def test_automatic_verification_preserves_custom_names_without_fallback(self):
        executor, requests = self.executor({
            "eq_str": "Eq(Derivative(f(t), t), f(t))", "y_name": "f", "x_name": "t",
        })
        result = executor.run("Solve this differential equation.")
        self.assertTrue(result["verify_result"]["verify"]["ok"])
        self.assertFalse(result["upgraded"])
        self.assertEqual([request["model"] for request in requests], ["primary-test"] * 2)
        verification = result["traces"][-1]
        self.assertEqual(verification["tool"], "sympy_verify_substitution")
        self.assertEqual(verification["args"]["y_name"], "f")
        self.assertEqual(verification["args"]["x_name"], "t")

    def test_manual_verification_preserves_custom_names(self):
        executor, requests = self.executor({
            "eq_str": "Eq(Derivative(f(t), t), f(t))", "y_name": "f", "x_name": "t",
        })
        result = executor.run("Solve this differential equation.", auto_upgrade=False)
        verification = executor.verify_last(result)
        self.assertTrue(verification["verify"]["verify"]["ok"])
        self.assertEqual(len(requests), 2, "manual verification must not call the model")

    def test_default_names_still_verify_automatically_and_manually(self):
        executor, requests = self.executor({"eq_str": "Eq(Derivative(y(x), x), y(x))"})
        result = executor.run("Solve this differential equation.")
        self.assertTrue(result["verify_result"]["verify"]["ok"])
        self.assertTrue(executor.verify_last(result)["verify"]["verify"]["ok"])
        self.assertFalse(result["upgraded"])
        self.assertEqual(len(requests), 2)

    def test_manual_verification_uses_the_last_solver_call_names(self):
        executor, _ = self.executor({})
        traces = []
        for name, variable in [("f", "t"), ("g", "s")]:
            args = {"eq_str": f"Eq(Derivative({name}({variable}), {variable}), {name}({variable}))",
                    "y_name": name, "x_name": variable}
            traces.append({"tool": "sympy_dsolve_ode", "args": args, "result": sympy_dsolve_ode(**args)})
        verification = executor.verify_last({"traces": traces})
        self.assertTrue(verification["verify"]["verify"]["ok"])
        self.assertEqual(verification["equation"], traces[-1]["result"]["equation"])

    def test_invalid_custom_solution_is_still_rejected(self):
        executor, _ = self.executor({})
        verification = executor.verify_last({"traces": [{
            "tool": "sympy_dsolve_ode", "args": {"y_name": "f", "x_name": "t"},
            "result": {"equation": "Eq(Derivative(f(t), t), f(t))", "solution": "Eq(f(t), t)"},
        }]})
        self.assertFalse(verification["verify"]["verify"]["ok"])

    def test_manual_verification_without_a_solver_result_is_unavailable(self):
        executor, _ = self.executor({})
        self.assertFalse(executor.verify_last({"traces": []})["ok"])


if __name__ == "__main__":
    unittest.main()
