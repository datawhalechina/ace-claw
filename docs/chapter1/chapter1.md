# Skill vs MCP
> [!CAUTION]
> ⚠️ Alpha内测版本警告：此为早期内部构建版本，尚不完整且可能存在错误，欢迎大家提Issue反馈问题或建议。


完整环境配置请看：`16agent-proj/docs/CONFIG_SETUP_CN.md`
## 目标能力

- 集成 `Cadabra2`、`Mathematica`、`SymPy`、知识库检索四类能力
- Stateful Session：对象级操作（定义符号、表达式、方程）可跨多轮复用
- 透明过程：前端显示每一步工具调用参数和返回值
- 证明兜底：支持将结论代回原方程进行验证

## Skill vs MCP：推荐分工

- **MCP（必须）**：承载“可验证计算”，提供结构化工具接口（`define_symbol`、`dsolve_ode`、`simplify`、`verify` 等）
- **Skill（强烈建议）**：约束流程与风格（禁止跳步、禁止心算、每一步必须引用工具返回值）

一句话：**MCP 管正确性，Skill 管方法论。**

## 目录结构

- `src/math_agent_mcp/session_manager.py`：会话状态与对象仓库
- `src/math_agent_mcp/tools/`：SymPy/Cadabra2/Mathematica/Knowledge 适配
- `src/math_agent_mcp/mcp_server.py`：Stateful MCP Server（FastMCP）
- `src/math_agent_mcp/mcp_tool_executor.py`：LLM 工具调用执行器（真实 tool-calling 循环）
- `src/math_agent_mcp/webapp.py`：Streamlit 交互界面（含工具调用折叠显示）

## 快速开始

1. 创建 Windows mamba 环境并安装依赖

```bash
mamba create -n math-agent-win python=3.11 pip -y
micromamba run -n math-agent-win python -m pip install .
```

2. 启动 MCP Server

```bash
micromamba run -n math-agent-win python -m math_agent_mcp.mcp_server
```

3. 启动 Web UI（类似你截图的“调用工具 + 结果可见”）

```bash
micromamba run -n math-agent-win streamlit run src/math_agent_mcp/webapp.py
```

## 环境变量（可选）

- `CADABRA2_BIN`：Cadabra2 可执行文件路径（默认 `cadabra2`）
- `CADABRA2_WSL_ENV`：Windows 回退到 WSL 时使用的 micromamba 环境名（默认 `cadabra`）
- `MATHEMATICA_BIN`：Wolfram 可执行文件路径（默认 `wolframscript`）
- `OPENAI_BASE_URL`：OpenAI 兼容端点（如 `https://hiapi.online/v1`）
- `OPENAI_API_KEY`：API 密钥（建议放 `.env`）
- `MODEL_PRIMARY`：默认模型（建议 `gemini-3-flash-no`）
- `MODEL_FALLBACK`：回退模型（建议 `gemini-3-pro-no`）

## 混合架构（Windows + WSL）

- Windows：MCP 主服务、Web UI、Mathematica、LLM API 调用
- WSL：Cadabra2
- Cadabra2 调用策略：
  1) 先尝试本机 `cadabra2`
  2) 失败且系统为 Windows 时，自动尝试 `wsl micromamba run -n cadabra cadabra2 -`

## Gemini API 快速测试

1. 复制模板并填入 key

```bash
copy .env.example .env
```

2. 运行 smoke test

```bash
micromamba run -n math-agent-win python scripts/gemini_smoke_test.py
```

## 在线网页端（真实工具调用）

```bash
micromamba run -n math-agent-win streamlit run src/math_agent_mcp/webapp.py
```

能力：
- 在线提问（数学/物理）
- LLM 自动调用工具链（knowledge/sympy/cadabra/mathematica）
- 自动验证 + 一键复验
- `flash-no -> pro-no` 自动升级

### 固定端口启动/停止（Windows）

如果你经常 `Ctrl+C` 后端口递增，可用脚本先清理再启动：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_webapp.ps1 -Port 8501
```

停止：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/stop_webapp.ps1
```

## 使用建议

- 对复杂物理推导：先用知识库工具检索定义和恒等式，再执行对象级符号操作
- 对最终结论：总是触发 `verify_substitution` 二次验证
- 把“证明文本”看作报告层，真正可信的是每一步 MCP 返回结果

## 下一步（建议）

- 对接真实向量数据库（Milvus/Qdrant）替换本地文本检索
- 增加“工具白名单策略”：不同阶段只允许调用特定工具
- 增加“Proof Graph”可视化（节点=表达式，边=工具变换）
