# AIStudioOS-Grok 使用说明书

产品定位见 `PRODUCT_CONSTITUTION.md`：人类直操；AI 可插拔；不绑定 Grok。

**边界（请先读）：** 生产级 7×24 为 **NOT ACCEPTED**。下面的有界演示使用仓库内写死的脚本工人/验收，属于 **scaffold**，不等于自治、自己拆活或自我迭代。聊天窗口里的 AI 只是可插拔部件，不是完成本闭环所必需的。

## 1. 环境

```bash
git clone https://github.com/shugnn/AIStudioOS-Grok.git
cd AIStudioOS-Grok
# 若使用工人分支上的本闭环：git checkout bot/human-direct-control-min
python3 -m venv .venv && source .venv/bin/activate   # Windows 用对应激活方式
pip install pytest
export PYTHONPATH="$PWD"
```

## 2. 本机直操最小闭环（有界、离线、零费用）

只需本说明书与仓库，即可：启动一个有界目标、授权、查看状态、跑完、急停。不必打开任何聊天窗口。

状态文件默认是 `control_plane/state.json`（运行时生成，不要提交）。

### 2.1 启动

```bash
python -m control_plane start
```

会创建一个演示目标（预算封套 $1，任务估价与实际花费均为 $0），并提出（尚未批准）两个离线任务：词数统计、checksum。输出中的 `[scaffold]` 提示不可省略理解。

### 2.2 查看状态

```bash
python -m control_plane status
```

列出急停开关、预算、目标与任务、权限策略。

### 2.3 授权

人类批准待处理任务后，执行轨才会跑它们（`run` 不会自动批准）：

```bash
python -m control_plane authorize
# 或逐条：python -m control_plane approve <task_id>
```

其它已有授权动作：

```bash
python -m control_plane raise-budget 0          # 提高预算上限（本演示为 $0，通常不必）
python -m control_plane policy                  # 查看策略
python -m control_plane unblock <task_id>       # 解阻被预算/策略挡住的任务
```

### 2.4 跑一轮并完成该有界目标

```bash
python -m control_plane run
python -m control_plane status
```

`run` 只处理 **已授权（approved）** 的任务：脚本工人写出 `artifacts/human_loop/` 下的产物，独立脚本验收器复算后接受或拒绝。两个任务均被接受且花费为 $0 时，目标标记为 completed（封套未动用，Hard-stop 应为 False）。

只处理一条任务时用 `python -m control_plane run --once`。

### 2.5 急停

```bash
python -m control_plane emergency-stop --reason "founder halt"
python -m control_plane status          # Armed: True
python -m control_plane run             # 必须拒绝新工作，退出码 3
python -m control_plane clear-stop      # 解除
```

等价的文件方式（同一开关）：

```bash
echo stop > docs/progress/EMERGENCY_STOP   # 开
rm -f docs/progress/EMERGENCY_STOP          # 关
```

急停文件本身不要提交。`l1_runner` 在该文件存在时同样以退出码 3 拒绝新作业。

## 3. 健康检查（可选）

```bash
python -m pytest tests/ -q
python scripts/health_check.py
```

## 4. 角色后端配置（插拔方向）

配置文件：`config/role_backends.yaml`（见仓库）。

- `manager: script|llm|null`
- `worker: script|llm|null`
- `verifier: script|llm|null`

当前默认以 **script** 为主；**llm** 为占位，接入具体厂商时只加适配器，不改控制平面核心。本闭环的 `start`/`run` 走的就是 script 脚手架，不是已完工的可插拔验收。

## 5. 其它脚手架业务（非本闭环证据，非自治）

```bash
# 离线多角色演示（scaffold）
python experiments/exp05-us-equity-lab/run_offline_pipeline.py

# 免费源采集基线（需本机网络；非自治 PASS）
pip install -r experiments/exp05-us-equity-lab/requirements-exp05.txt
python experiments/exp05-us-equity-lab/run_live_pipeline.py
```

## 6. 证据与边界

- Issue #9 为审计主场
- 零默认付费；不改 ChatGPT 仓
- 生产 7×24：**NOT ACCEPTED**
- scaffold ≠ 自治 / 自己拆活 / 自我迭代
- 本节最小闭环只证明：人类可以凭本说明书完成 **一个预置的有界离线目标**；任意新目标的拆活与实现仍未具备
