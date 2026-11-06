# OpenCode × Cursor 评审方案

2026-11-06 建立。结论优先。
OpenCode 写，Cursor 挑刺，人拍板。两条通道独立：`/cr` 审**代码改动**，`/xcheck` 审**判断和方案**。

---

## 1. 目录即安装源

本目录是唯一事实来源，`install.sh` 同步到生效位置：

```bash
cd ~/code/ai/ai_study/agent/opencode
./install.sh            # 安装/覆盖
./install.sh --check    # 只比对，有差异退出码 1
```

| 本目录 | 生效位置 | 作用 |
|---|---|---|
| `scripts/opencode-cr` | `~/.local/bin/opencode-cr` | 取 `git diff` 交 cursor-agent 只读评审 |
| `scripts/opencode-xcheck` | `~/.local/bin/opencode-xcheck` | 把一段文本交 cursor-agent 批判 |
| `config/agents/cr.md` | `~/.config/opencode/agents/cr.md` | `cr` 子 agent：只跑脚本、只转述 |
| `config/commands/cr.md` | `~/.config/opencode/commands/cr.md` | `/cr`：审 + 按策略修 + 复验 |
| `config/commands/xcheck.md` | `~/.config/opencode/commands/xcheck.md` | `/xcheck`：落盘 → 批判 → 裁决表 → 停 |

未改动 `opencode.jsonc`，未安装 git hook，未改 shell 配置。

安装后需重开 opencode 或 `opencode reload`（命令与 agent 在启动时加载）。

---

## 2. 用法

```bash
/cr                 # 审工作区改动（git diff HEAD，含 staged）
/cr main            # 审相对 main 的改动，$ARGUMENTS 透传给脚本
@cr 审一下           # 只要意见，不让它改
```

`/cr` 的修复策略写死在命令里：blocker 必须修（不修要留理由）→ major 问过再改 → minor 只汇报 → 最多复验 3 轮。

```bash
/xcheck             # 把上一条回复逐字落盘交给 cursor 批判，出裁决表后停住
```

`/xcheck` 四步各有防守目标：逐字落盘（防转述缩水）→ 强制证据（防幻觉）→ 裁决表（防静默丢弃）→ 停在表格（防无感落盘）。

---

## 3. 关键设计决策

1. **单裁判**：`cr` 子 agent 只转述 cursor 输出，不二次评审。两个模型各说一套无法收敛。
2. **diff 内联 + 保留 workspace**：内联保证「只就改动下结论」，workspace 允许它读调用方验证影响面。禁的是点评范围，不是阅读范围。
3. **每处改动必须报引用点数量（0 也要写）**：防不 grep 就断言无影响。
4. **强制证据**：每条批判须带 `文件:行号 + 原文`，或真跑过的命令及输出；给不出必须标「无证据」。这是压住幻觉的唯一杠杆。
5. **不自动触发**：无文件监听、无 pre-commit hook。30~60 秒阻塞会诱使 `--no-verify`，且真坑多为 major 而非 blocker。
6. **模型 `grok-4.7-medium`**（`CR_MODEL` / `XC_MODEL` 可覆盖）。不用 fast：评审要判断力，不要吞吐。

---

## 4. 实测（临时仓库，非业务代码）

| 场景 | 模型 | 耗时 | 结果 |
|---|---|---|---|
| diff 含 4 处缺陷（注入/越界/类型/None 解包） | gpt-5.3-codex-low-fast | 33~43s | 全命中 |
| 同上 | grok-4.7-medium | 61s | 全命中，并主动报「引用点：0」 |
| 改动仅在 `svc.py`，调用方在 `api.py`/`jobs.py` | gpt-5.3-codex-low-fast | 43s | 自行读两个未改动文件，逐条引用并判定破坏 |
| 自信但错误的方案文本（谎称有 try/except、已判空） | gpt-5.3-codex-low-fast | 45s | 4 条全击穿，含一条实跑 `rg` 作为证据 |

---

## 5. 已知边界

- **跨仓库消费方**：只看当前 workspace，改 API 字段时看不见别的服务，需 `--add-dir` 或人工告知。
- **Nacos / 环境变量 / DB schema**：不在 git 内，天然盲区。
- **未跟踪文件**：按 `+` 前缀补入（文本）；超大或二进制被闸门拒绝（默认 80000 字节）。
- **commit 后 diff 为空**：`/cr` 基于 `git diff HEAD`，每轮都 commit 会让下一轮直接 `NO_ISSUES`。
- **时长**：单次 30~60s；`/cr` 的 `!` 展开同步阻塞，大 diff 有被 bash 超时截断的风险。

## 6. 待办

- [ ] `opencode-xcheck` 用 grok-4.7-medium 尚未实跑（与 `/cr` 同路径，模型可用性已验证）。
- [ ] 3 轮以上循环出现「重复提已裁决项」时，给 prompt 增加「已裁决清单」参数。
- [ ] 若确认脚本稳定，考虑把 `cursor-agent login` 失效检测前置（当前失败信息已提示）。

## 7. 变更记录

- 2026-11-06 建立；删除旧的 `commands/cursor-review.md`（新方案取代），删除全局 `designer` / `critic` 两个 agent。
