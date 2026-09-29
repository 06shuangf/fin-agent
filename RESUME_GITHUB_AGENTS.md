# 简历素材(详细版):四个 Agent 项目(GitHub:06shuangf)

> 本版基于四个仓库的 README + ARCHITECTURE.md 深度整理,每个项目含:
> 完整经历段(可直接粘贴)/ 架构图 / 关键设计决策(面试深挖时用)/ 数据流示例 / 追问答辞。
> 通用底座:GLM(OpenAI 兼容接口)· LangGraph · PyGithub · pytest · 结构化输出 + 容错解析。
>
> 用法建议:简历上放"完整经历段"的主体 bullet;"设计决策"部分是面试口述弹药,不必写进简历。

---

# 项目 1:mini-dev-team —— 多 Agent 协作开发团队(最重磅,建议首位)

**LangGraph 多 Agent 系统:Planner → Coder → Tester → Reviewer 流水线 + 打回循环 + 单/多 Agent 基准**
github.com/06shuangf/mini-dev-team | Python · LangGraph 1.2 · GLM · pytest 沙箱

## 完整经历段(简历用)

把一个编程任务交给四个专职 Agent 组成的开发流水线:Planner 出实现计划,Coder 生成代码与自测,
Tester 在沙箱中执行真实 pytest 提供客观反馈,Reviewer 审查不过则带具体意见打回 Coder 重写,
循环直到通过或到达轮数上限。

