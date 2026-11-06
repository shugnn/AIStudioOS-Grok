# AIStudioOS-Grok 使用说明书

**适用：** 创始人 / 维护者在本机（Windows 或 Ubuntu）操作本仓库  
**约束：** 零新增付费（默认）、不改 ChatGPT 仓库、重要事项写 GitHub Issue/PR  
**更新：** 2026-11-07

---

## 1. 环境准备

### 1.1 共同要求

- Git  
- Python 3.10+（Ubuntu 实测 3.12；Windows 曾用 3.14）  
- 仓库：`https://github.com/shugnn/AIStudioOS-Grok`  

### 1.2 Ubuntu 示例

```bash
cd ~/work
git clone https://github.com/shugnn/AIStudioOS-Grok.git
cd AIStudioOS-Grok
python3 -m venv .venv
source .venv/bin/activate
pip install pytest
# 按需再装业务依赖（开网采集前会在实验目录说明）
export PYTHONPATH="$PWD"
```

### 1.3 Windows 示例

```powershell
cd D:\work\AIStudioOS项目-Grok
git pull
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install pytest
$env:PYTHONPATH = (Get-Location).Path
```

---

## 2. 五分钟健康检查

```bash
export PYTHONPATH="$PWD"   # Windows 用 $env:PYTHONPATH
python -m pytest tests/ -q
python scripts/health_check.py
```

期望：测试通过；`health_check` 中 `overall_ok: true`。

---

## 3. 日常概念

| 名称 | 含义 |
|------|------|
| 控制平面 | 目标/任务/预算/权限/检查点 |
| L1 | 本机带锁的一轮执行入口 |
| 急停 | 创建 `docs/progress/EMERGENCY_STOP` 后 L1 应停止 |
| 浸泡 soak | 有界重复跑，用于观察稳定性；看 with_work 不要只看 exit0 |
| 监督 | 盯进度的机制；短中断记缺口，长中断才算监督失败 |

---

## 4. 常用命令

### 4.1 跑一轮 L1

```bash
python scripts/l1_runner.py --job auto_loop_once
```

### 4.2 短浸泡（示例）

```bash
python scripts/soak_2h.py --cycles 10 --interval 5 --via-l1 --idle-policy reseed
```

### 4.3 急停

```bash
# 开启急停
echo stop > docs/progress/EMERGENCY_STOP
# 解除
rm -f docs/progress/EMERGENCY_STOP
```

### 4.4 急停 / 强杀恢复演练（已有脚本）

```bash
python scripts/run_emergency_stop_drill.py
python scripts/run_recovery_drill.py
```

### 4.5 监督注入（R3，约 5+ 分钟）

```bash
python scripts/run_r3_injection.py
```

---

## 5. 业务实验 Exp-05（美股多角色 · 研究用）

### 5.1 离线（默认，不联网）

```bash
python experiments/exp05-us-equity-lab/run_offline_pipeline.py
```

查看：`experiments/exp05-us-equity-lab/results/offline_run/`

### 5.2 开网采集（需创始人批准）

**状态：** 创始人已原则批准「仅免费源开网」。  
**实装原则：**

1. 仍禁止付费 API、禁止自动下单  
2. 先在文档与代码中钉死源列表与限速  
3. 数据只写入本实验目录下的 datalake  
4. 权限门：仅开放采集所需网络，不开放无关外连  

具体开网采集命令将在 `experiments/exp05-us-equity-lab/README.md` 的「Live ingest」小节随代码一并提供（本说明书发布时以离线为准）。

### 5.3 产出如何理解

- 短线/中线观察池、策略草案 = **研究与工程压测产物**  
- **不是**投资建议，**不**构成交易指令  

---

## 6. 证据与 GitHub

- 重要结论写在 **Issue #9**  
- 交叉审查 ChatGPT 轨时评论其 Issue #11，**不改对方代码**  
- 大日志可留本机；关键 `metrics` / 演练 JSON 尽量入库  

推送示例：

```bash
git add docs/progress/drills/ experiments/exp05-us-equity-lab/results/
git commit -m "evidence: ..."
git push origin main
```

GitHub 已不接受账户密码，请使用 **Personal Access Token** 或 SSH。

---

## 7. 双机注意

| 机器 | 说明 |
|------|------|
| Windows | 曾做计划任务与 D1；壳层不稳定时勿高频弹控制台任务 |
| Ubuntu | 推荐长跑与 Exp-05；路径示例 `~/work/AIStudioOS-Grok` |

两台机器的锁与 `docs/progress` **不要混用同一目录**。

---

## 8. 故障速查

| 现象 | 处理 |
|------|------|
| `No module named pytest` | venv 内 `pip install pytest`，勿破坏系统 Python |
| `externally-managed-environment` | 用 venv，不要 `--break-system-packages` |
| git pull 合并未完成 | `git status`；确认无要留文件后可用 `git reset --hard origin/main` |
| 指标与 summary 对不上 | 是否短演练覆盖了长跑的 metrics；对照归档文件 |
| 急停后无法跑 | 删除 `docs/progress/EMERGENCY_STOP` |

---

## 9. 版本与宣称

- 工程证据：见 `docs/progress/` 与 Issue #9  
- **生产级 7×24：未验收，禁止对外宣称已实现**  

---

## 10. 获取帮助

1. 先查本说明书与 `docs/PRODUCT.md`  
2. 再查 Issue #9  
3. 需授权的事项（开网范围、实盘相关、付费）单独向创始人书面确认  
