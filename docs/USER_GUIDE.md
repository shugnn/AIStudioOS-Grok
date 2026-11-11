# AIStudioOS-Grok 使用说明书（纠偏后）

产品定位见 `PRODUCT_CONSTITUTION.md`：人类直操；AI 可插拔；不绑定 Grok。

## 1. 环境

```bash
git clone https://github.com/shugnn/AIStudioOS-Grok.git
cd AIStudioOS-Grok
python3 -m venv .venv && source .venv/bin/activate   # Windows 用对应激活方式
pip install pytest
export PYTHONPATH="$PWD"
```

## 2. 人类直操：健康检查

```bash
python -m pytest tests/ -q
python scripts/health_check.py
```

这两条都不是 72h 开工，也不是 L2-2 验收。`health_check.py` 退出码 0 只表示本地检查和未开工脚手架检查通过（`NOT_STARTED`，门控保持 false，生产 7×24 仍为 **NOT ACCEPTED**）。

## 3. 人类直操：急停

```bash
echo stop > docs/progress/EMERGENCY_STOP   # 开
rm -f docs/progress/EMERGENCY_STOP          # 关
```

## 4. 角色后端配置（插拔方向）

配置文件：`config/role_backends.yaml`（见仓库）。

- `manager: script|llm|null`  
- `worker: script|llm|null`  
- `verifier: script|llm|null`  

当前默认以 **script** 为主；**llm** 为占位，接入具体厂商时只加适配器，不改控制平面核心。

## 5. 脚手架业务（非自治证据）

```bash
# 离线多角色演示
python experiments/exp05-us-equity-lab/run_offline_pipeline.py

# 免费源采集基线（需本机网络；非自治 PASS）
pip install -r experiments/exp05-us-equity-lab/requirements-exp05.txt
python experiments/exp05-us-equity-lab/run_live_pipeline.py
```

## 6. 证据与边界

- Issue #9 为审计主场  
- 零默认付费；不改 ChatGPT 仓  
- 生产 7×24：未验收  
