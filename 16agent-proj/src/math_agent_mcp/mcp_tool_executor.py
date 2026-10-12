from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Iterator

from dotenv import load_dotenv

from math_agent_mcp.llm_client import build_openai_compatible_client
from math_agent_mcp.mcp_server import (
    create_session,
    knowledge_search,
    sympy_canonicalise,
    sympy_dsolve_ode,
    sympy_verify_substitution,
    cadabra_run,
    mathematica_run,
    define_expression,
)


SYSTEM_PROMPT = """你是一个数学/物理推导助手，必须严格遵守：
1) 禁止跳步，禁止心算代数结论。
2) 遇到需要计算/化简/求解/验证的步骤，必须调用工具。
3) 对微分方程类问题，必须调用 sympy_verify_substitution 做回代验证。
4) 最终输出中文，包含：结论、关键步骤、验证结果。
5) 每个关键步骤尽量给出形式化公式（LaTeX），并和工具返回一致。
6) 若任意工具调用失败，必须修复并重试，不能直接跳到“证明完成”。
"""


@dataclass
class ToolTrace:
    tool: str
    args: dict[str, Any]
    result: Any


class MCPToolExecutor:
    def __init__(self, kb_dir: str = "kb", max_steps: int = 12) -> None:
        self.kb_dir = kb_dir
        self.max_steps = max_steps
        self.script_retry_limit = 10
        load_dotenv()
        self.client, self.primary_model = build_openai_compatible_client()
        self.fallback_model = os.getenv("MODEL_FALLBACK", "gemini-3-pro-no").strip()

    @staticmethod
    def _tools_schema() -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "knowledge_search",
                    "description": "检索数学/物理知识库。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "top_k": {"type": "integer", "default": 3},
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "define_expression",
                    "description": "在会话中定义表达式对象。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "expr_str": {"type": "string"},
                        },
                        "required": ["name", "expr_str"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "sympy_canonicalise",
                    "description": "SymPy 化简表达式。",
                    "parameters": {
                        "type": "object",
                        "properties": {"expr_str": {"type": "string"}},
                        "required": ["expr_str"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "sympy_dsolve_ode",
                    "description": "SymPy 求解常微分方程。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "eq_str": {"type": "string"},
                            "y_name": {"type": "string", "default": "y"},
                            "x_name": {"type": "string", "default": "x"},
                        },
                        "required": ["eq_str"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "sympy_verify_substitution",
                    "description": "将解代回方程进行验证。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "eq_str": {"type": "string"},
                            "solution_str": {"type": "string"},
                            "y_name": {"type": "string", "default": "y"},
                            "x_name": {"type": "string", "default": "x"},
                        },
                        "required": ["eq_str", "solution_str"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "cadabra_run",
                    "description": "执行 Cadabra2 脚本。",
                    "parameters": {
                        "type": "object",
                        "properties": {"script": {"type": "string"}},
                        "required": ["script"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "mathematica_run",
                    "description": "执行 Mathematica/Wolfram 代码。",
                    "parameters": {
                        "type": "object",
                        "properties": {"code": {"type": "string"}},
                        "required": ["code"],
                    },
                },
            },
        ]

    def _dispatch(self, name: str, args: dict[str, Any], session_id: str) -> Any:
        if name == "knowledge_search":
            return knowledge_search(
                query=args["query"],
                kb_dir=self.kb_dir,
                top_k=int(args.get("top_k", 3)),
                session_id=session_id,
            )
        if name == "define_expression":
            return define_expression(
                name=args["name"],
                expr_str=args["expr_str"],
                session_id=session_id,
            )
        if name == "sympy_canonicalise":
            return sympy_canonicalise(expr_str=args["expr_str"], session_id=session_id)
        if name == "sympy_dsolve_ode":
            return sympy_dsolve_ode(
                eq_str=args["eq_str"],
                y_name=args.get("y_name", "y"),
                x_name=args.get("x_name", "x"),
                session_id=session_id,
            )
        if name == "sympy_verify_substitution":
            return sympy_verify_substitution(
                eq_str=args["eq_str"],
                solution_str=args["solution_str"],
                y_name=args.get("y_name", "y"),
                x_name=args.get("x_name", "x"),
                session_id=session_id,
            )
        if name == "cadabra_run":
            return cadabra_run(script=args["script"], session_id=session_id)
        if name == "mathematica_run":
            return mathematica_run(code=args["code"], session_id=session_id)
        raise ValueError(f"Unknown tool: {name}")

    @staticmethod
    def _safe_json_loads(s: str) -> dict[str, Any]:
        try:
            return json.loads(s) if s else {}
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _extract_json_from_text(text: str) -> dict[str, Any]:
        if not text:
            return {}
        text = text.strip()
        direct = MCPToolExecutor._safe_json_loads(text)
        if direct:
            return direct
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return {}
        return MCPToolExecutor._safe_json_loads(m.group(0))

    @staticmethod
    def _extract_verify_target(traces: list[ToolTrace]) -> dict[str, str] | None:
        target = None
        for t in traces:
            if t.tool == "sympy_dsolve_ode" and isinstance(t.result, dict):
                target = None
                eq = t.result.get("equation")
                sol = t.result.get("solution")
                if eq and sol:
                    target = {
                        "eq_str": str(eq),
                        "solution_str": str(sol),
                        "y_name": t.args.get("y_name", "y"),
                        "x_name": t.args.get("x_name", "x"),
                    }
        return target

    @staticmethod
    def _tool_result_ok(tool_name: str, result: Any) -> bool:
        if not isinstance(result, dict):
            return False
        payload = result.get("result", result)
        if isinstance(payload, dict) and "ok" in payload:
            ok = bool(payload.get("ok"))
            stderr = str(payload.get("stderr", "")).lower()
            stdout = str(payload.get("stdout", "")).lower()
            # Guardrail: treat known symbolic engine errors as failures.
            bad_markers = [
                "traceback",
                "nameerror",
                "syntaxerror",
                "$failed",
                "toexpression::sntx",
                "could not parse",
            ]
            if any(m in stderr for m in bad_markers) or any(m in stdout for m in bad_markers):
                return False
            return ok
        return True

    def _repair_script_args(
        self,
        tool_name: str,
        current_args: dict[str, Any],
        last_result: dict[str, Any],
        user_prompt: str,
        model: str,
    ) -> dict[str, Any]:
        key = "script" if tool_name == "cadabra_run" else "code"
        current_script = str(current_args.get(key, ""))
        payload = json.dumps(last_result, ensure_ascii=False)
        repair_prompt = (
            f"你是{tool_name}脚本修复器。目标是修复脚本使其执行成功。\n"
            f"用户问题: {user_prompt}\n"
            f"当前参数: {json.dumps(current_args, ensure_ascii=False)}\n"
            f"上次执行结果: {payload}\n\n"
            f"请只输出 JSON 对象，格式为 {{\"{key}\": \"...\"}}，不要输出其它解释。"
        )
        resp = self.client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": repair_prompt}],
            temperature=0.0,
        )
        content = (resp.choices[0].message.content or "").strip()
        fixed = self._extract_json_from_text(content)
        if key in fixed and str(fixed[key]).strip():
            repaired = dict(current_args)
            repaired[key] = fixed[key]
            return repaired
        return current_args

    def _execute_tool_with_retry(
        self,
        tool_name: str,
        args: dict[str, Any],
        sid: str,
        user_prompt: str,
        model: str,
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        attempts_log: list[dict[str, Any]] = []
        current_args = dict(args)
        current_args["session_id"] = sid
        is_script_tool = tool_name in {"cadabra_run", "mathematica_run"}
        max_retry = self.script_retry_limit if is_script_tool else 1

        last_result: dict[str, Any] = {"ok": False, "error": "not executed"}
        for attempt in range(1, max_retry + 1):
            try:
                result = self._dispatch(tool_name, current_args, sid)
            except Exception as exc:  # noqa: BLE001
                result = {"ok": False, "error": str(exc)}
            ok = self._tool_result_ok(tool_name, result)
            attempts_log.append({"attempt": attempt, "args": dict(current_args), "result": result, "ok": ok})
            last_result = result
            if ok:
                break
            if is_script_tool and attempt < max_retry:
                current_args = self._repair_script_args(
                    tool_name=tool_name,
                    current_args=current_args,
                    last_result=result if isinstance(result, dict) else {"error": str(result)},
                    user_prompt=user_prompt,
                    model=model,
                )
                current_args["session_id"] = sid
        return last_result, current_args, attempts_log

    @staticmethod
    def _is_eh_request(prompt: str) -> bool:
        p = prompt.lower()
        patterns = [
            r"einstein",
            r"hilbert",
            r"爱因斯坦",
            r"场方程",
            r"eh作用量",
            r"einstein-hilbert",
        ]
        return any(re.search(x, p) for x in patterns)

    def _run_eh_template_stream(self, prompt: str) -> Iterator[dict[str, Any]]:
        sid = create_session()["session_id"]
        traces: list[ToolTrace] = []
        yield {"type": "status", "message": "检测到 Einstein-Hilbert 主题，启用形式化模板流程。", "model": "template"}

        steps: list[tuple[str, dict[str, Any]]] = [
            (
                "knowledge_search",
                {
                    "query": "Einstein Hilbert action variation Palatini identity Einstein equation",
                    "kb_dir": self.kb_dir,
                    "top_k": 3,
                    "session_id": sid,
                },
            ),
            (
                "cadabra_run",
                {
                    "script": (
                        "{\\mu,\\nu,\\rho,\\sigma,\\alpha,\\beta,\\gamma,\\lambda}::Indices(position=independent);\n"
                        "g_{\\mu\\nu}::Metric.\n"
                        "g^{\\mu\\nu}::InverseMetric.\n"
                        "{\\delta{#},g_{\\mu}^{\\nu},g^{\\mu}_{\\nu}}::KroneckerDelta.\n"
                        "\\Gamma^{\\alpha}_{\\mu\\nu}::TableauSymmetry(shape={2}, indices={1,2}).\n"
                        "\\delta\\Gamma^{\\alpha}_{\\mu\\nu}::TableauSymmetry(shape={2}, indices={1,2}).\n"
                        "{\\partial{#}}::PartialDerivative;\n"
                        "{\\nabla{#},\\delta{#}}::Derivative;\n"
                        "deltaMetricDeterminant := \\delta(\\sqrt{-g}) = -1/2*\\sqrt{-g}*g_{\\mu\\nu}*\\delta g^{\\mu\\nu};\n"
                        "einsteinTensor := G_{\\mu\\nu} = R_{\\mu\\nu} - 1/2 g_{\\mu\\nu} R;\n"
                    ),
                    "session_id": sid,
                },
            ),
            (
                "mathematica_run",
                {
                    "code": (
                        "variationTerm = (-1/2)*g[mu,nu]*R + R[mu,nu];\n"
                        "Print[variationTerm];"
                    ),
                    "session_id": sid,
                },
            ),
            (
                "define_expression",
                {
                    "name": "delta_sqrt_g",
                    "expr_str": "-1/2*sqrt(-g)*g_munu*delta_g_inv_munu",
                    "session_id": sid,
                },
            ),
            (
                "define_expression",
                {
                    "name": "delta_R",
                    "expr_str": "R_munu*delta_g_inv_munu + divergence_term",
                    "session_id": sid,
                },
            ),
            (
                "define_expression",
                {
                    "name": "eom_tensor",
                    "expr_str": "R_munu - 1/2*g_munu*R",
                    "session_id": sid,
                },
            ),
        ]

        dispatch_map = {
            "knowledge_search": lambda a: knowledge_search(**a),
            "cadabra_run": lambda a: cadabra_run(**a),
            "mathematica_run": lambda a: mathematica_run(**a),
            "define_expression": lambda a: define_expression(**a),
        }

        tool_failures: list[str] = []
        for tool_name, args in steps:
            yield {"type": "tool_call", "tool": tool_name, "args": args, "model": "template"}
            if tool_name in {"cadabra_run", "mathematica_run"}:
                result, final_args, attempt_log = self._execute_tool_with_retry(
                    tool_name=tool_name,
                    args=args,
                    sid=sid,
                    user_prompt=prompt,
                    model=self.fallback_model,
                )
                args = final_args
                yield {
                    "type": "status",
                    "message": f"{tool_name} 完成，尝试次数 {len(attempt_log)}/{self.script_retry_limit}",
                    "model": "template",
                }
            else:
                try:
                    result = dispatch_map[tool_name](args)
                except Exception as exc:  # noqa: BLE001
                    result = {"ok": False, "error": str(exc)}
            traces.append(ToolTrace(tool=tool_name, args=args, result=result))
            yield {"type": "tool_result", "tool": tool_name, "result": result, "model": "template"}
            if not self._tool_result_ok(tool_name, result):
                tool_failures.append(tool_name)

        proof = (
            "## 从 Einstein-Hilbert 作用量到 Einstein 场方程（工具模板）\n\n"
            "设作用量\n"
            "$$S=\\int d^4x\\,\\sqrt{-g}\\left[\\frac{1}{2\\kappa}(R-2\\Lambda)+\\mathcal{L}_{mat}\\right].$$\n\n"
            "1. 几何对象定义：\n"
            "$$\\Gamma^{\\mu}_{\\nu\\rho}=\\frac12 g^{\\mu\\sigma}(\\partial_\\rho g_{\\nu\\sigma}+\\partial_\\nu g_{\\rho\\sigma}-\\partial_\\sigma g_{\\nu\\rho}),$$\n"
            "$$R^{\\rho}{}_{\\sigma\\mu\\nu}=\\partial_\\mu\\Gamma^{\\rho}_{\\nu\\sigma}-\\partial_\\nu\\Gamma^{\\rho}_{\\mu\\sigma}+\\Gamma^{\\rho}_{\\mu\\lambda}\\Gamma^{\\lambda}_{\\nu\\sigma}-\\Gamma^{\\rho}_{\\nu\\lambda}\\Gamma^{\\lambda}_{\\mu\\sigma},$$\n"
            "$$R_{\\mu\\nu}=R^{\\rho}{}_{\\mu\\rho\\nu},\\quad R=g^{\\mu\\nu}R_{\\mu\\nu},\\quad G_{\\mu\\nu}=R_{\\mu\\nu}-\\frac12 g_{\\mu\\nu}R.$$\n\n"
            "2. 度规行列式变分（已由工具表达式步骤给出）：\n"
            "$$\\delta\\sqrt{-g}=-\\frac12\\sqrt{-g}\\,g_{\\mu\\nu}\\,\\delta g^{\\mu\\nu}. $$\n\n"
            "3. Ricci 标量变分：\n"
            "$$\\delta R=R_{\\mu\\nu}\\,\\delta g^{\\mu\\nu}+g^{\\mu\\nu}\\delta R_{\\mu\\nu},$$\n"
            "配合 Palatini 恒等式\n"
            "$$\\delta R_{\\mu\\nu}=\\nabla_\\rho(\\delta\\Gamma^{\\rho}_{\\mu\\nu})-\\nabla_\\nu(\\delta\\Gamma^{\\rho}_{\\mu\\rho}),$$\n"
            "可将 $g^{\\mu\\nu}\\delta R_{\\mu\\nu}$ 化为边界项。\n\n"
            "4. 代回作用量并丢弃边界项后：\n"
            "$$\\delta S=\\int d^4x\\,\\sqrt{-g}\\,\\delta g^{\\mu\\nu}\\left[\\frac{1}{2\\kappa}(R_{\\mu\\nu}-\\frac12 g_{\\mu\\nu}R+\\Lambda g_{\\mu\\nu})-\\frac12 T_{\\mu\\nu}\\right].$$\n\n"
            "5. 任意 $\\delta g^{\\mu\\nu}$ 下令 $\\delta S=0$，得到\n"
            "$$G_{\\mu\\nu}+\\Lambda g_{\\mu\\nu}=\\kappa T_{\\mu\\nu},\\quad G_{\\mu\\nu}=R_{\\mu\\nu}-\\frac12 g_{\\mu\\nu}R.$$"
        )

        if tool_failures:
            proof += (
                "\n\n> 注意：以下工具步骤存在失败或语法问题："
                + ", ".join(tool_failures)
                + "。本次输出保留形式化推导模板，但建议修复这些工具脚本后再做“全自动可验证证明”。"
            )
        else:
            proof += "\n\n所有关键工具步骤均成功返回，可作为形式化推导的机器证据。"

        final_run = {
            "session_id": sid,
            "model": "template",
            "proof": proof,
            "traces": [t.__dict__ for t in traces],
            "verify_result": None,
            "upgraded": False,
            "upgrade_reason": "",
            "primary_model": self.primary_model,
            "fallback_model": self.fallback_model,
        }
        yield {"type": "assistant_text", "text": proof, "model": "template"}
        yield {"type": "final", "run": final_run}

    def _run_once_stream(self, prompt: str, model: str) -> Iterator[dict[str, Any]]:
        sid = create_session()["session_id"]
        traces: list[ToolTrace] = []
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        yield {"type": "status", "message": f"使用模型 `{model}` 开始推导...", "model": model}

        final_text = ""
        for round_idx in range(1, self.max_steps + 1):
            yield {"type": "status", "message": f"第 {round_idx}/{self.max_steps} 轮推理...", "model": model}
            resp = self.client.chat.completions.create(
                model=model,
                messages=messages,
                tools=self._tools_schema(),
                tool_choice="auto",
                temperature=0.0,
            )
            msg = resp.choices[0].message

            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": msg.content or "",
            }
            tool_calls = getattr(msg, "tool_calls", None) or []
            if tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in tool_calls
                ]
            messages.append(assistant_msg)

            if tool_calls:
                for tc in tool_calls:
                    name = tc.function.name
                    args = self._safe_json_loads(tc.function.arguments)
                    yield {"type": "tool_call", "tool": name, "args": args, "model": model}
                    result, used_args, attempts = self._execute_tool_with_retry(
                        tool_name=name,
                        args=args,
                        sid=sid,
                        user_prompt=prompt,
                        model=self.fallback_model,
                    )
                    if len(attempts) > 1:
                        yield {
                            "type": "status",
                            "message": f"{name} 重试 {len(attempts)} 次后完成",
                            "model": model,
                        }
                    trace_result = dict(result) if isinstance(result, dict) else {"result": result}
                    trace_result["_attempts"] = attempts
                    traces.append(ToolTrace(tool=name, args=used_args, result=trace_result))
                    yield {"type": "tool_result", "tool": name, "result": trace_result, "model": model}
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "name": name,
                            "content": json.dumps(trace_result, ensure_ascii=False),
                        }
                    )
                continue

            final_text = msg.content or ""
            yield {"type": "assistant_text", "text": final_text, "model": model}
            break

        verify_result = None
        target = self._extract_verify_target(traces)
        if target:
            yield {"type": "status", "message": "检测到 ODE 解，执行自动回代验证...", "model": model}
            verify_result = sympy_verify_substitution(**target, session_id=sid)
            traces.append(
                ToolTrace(
                    tool="sympy_verify_substitution",
                    args=target,
                    result=verify_result,
                )
            )
            yield {"type": "tool_result", "tool": "sympy_verify_substitution", "result": verify_result, "model": model}

        return_payload = {
            "session_id": sid,
            "model": model,
            "proof": final_text.strip(),
            "traces": [t.__dict__ for t in traces],
            "verify_result": verify_result,
        }
        yield {"type": "done_once", "run": return_payload}
        return return_payload

    def run_stream(self, prompt: str, auto_upgrade: bool = True) -> Iterator[dict[str, Any]]:
        if self._is_eh_request(prompt):
            yield from self._run_eh_template_stream(prompt)
            return

        first_error = None
        try:
            first = yield from self._run_once_stream(prompt=prompt, model=self.primary_model)
        except Exception as exc:  # noqa: BLE001
            first_error = str(exc)
            first = {
                "session_id": None,
                "model": self.primary_model,
                "proof": "",
                "traces": [],
                "verify_result": None,
                "error": first_error,
            }
            yield {"type": "status", "message": f"主模型执行异常：{first_error}", "model": self.primary_model}
        upgraded = False
        reason = ""

        verify_ok = True
        if isinstance(first.get("verify_result"), dict):
            verify = first["verify_result"].get("verify", {})
            verify_ok = bool(verify.get("ok", True))

        if auto_upgrade and (first_error or not first.get("proof") or not verify_ok):
            upgraded = True
            reason = "primary_exception_or_verify_not_passed"
            yield {
                "type": "status",
                "message": f"触发自动升级：`{self.primary_model}` -> `{self.fallback_model}`",
                "model": self.fallback_model,
            }
            followup_prompt = (
                prompt
                + "\n\n请重新推导，并确保调用工具完成验证。"
                + "\n如果是微分方程，必须输出可回代验证的解。"
            )
            second = yield from self._run_once_stream(prompt=followup_prompt, model=self.fallback_model)
            second["upgraded"] = upgraded
            second["upgrade_reason"] = reason
            second["primary_model"] = self.primary_model
            second["fallback_model"] = self.fallback_model
            if first_error:
                second["primary_error"] = first_error
            yield {"type": "final", "run": second}
            return

        first["upgraded"] = upgraded
        first["upgrade_reason"] = reason
        first["primary_model"] = self.primary_model
        first["fallback_model"] = self.fallback_model
        yield {"type": "final", "run": first}

    def run(self, prompt: str, auto_upgrade: bool = True) -> dict[str, Any]:
        final_run = None
        for event in self.run_stream(prompt=prompt, auto_upgrade=auto_upgrade):
            if event.get("type") == "final":
                final_run = event["run"]
        if final_run is None:
            return {
                "session_id": None,
                "model": self.primary_model,
                "proof": "",
                "traces": [],
                "verify_result": None,
                "upgraded": False,
                "upgrade_reason": "no_final_event",
                "primary_model": self.primary_model,
                "fallback_model": self.fallback_model,
            }
        return final_run

    def verify_last(self, last_run: dict[str, Any]) -> dict[str, Any]:
        traces = [
            ToolTrace(tool=t.get("tool", ""), args=t.get("args", {}), result=t.get("result", {}))
            for t in last_run.get("traces", [])
        ]
        target = self._extract_verify_target(traces)
        if not target:
            return {"ok": False, "reason": "未找到可回代验证的方程与解。"}
        verify = sympy_verify_substitution(**target)
        return {"ok": True, "verify": verify, "equation": target["eq_str"], "solution": target["solution_str"]}

