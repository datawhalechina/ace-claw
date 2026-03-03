<h1 align="center"> 项目名称（⚠️ Alpha内测版） </h1>

> [!CAUTION]
> ⚠️ Alpha内测版本警告：此为早期内部构建版本，尚不完整且可能存在错误，欢迎大家提Issue反馈问题或建议。

一个面向数学/物理推导的低幻觉智能体骨架：  
核心思想是**让 LLM 只负责“决策与编排”**，把代数运算、微分方程求解、化简、验算等交给 OpenClaw 工具执行并返回可追溯结果。

## 项目受众

物理学、数学等科学领域的研究人员，需要借助LLM进行辅助符号运算来解决科研问题。

## 在线阅读
https://datawhalechina.github.io/repo-template

## 目录
*这里写你的项目目录，及其完成状态，已完成的部分添加上跳转链接*

|  章节名   | 简介 | 状态 |
|  ----  | ---- | ---- |
| [第1章  Skill vs MCP](https://github.com/flying-fish-2025/math-physics/blob/main/docs/chapter1/chapter1.md)  | 集成 `Cadabra2`、`Mathematica`、`SymPy`三类能力；Stateful Session：对象级操作（定义符号、表达式、方程）可跨多轮复用；透明过程：前端显示每一步工具调用参数和返回值；证明兜底：支持将结论代回原方程进行验证 | ✅ |
| [第2章 对接OpenClaw](https://github.com/datawhalechina/repo-template/blob/main/docs/chapter2)  | 将第1章内容作为OpenClaw的应用 | 🚧 |

## 贡献者名单

| 姓名 | 职责 | 简介 |
| :----| :---- | :---- |
| 肖泽华 | 项目负责人 | 一个数学物理研究者 |
| 陈可为 | 第1章贡献者1 | 机器学习在读研究生 |
| 龙垭宇 | 第1章贡献者2 | 机器学习在读研究生 |


## 参与贡献

- 如果你发现了一些问题，可以提Issue进行反馈，如果提完没有人回复你可以联系[保姆团队](https://github.com/datawhalechina/DOPMC/blob/main/OP.md)的同学进行反馈跟进~
- 如果你想参与贡献本项目，可以提Pull Request，如果提完没有人回复你可以联系[保姆团队](https://github.com/datawhalechina/DOPMC/blob/main/OP.md)的同学进行反馈跟进~
- 如果你对 Datawhale 很感兴趣并想要发起一个新的项目，请按照[Datawhale开源项目指南](https://github.com/datawhalechina/DOPMC/blob/main/GUIDE.md)进行操作即可~

## 关注我们

<div align=center>
<p>扫描下方二维码关注公众号：Datawhale</p>
<img src="https://raw.githubusercontent.com/datawhalechina/pumpkin-book/master/res/qrcode.jpeg" width = "180" height = "180">
</div>

## LICENSE

<a rel="license" href="http://creativecommons.org/licenses/by-nc-sa/4.0/"><img alt="知识共享许可协议" style="border-width:0" src="https://img.shields.io/badge/license-CC%20BY--NC--SA%204.0-lightgrey" /></a><br />本作品采用<a rel="license" href="http://creativecommons.org/licenses/by-nc-sa/4.0/">知识共享署名-非商业性使用-相同方式共享 4.0 国际许可协议</a>进行许可。

