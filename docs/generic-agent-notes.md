# GenericAgent 定向阅读笔记

- 阅读日期：2026-10-09。
- 阅读对象：[lsdefine/GenericAgent](https://github.com/lsdefine/GenericAgent)。
- 源码版本：[`f308ee7`](https://github.com/lsdefine/GenericAgent/commit/f308ee7eb079cc402edf5a934fa65f6d71a4c7ad)，提交日期 2026-09-30。
- 目标：只回答 Agent Loop、Tool、Context、Memory、Skill 五个问题，记录架构、关键抽象和采用取舍。
- 方法：静态阅读核心源码与记忆文档，不复制实现代码；下文“借鉴／暂不采用”是针对自建项目的判断。
- 项目背景：引用对话显示，自建 `self_evolving_agent` 已有 LLMClient、FakeLLM 和统一入口，下一步是最小 Tool。
- 总体结构：`agentmain.py` 组织任务，`agent_loop.py` 驱动循环，`ga.py` 执行动作，`llmcore.py` 适配模型并维护会话。

## 1. Agent Loop 怎么运行？

### 架构与运行路径

1. 外部入口调用 `GenericAgent.put_task()`，把任务放入队列，并得到用于接收输出的队列。
2. `GenericAgent.run()` 取出任务，组装系统提示，创建 `GenericAgentHandler`，启动 `agent_runner_loop()`。
3. 循环首次发送系统提示和用户输入；每轮调用 `client.chat(messages, tools)` 获取模型响应。
4. 模型客户端把不同协议的响应统一成包含正文和 `tool_calls` 的结果。
5. 循环解析工具名称与参数，再交给 Handler 分发执行；同一轮的多个调用按顺序处理。
6. 工具返回 `StepOutcome`，循环收集结果和后续提示，通过回调更新摘要及下一轮上下文。
7. 下一轮发送新增反馈，历史由客户端背后的 Session 保存；持续执行直到结束、中断或达到轮数上限。

### 关键抽象与结束条件

- `agent_runner_loop`：负责“请求模型 → 分发动作 → 回传结果 → 判断继续”的控制流程。
- `BaseHandler`：提供工具分发和轮次结束回调；`GenericAgentHandler` 实现具体行为。
- `StepOutcome.data`：本次动作产生的数据。
- `StepOutcome.next_prompt`：下一轮反馈；为空时，循环按当前任务完成处理。
- `StepOutcome.should_exit`：明确要求退出，例如 `ask_user` 发起人工介入。
- 没有显式工具调用时，引擎转交内部 `no_tool`；普通完整回复会结束，空回复等情况可要求重试。
- `_done_hooks` 可以在普通结束前追加收尾提示；显式退出不经过这类收尾。
- 循环函数默认上限为 40 轮，`GenericAgent.run()` 实际传入 180 轮；Handler 也能调整上限。
- 达到上限返回 `MAX_TURNS_EXCEEDED`；“没有工具调用”本身不等于现实任务已验证成功。

### 借鉴与暂不采用

- 借鉴：把循环和动作实现分开，使 FakeLLM 可以独立验证控制流程。
- 借鉴：显式表达动作结果、继续和退出，避免依靠打印文字决定执行状态。
- 暂不采用：一开始就加入任务队列、流式输出、计划模式、完成钩子和复杂轮次提示。
- 当前落点：先实现单任务循环，验证“调用一次工具 → 读取反馈 → 最终回答”和轮数上限。

依据：[任务组织](https://github.com/lsdefine/GenericAgent/blob/f308ee7eb079cc402edf5a934fa65f6d71a4c7ad/agentmain.py#L131)、[循环与 StepOutcome](https://github.com/lsdefine/GenericAgent/blob/f308ee7eb079cc402edf5a934fa65f6d71a4c7ad/agent_loop.py#L7)、[no_tool 处理](https://github.com/lsdefine/GenericAgent/blob/f308ee7eb079cc402edf5a934fa65f6d71a4c7ad/ga.py#L477)。

## 2. Tool 怎么注册与执行？

### 架构与调用路径

1. `agentmain.load_tool_schema()` 读取 `assets/tools_schema.json`，形成对模型可见的工具描述列表。
2. 描述包含工具名称、用途和参数结构；非 Windows 环境会把 schema 中的 PowerShell 改为 Bash。
3. `--no-user-tools` 会过滤 `ask_user` 和 `start_long_term_update`，改变模型可见的列表。
4. `ToolClient` 通过文本协议描述工具并解析 `<tool_use>`；`NativeToolClient` 对接原生工具调用协议。
5. 两条路径最终向循环提供统一的 `tool_calls`，循环无需感知模型厂商的协议差别。
6. `BaseHandler.dispatch()` 按名称寻找 `do_<tool_name>` 方法，再由该方法调用底层工具函数。
7. 工具执行结果被序列化并与调用 ID 关联，回传给模型，构成后续决策的观察依据。

### 关键抽象

- “注册”由两部分组成：schema 负责让模型知道工具，Handler 方法负责实际执行。
- 这里没有统一的装饰器注册表；新增工具需要同步描述名称与执行方法。
- schema 声明不等于完整运行时校验；源码中各 Handler 自行提取、转换和检查部分参数。
- 未知工具会生成纠错反馈，并触发工具描述刷新；它不会被自动创建成新工具。
- 九个公开工具包含代码执行、文件读写与补丁、网页观察与 JS、人工介入及两种记忆操作。
- `no_tool` 是引擎内部处理路径，不属于对模型公开的九个工具。
- 工具可以返回普通结果或生成器；生成器用于逐步输出日志，最终结果仍由 `StepOutcome` 表达。

### 借鉴与暂不采用

- 借鉴：分开“对模型的工具说明”和“程序中的执行函数”，并让两者使用同一名称。
- 借鉴：把工具反馈送回模型，失败时也保留可用于调整策略的错误信息。
- 暂不采用：同时实现文本工具协议和原生协议，以及从回复代码块提取执行内容的兼容逻辑。
- 当前落点：只做一个简单工具，明确名称、参数和结果，先验证名称解析、执行与反馈闭环。
- 取舍：当前工具很少时，直接名称映射即可；无需提前做插件发现或动态注册框架。

依据：[schema 加载](https://github.com/lsdefine/GenericAgent/blob/f308ee7eb079cc402edf5a934fa65f6d71a4c7ad/agentmain.py#L17)、[工具定义](https://github.com/lsdefine/GenericAgent/blob/f308ee7eb079cc402edf5a934fa65f6d71a4c7ad/assets/tools_schema.json)、[方法分发](https://github.com/lsdefine/GenericAgent/blob/f308ee7eb079cc402edf5a934fa65f6d71a4c7ad/agent_loop.py#L18)、[协议适配](https://github.com/lsdefine/GenericAgent/blob/f308ee7eb079cc402edf5a934fa65f6d71a4c7ad/llmcore.py#L907)。

## 3. Context 怎么组织？

### 上下文组成与归属

| 内容 | 维护位置 | 作用 |
| --- | --- | --- |
| 系统提示、日期、记忆导航 | `get_system_prompt()` | 给出角色规则和查找记忆的入口 |
| 完整会话消息 | `llmclient.backend.history` | 保存用户、模型和工具交互，供后续请求使用 |
| 简短过程摘要 | `handler.history_info` | 记录用户输入概况和模型 `<summary>`，重新锚定进度 |
| 当前任务关键事实 | `handler.working['key_info']` | 保留约束、已验证发现、当前进展和下一步 |
| 当前工具结果及后续提示 | 循环当轮消息 | 让模型依据最新观察继续执行 |

### 组织与压缩机制

- 循环每轮只显式传入新增消息；实际历史积累由 Session 完成，不能据此认为旧消息被全部丢弃。
- `history_info` 是摘要轨迹，和 Session 的完整协议历史是两份不同用途的数据。
- `_get_anchor_prompt()` 在相关工具反馈中拼接轮次、摘要及 `key_info`；并非每个工具都追加完整锚点。
- 该方法在奇数轮加入最近 30 条摘要，并按更低频率加入更早摘要的折叠结果。
- `turn_end_callback()` 提取本轮 `<summary>`，按轮次条件追加检查点提示、记忆导航或人工干预内容。
- `llmcore.compress_history_tags()` 压缩旧消息中的重复锚点、思考文本和较长工具内容。
- `trim_messages_history()` 用序列化字符数近似上下文体积，超限后保留前缀和近期消息、裁掉中间旧消息。
- 裁剪时还处理孤立的工具结果引用，避免破坏模型接口要求的消息结构。

### 借鉴与暂不采用

- 借鉴：区分完整历史、任务摘要和关键状态，给每种数据明确归属。
- 借鉴：长输出按需截断，关键结论单独保留，避免每轮塞入全部文件和日志。
- 暂不采用：固定轮次的多套提示规则、XML 风格锚点和多模型消息裁剪兼容层。
- 当前落点：先维护一份消息列表，确保工具调用和结果成对；出现实际长度问题后再引入摘要。

依据：[锚点与轮次回调](https://github.com/lsdefine/GenericAgent/blob/f308ee7eb079cc402edf5a934fa65f6d71a4c7ad/ga.py#L540)、[历史压缩与裁剪](https://github.com/lsdefine/GenericAgent/blob/f308ee7eb079cc402edf5a934fa65f6d71a4c7ad/llmcore.py#L48)。

## 4. Memory 怎么注入？

### 分层存储

| 层级 | 文件或载体 | 职责 |
| --- | --- | --- |
| L0 | `memory/memory_management_sop.md` | 定义记忆分类、写入和维护规则 |
| L1 | `memory/global_mem_insight.txt` | 用场景关键词定位下层记忆 |
| L2 | `memory/global_mem.txt` | 保存长期有效的环境事实与配置 |
| L3 | `memory/` 中的 SOP 与脚本 | 保存特定任务的关键经验和复用能力 |
| L4 | `memory/L4_raw_sessions/` | 保存或处理历史会话资料，供需要时追溯 |

### 注入与更新路径

1. 初始化时，`agentmain.py` 检查 L1/L2 文件；缺失时创建空事实库或复制索引模板。
2. 每次任务组装系统提示时，`get_global_memory()` 读取固定导航结构和 L1 索引，并附上工作目录。
3. 默认注入的是记忆入口与索引；L0、L2、L3、L4 的正文不会在这里全部自动展开。
4. 模型按索引使用 `file_read` 读取需要的事实或 SOP，再依据内容继续行动。
5. `update_working_checkpoint` 替换当前 `key_info`，供后续锚点使用；它本身不把信息持久化到文件。
6. 新任务会继承上一 Handler 的 `key_info` 并标记其已跨任务，提示模型更新或清除旧状态。
7. `start_long_term_update` 提供记忆提炼提示和 L0 内容，随后仍需模型调用文件工具完成写入。
8. 当前实现不足 10 轮时不进入长期提炼；schema 的“15+ 轮必须调用”属于提示约定，二者需区分。

### 借鉴与暂不采用

- 借鉴：采用“短索引常驻、详细内容按需读取”，控制每轮上下文成本。
- 借鉴：短期进度与长期经验分开，长期条目只保留已验证、可复用且不易重建的信息。
- 暂不采用：一开始就建立五层文件体系、自动归档调度和依赖模型主动维护的复杂索引规则。
- 当前落点：先用一份可人工检查的 Markdown 保存复用经验，确有多个场景后再拆索引与详情。
- 取舍：记忆 SOP 是行为约定；不能把提示里的写入要求当成程序已经强制执行的存储约束。

依据：[记忆入口读取](https://github.com/lsdefine/GenericAgent/blob/f308ee7eb079cc402edf5a934fa65f6d71a4c7ad/ga.py#L597)、[初始化与系统提示](https://github.com/lsdefine/GenericAgent/blob/f308ee7eb079cc402edf5a934fa65f6d71a4c7ad/agentmain.py#L25)、[检查点与长期更新](https://github.com/lsdefine/GenericAgent/blob/f308ee7eb079cc402edf5a934fa65f6d71a4c7ad/ga.py#L461)、[记忆管理 SOP](https://github.com/lsdefine/GenericAgent/blob/f308ee7eb079cc402edf5a934fa65f6d71a4c7ad/memory/memory_management_sop.md)。

## 5. Skill 怎么调用？

### 发现与执行路径

1. 本项目的 Skill 主要体现为 L3 的任务 SOP 和工具脚本，而非一个独立的 Skill 类。
2. L1 索引提供场景关键词与文件名，例如浏览器特殊操作指向 `tmwebdriver_sop`。
3. 模型判断任务与哪个场景相关，通过 `file_read` 读取对应 SOP；索引不足时可列出目录寻找文件。
4. `do_file_read()` 对记忆或 SOP 文件追加提示，要求把执行要点提取到工作记忆。
5. 纯说明型 SOP 指导模型组合现有工具；脚本型能力通过 `code_run` 执行或导入使用。
6. 例如浏览器 SOP 解释导航、页面观察和特殊操作的前提，再由 `web_scan`、`web_execute_js` 等完成动作。
7. 可复用经验经验证后写成 SOP 或脚本，并按需更新 L1，使下次相似任务更容易找到它。

### 关键区别

- Tool 是程序能直接分发执行的原子动作；Skill 是完成一类任务的经验、约束和工具组合方法。
- 核心公开工具列表没有 `call_skill`；上述调用链依靠“发现 → 阅读 → 理解 → 工具执行”完成。
- 脚本可以复用复杂处理逻辑，但写入脚本不等于自动新增一个对模型公开的工具 schema。
- 索引决定能力能否被发现，SOP 提供关键前提，工具反馈决定执行是否真实成功。
- 这里的“自进化”主要是积累并复用外部经验与脚本，不是训练模型参数。

### 借鉴与暂不采用

- 借鉴：把高成本探索后验证有效的前提和坑点整理为短 SOP，避免下次重新探索。
- 借鉴：文档与脚本结合；文档解释适用条件，脚本封装确实值得复用的复杂操作。
- 暂不采用：自动生成大量技能、无条件安装依赖，以及现在就搭建技能市场或统一加载器。
- 当前落点：先跑通一个工具任务，再手工总结一份短 SOP，验证后续同类任务能否复用。
- 采用顺序：最小循环与工具闭环 → 可检查的消息历史 → 短 SOP → 有实际需求后再做分层记忆。

依据：[初始能力索引](https://github.com/lsdefine/GenericAgent/blob/f308ee7eb079cc402edf5a934fa65f6d71a4c7ad/assets/global_mem_insight_template.txt)、[SOP 读取后的提示](https://github.com/lsdefine/GenericAgent/blob/f308ee7eb079cc402edf5a934fa65f6d71a4c7ad/ga.py#L427)、[浏览器 SOP 示例](https://github.com/lsdefine/GenericAgent/blob/f308ee7eb079cc402edf5a934fa65f6d71a4c7ad/memory/tmwebdriver_sop.md)。
