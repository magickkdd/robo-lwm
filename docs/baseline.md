# Robo-LWM 基线成绩（Baseline v1）

> 这是后续改进的对照基线。除非特别说明，后续比较都应使用完全相同的 suite、模型、预算和评测口径。

## 0. 基线信息

| 项 | 值 |
| :--- | :--- |
| 记录日期 | 2026-11-12 |
| 代码基线 | `df51018` + 工作区未提交改动（外部提交门控、文档更新） |
| Agent | `DefaultAgent`（mini-swe-agent 内核） |
| 模型 | `gpt-6-luna`，`reasoning_effort=none`，request timeout 180s，最多 3 次重试 |
| 仿真 | LIBERO，Franka Panda，固定 `init_states[0]`，MuJoCo OSMesa，256×256 录像 |
| 预算 | `max-turns=40`，`try-cap=10`，墙钟 `timeout=1200s` |
| 成功判定 | LIBERO 原生 `check_success()`；至少一次 try 成功才接受提交 |
| 任务数 | `libero_object` 10 个；`libero_10`（Long）10 个 |
| 运行次数 | 每个任务 1 次（单 seed / 固定初始状态） |

## 1. 总览

| Suite | 成功 / 总数 | 任务成功率 | 总 tries | 总轮数 | 总耗时 |
| :--- | ---: | ---: | ---: | ---: | ---: |
| LIBERO-Object (`libero_object`) | 8 / 10 | **80.0%** | 14 | 40 | 1660.5s |
| LIBERO-Long (`libero_10`) | 3 / 10 | **30.0%** | 80 | 201 | 7160.5s |
| **合计** | **11 / 20** | **55.0%** | 94 | 241 | 8820.5s（约 147 分钟） |

## 2. LIBERO-Object 明细（`runs/eval1`）

| task | 任务 | 结果 | tries | 轮数 | 步数 | 耗时(s) |
| ---: | :--- | :---: | ---: | ---: | ---: | ---: |
| 0 | alphabet soup → basket | ✅ | 1 | 4 | 181 | 274.1 |
| 1 | cream cheese → basket | ✅ | 1 | 5 | 173 | 356.2 |
| 2 | salad dressing → basket | ✅ | 3 | 4 | 152 | 233.0 |
| 3 | bbq sauce → basket | ❌ | 1 | 3 | 220 | 99.1 |
| 4 | ketchup → basket | ❌ | 2 | 3 | 220 | 151.3 |
| 5 | tomato sauce → basket | ✅ | 1 | 4 | 167 | 102.1 |
| 6 | butter → basket | ✅ | 1 | 4 | 166 | 82.6 |
| 7 | milk → basket | ✅ | 1 | 3 | 169 | 83.9 |
| 8 | chocolate pudding → basket | ✅ | 1 | 4 | 156 | 81.9 |
| 9 | orange juice → basket | ✅ | 2 | 6 | 174 | 196.3 |

- 成功任务平均 tries：1.375
- 成功任务平均步数：167.2
- 成功视频：`runs/eval1/libero_object_{0,1,2,5,6,7,8,9}/artifacts/video.mp4`

> 注意：Object 这轮评估发生在“外部提交门控”修复**之前**。task 3/4 的失败原因是 agent 在 episode 失败后把提交哨兵链在命令末尾，提前结束，而不是跑满 try 预算。修复后在 `runs/eval2` 单独重跑，task 3（1 try）和 task 4（3 tries）都成功。因此 Object 的 8/10 是**旧门控下的原始基线**；当前代码若完整重跑，预计会高于 8/10，但尚未做单轮全量验证。

## 3. LIBERO-Long 明细（`runs/long1`，`libero_10`）

| task | 任务 | 结果 | tries | 轮数 | 步数 | 耗时(s) | 退出状态 |
| ---: | :--- | :---: | ---: | ---: | ---: | ---: | :--- |
| 0 | alphabet soup + tomato sauce → basket | ✅ | 3 | 4 | 390 | 270.3 | Submitted |
| 1 | cream cheese box + butter → basket | ✅ | 6 | 8 | 500 | 731.9 | Submitted |
| 2 | turn on stove + moka pot | ❌ | 10 | 22 | 245 | 579.1 | TrialBudgetExhausted |
| 3 | black bowl → bottom drawer + close | ❌ | 10 | 40 | 275 | 643.4 | LimitsExceeded |
| 4 | two mugs → left/right plates | ❌ | 10 | 19 | 500 | 662.9 | TrialBudgetExhausted |
| 5 | book → back compartment of caddy | ❌ | 10 | 27 | 230 | 762.5 | RepeatedFormatError |
| 6 | mug → plate + pudding → right of plate | ❌ | 10 | 15 | 350 | 1052.5 | TrialBudgetExhausted |
| 7 | alphabet soup + cream cheese box → basket | ✅ | 3 | 4 | 375 | 283.3 | Submitted |
| 8 | two moka pots → stove | ❌ | 10 | 40 | 330 | 943.9 | LimitsExceeded |
| 9 | mug → microwave + close | ❌ | 8 | 22 | 384 | 1230.7 | TimeExceeded |

- 成功任务平均 tries：4.0
- 成功任务平均步数：421.7
- 成功视频：`runs/long1/libero_10_{0,1,7}/artifacts/video.mp4`

### 失败模式

| 退出状态 | 数量 | 含义 |
| :--- | ---: | :--- |
| `TrialBudgetExhausted` | 3 | 10 次 try 用完仍无成功，提交被外部门控拒绝 |
| `LimitsExceeded` | 2 | 40 轮 LLM 预算耗尽 |
| `RepeatedFormatError` | 1 | 连续 3 次模型输出格式错误 |
| `TimeExceeded` | 1 | 墙钟 1200s 耗尽 |

所有失败都在**预算耗尽后**结束，没有出现“失败后立即提交”的提前终止。

## 4. 基线口径与改进判定

后续改进必须使用同一口径：

- 同一 suite、同一任务列表、同一模型、同一预算；
- 每个任务单次运行，固定 `init_states[0]`；
- 成功只看 LIBERO 原生 `check_success()`；
- 报告任务成功率，同时报告 tries / 轮数 / 耗时；
- 不允许通过提前终止、跳过失败任务、减少任务数来提高分母外的成功率。

建议的“idea work”判定：

| 判定 | 条件 |
| :--- | :--- |
| 强提升 | Object > 80% 且 Long > 30%，或合计 > 55%，且无 suite 回退 |
| 局部提升 | 任一 suite 提升 ≥ 1 个任务，另一个 suite 不回退 |
| 效率提升 | 成功率相同，但平均 tries 或轮数显著下降 |
| 不成立 | 任一 suite 回退，或需要放宽预算/换更强模型才成立 |

> 由于 Object 基线是在旧提交门控下测的，严格比较时应先用当前代码重跑 Object 全套，再与 Long 一起作为新的 v1.1 基线；本文保留原始测量值，避免事后修改基线。

## 5. 复现命令

```bash
cd /home/czx/RoboLWM

# Object
.venv/bin/python runner.py --stage eval1 --suite libero_object --all \
    --max-turns 40 --try-cap 10 --camera 256 --timeout 1200

# Long（libero_10）
.venv/bin/python runner.py --stage long1 --suite libero_10 --all \
    --max-turns 40 --try-cap 10 --camera 256 --timeout 1200
```

> `runs/` 已在 `.gitignore` 中，原始 run 数据不会进入版本库；本文件是唯一的基线成绩记录。