- **状态图编排**:基于 LangGraph StateGraph 显式建图(agent 间不直接对话,读写共享
  DevTeamState);条件路由是全图唯一分支点(APPROVE→结束 / REJECT 且未到上限→打回 /
  到上限→放弃并报告);`history` 字段用 reducer 追加而非覆盖,任何时刻状态里保留完整执行
  轨迹,每轮代码/测试报告/审查意见落盘 runs/*.json 可复盘
- **客观反馈闭环**:Tester 不用 LLM 判定——pytest 在沙箱(临时目录 + subprocess +
  30s 超时 + 危险模式静态拦截)里的 exit code 是 0 就是非 0,LLM 只负责把原始输出压缩成
  摘要;杜绝"模型之间互相客气、循环空转"的多 Agent 经典失败模式
- **评审必须可执行**:Reviewer 强制输出严格 JSON {verdict, comments},意见具体到
  "Coder 无需猜测就能修"(如"单列时 right 边界处理错误,修复 while 条件");
  修订轮 prompt 注入上轮测试报告+审查意见,并约束"只修复被点名的问题",防止改崩已过的部分
- **工程稳定性**:三层容错 JSON 解析(直接 loads → 剥 markdown 围栏 → 正则提取 {}),
  难题集 20 次 Coder 调用零解析失败;业务层轮数上限 + LangGraph recursion_limit
  (4 + max_rounds×3)双保险防死循环;四个节点按角色差异化设定温度
  (planner 0.1 / coder 0.2 / tester 0.0 / reviewer 0.1)
- **单 vs 多 Agent 基准**:10 任务 + 人工隐藏测试,判分与被测系统完全隔离
  (模型永远看不到判分侧测试);validate_hard 先用参考实现验证每个隐藏测试套件本身可满足
  (防"题目无解"污染基准);retry 只对基础设施错误(网关 524)公平重试、逻辑失败不重试
  (避免"重试到通过"的美化偏差);13 个离线单元测试

## 架构图(口述用)

```
task → START → planner → coder → tester(沙箱跑 pytest)→ reviewer ─┬→ accepted → END
                  ▲                                            │
                  └────── REJECT: 带具体意见打回 ←──────────────┘
                        (rounds >= MAX_ROUNDS → finish_review_rejected)
```

## 关键设计决策(面试深挖)

1. **为什么 Tester 是"沙箱跑测试"而不是"LLM 写测试"**:多 Agent 系统最怕反馈回路里
   全是 LLM 主观判断。把"客观信号"交给确定性代码,exit code 没有解释空间;LLM 在
   tester 节点只做输出压缩,不参与判定。
2. **reducer 而非覆盖**:LangGraph 默认新值覆盖旧值;history 用 Annotated[list, append]
   让每个节点追加条目——可解释性和复盘能力的基础。
3. **职责边界靠状态字段划分**:planner→plan, coder→code/test_code/rounds,
   tester→test_*, reviewer→review_*;状态对象本身就是接口契约。
4. **沙箱的诚实边界**:demo 级黑名单+超时(静态扫描 subprocess/os.remove/绝对路径,
   30s kill 死循环),README 明示生产应换 Docker/WASM;黑名单可被 getattr 绕过,
   但"给 LLM 提供客观反馈"的用途下成本只有 Docker 的 1/10。
5. **真实数据流示例**(spiral_order 难题):coder 首版漏单列场景 → 沙箱自测 FAIL →
   reviewer 打回"test_single_col 失败,修复 while 条件" → coder#2 只改边界条件 →
   全绿 APPROVE。两轮完成,轨迹完整落盘。

## 追问答辞

- **多 Agent 一定比单 Agent 好吗?** 不一定,所以我做了基准对比:简单任务单 Agent 更省
  token,难题/需要自我修复的任务多 Agent 的打回循环优势明显。结论是任务复杂度决定选型。
- **怎么防死循环?** 双保险:业务层 rounds 上限保证语义正确,框架层 recursion_limit 兜底。
- **LLM 输出不合规怎么办?** 三层容错解析(实测 20 次调用零失败);解析器看似琐碎,
  实际是流水线稳定性的关键——没有它约 5-10% 的输出会炸掉整个任务。

---

# 项目 2:github-copilot-assistant —— 单 Agent ReAct 工具调用

**GLM + LangGraph ReAct Agent:自然语言查询 GitHub 全生态**
github.com/06shuangf/github-copilot-assistant | Python · LangGraph · PyGithub

## 完整经历段(简历用)

基于 LangGraph create_react_agent 构建单 Agent 问答系统:用户一句自然语言
("langgraph 有多少 star?最近在做什么?"),Agent 自主进入"思考 → 选工具 → 调 GitHub API →
观察 → 继续调工具或作答"循环,停止时机完全由模型决定。

- **三层解耦架构**:接口层(CLI 会话/命令/调用可视化/错误兜底)→ 编排层
  (create_react_agent + ReAct 循环 + 系统提示词约束)→ 工具层(7 个 @tool);
  依赖方向自上而下,换界面(如 Gradio)只动接口层
- **工具层设计**:PyGithub 封装为 7 个结构化工具,按"用户问题→所需数据"最短路径设计,
  覆盖发现(仓库搜索)/仓库详情(issue/PR)/用户资料/用户动态四类查询;
  Pydantic args_schema 做入参契约(Field 描述 + ge/le 范围约束),
  模型传错值直接触发可读校验错误而非浪费配额的 API 调用
- **反幻觉的工程细节**:工具统一返回 JSON 而非自然语言——数字和日期是 LLM 最易编造的
  内容,JSON 让模型"转述"接近填空而非改写;list_user_events 对 PushEvent 等
  做载荷裁剪(只留 commit 消息前 80 字符),上下文预算是 Agent 系统最贵的资源
- **可测试性**:Settings 注入而非全局读环境,单元测试完全离线确定;联网测试显式标记
  pytest -m live 按需运行;GITHUB_TOKEN 缺失自动降级匿名访问,
  clone 后只需一个 GLM key 即可演示

## 关键设计决策(面试深挖)

1. **为什么工具返回 JSON**:返回自然语言时模型转述≈改写(幻觉率高);返回 JSON 时
   转述≈填空。错误也走同一条路 {"error": ...},模型拿到错误能自己向用户解释,
   异常不炸会话。
2. **为什么是这 7 个工具**:刻意不贪多,按四类查询的最短路径设计;工具越多,
   模型选择负担越大、描述维护成本越高。
3. **载荷裁剪**:GitHub event 的原始 payload 很大,直接塞上下文会迅速耗尽预算;
   裁剪后单事件一行紧凑表示。

## 追问答辞

- **ReAct 循环谁控制停止?** 模型自己决定(观察后不再发 tool_call 即作答);
  create_react_agent 内部处理 agent↔tools 的消息拼接。
- **与 mini-dev-team 的关系?** 单/多 Agent 两类核心能力的对照实验:本项目核心是
  "模型如何正确使用工具",那边是"多角色如何协作与自我修复";共享 GLM 接入与
  结构化输出+容错解析的设计模式。

---

# 项目 3:rag-knowledge-base —— RAG 检索增强生成

**100% 本地混合检索 + 反幻觉三道闸门的知识库问答**
github.com/06shuangf/rag-knowledge-base | Python · numpy · GLM(零 embedding 依赖)

## 完整经历段(简历用)

检索增强问答系统:离线把本地文档切块建索引(JSONL 追加式),在线混合检索召回相关片段,
GLM 做"开卷考试"式回答并强制标注引用;知识库覆盖不到的问题拒答而不是编造。
工程重心在检索质量与幻觉控制,评测 7/7 通过(含 2 个知识库外问题全部正确拒答,零幻觉)。

- **零 embedding 依赖的混合检索**:BM25(词级:ASCII 整词 + CJK 单字)+
  字符 3-gram TF-IDF 余弦双通道,RRF 倒数排名融合(k=60)——选 RRF 而非分数加权
  因为 BM25(无界)与余弦(0~1)量纲不可比,RRF 只用排名对分数分布免疫;
  所用网关无 embedding 模型,检索层完全本地化后系统反而更强壮(无第二 API 依赖)
- **反幻觉三道闸门(成本递增)**:①检索信号门控——两路得分都≈0 时直接拒答,
  连 LLM 调用都不发(零成本,不给模型编造机会);②提示词硬约束——只用资料块、
  事实必须带 [chunk_id] 引用、不足输出固定拒答句;③引用后校验——答案中的引用 id
  必须 ∈ 本次召回集合,伪造引用被过滤(零成本)
- **CJK 感知的分块与分词**:两级贪心装箱分块(段落→句子边界 + 100 字符重叠窗口,
  绝不固定长度硬切拦腰斩断句子),chunk_id 带文档名前缀可回溯;
  自写正则分词(ASCII 连续段保整词 + 中文单字),不引入 jieba 保持零依赖,
  其"不识别词边界"的弱点由 3-gram 通道补偿
- **严格的评测设计**:7 题中刻意放 2 个"模型知道答案但知识库没有"的问题
  (奥运年份/GIL)——这是 RAG 最容易翻车的地方(参数知识压过提示词约束),
  判分要求必须拒答;abstained 判定 = 含拒答句 且 无有效引用(防止"先说不知道
  又忍不住猜一句");11 个离线单元测试

## 关键设计决策(面试深挖)

1. **双通道互补**:BM25 擅长精确词面命中(专有名词/编号/代码标识符),
   3-gram 擅长子词变形("倒数排名"命中"倒数排名融合");中文无空格场景尤其有效。
2. **重叠窗口**:检索最小单位是块,块边界就是语义撕裂发生的地方;100 字符重叠
   避免关键句恰好被切在边界。
3. **JSONL 追加式索引**:add 只追加行 O(新块数);检索器惰性重建并缓存,
   文档变更才置空——索引成本线性而非每次全量重建。
4. **temperature=0**:答案应当是检索内容的确定性函数,不该有随机性。

## 追问答辞

- **为什么不用向量库?** 网关无 embedding 模型;与其引入第二 API 依赖不如本地化。
   RRF 已预留多通道接口,加一路向量检索即可升级——这是演进项不是缺陷。
- **拒答机制为什么重要?** 合规/企业场景"宁可不说,不能说错";评测里专放
   知识库外问题就是为了量化这个能力。

---

# 项目 4:github-watch-agent —— 事件驱动的自主定时 Agent

**无人提问的自主 Agent:轮询 → 去重 → LLM 过滤排序 → 日报推送**
github.com/06shuangf/github-watch-agent | Python · PyGithub · GLM

## 完整经历段(简历用)

与前三个项目本质不同:没有人类提问环节。调度器定时唤醒 → PyGithub 采集订阅仓库的
issue/PR/release → 与持久化状态库(seen.json)比对去重 → LLM 一次调用完成
"逐条裁决值得报吗(含理由)+ 按重要性排序的中文日报" → 三通道推送(控制台/文件/Webhook)。
人类的角色从"提问者"退化为"订阅者+收件人"——注意力外置的典型形态。

- **首轮基线策略(防洪水)**:新订阅的仓库已有大量存量 issue/PR,若首轮照常报告,
  第一封日报就是 10+ 条历史噪音;判定规则为"该仓库事件全部未见过=首轮"→只记录
  不报告;按仓库独立判定,中途新增订阅互不影响
- **幂等去重 key**:`owner/repo#issue:1234` / `#pr:9027` / `#release:v1.2.3`
  ——对象类型+永不变的对象标识,天然稳定;已知边界明示:issue 重开等状态迁移
  不产生新 key(演进方案:key 加状态后缀或对象状态机,当前场景增量收益不抵复杂度)
- **成本与一致性设计**:过滤与摘要合并为一次 LLM 调用(同时返回 verdicts+digest),
  省 50% 调用且排序直接复用裁决结论、两阶段不打架;temperature=0
  (日报应是事件的确定性函数);RawEvent 中间结构让 summarizer 不依赖 PyGithub 类型,
  单元测试纯内存构造
- **存活优先的工程哲学**:serve 循环把单轮整体包 try/except——网络断/限速/网关 524
  只打日志下一轮照常;后台监控 Agent 最不可接受的失败模式是"悄悄死了",
  比"某轮报错"糟糕一个量级;KeyboardInterrupt 单独放行保证可人工停止

## 真实运行示例(三轮实测)

```
第 1 轮 → 基线:记录 10 个存量事件,安静不报
第 2 轮 → 无新事件:本轮没有新事件。
第 3 轮 → 新 PR #9027:LLM 裁决 report=true("安全相关修复…建议跟进")
          → 日报含一句话理由 + 事件 URL → 推送 → 10 keys 写回 seen
```

## 追问答辞

- **为什么轮询不用 webhook?** 推送需要公网端点;个人订阅场景轮询足够
  (匿名 60 req/h、token 5000/h,当前每仓库每轮仅 3 请求);run --once 已为
  cron 触发预留,生产化即包系统定时任务。
- **LLM 在这里的角色?** 收窄为"信息守门员+编辑"(过滤+排序),不做全权决策——
  自主 Agent 的失控风险随 LLM 权限扩大而上升。

---

# 组合叙事(放简历总述或面试自我介绍)

**Agent 工程系列(4 个项目,github.com/06shuangf)**:围绕 Agent 的四种架构模式
各做一个可运行、带测试、有实测数据的完整实现——单 Agent ReAct 工具调用
(copilot-assistant)/ 多 Agent 协作编排(mini-dev-team)/ RAG 检索增强
(rag-knowledge-base)/ 事件驱动自主运行(watch-agent)。四者共享统一技术底座
(GLM OpenAI 兼容接入、结构化输出+容错解析、pytest 离线测试),覆盖从被动应答到
全自主运行的完整主动性谱系;每个仓库均附 ARCHITECTURE.md 沉淀设计决策与已知边界。

一句话串联:"我不是做了一个 demo 的四种皮肤,而是沿'编排复杂度'和'自主性'两个轴
各做了带基准/评测的完整实现,并且每个项目都明示了能力边界和演进方向。"

## 能力矩阵

| 项目 | 架构模式 | 核心能力证明 | 量化结果 |
|---|---|---|---|
| mini-dev-team | 多 Agent 编排 | 状态图/打回循环/客观反馈/隔离基准 | 13 单测;难题集 20 次 Coder 调用零解析失败 |
| copilot-assistant | 单 Agent ReAct | 工具层设计/JSON 反幻觉/三层解耦 | 7 工具;分层测试(离线秒级+live 按需) |
| rag-knowledge-base | RAG | 混合检索/三道反幻觉闸门/严格评测 | 评测 7/7 零幻觉;11 单测 |
| watch-agent | 自主定时 | 幂等去重/成本优化/存活优先 | 三轮实测行为符合设计;省 50% LLM 调用 |

## 通用高频追问

| 追问 | 要点 |
|---|---|
| 四个项目关系? | 同一底座下四种架构模式的刻意探索;两两互为对照(单 vs 多 Agent;被动 vs 自主) |
| 结构化输出怎么保证? | 严格 JSON + 三层容错解析(loads→剥围栏→正则);温度按角色差异化 |
| LLM 权限边界? | 越自主的项目 LLM 决策权越收窄(watch-agent 只做过滤排序);客观判定交给确定性代码 |
| 怎么控制成本? | 信号门控免调用、verdicts+digest 合并、载荷裁剪、上下文预算管理 |
| 工程成熟度? | 每项目都有:离线单测、评测脚本、ARCHITECTURE.md、已知限制明示(诚实边界) |
