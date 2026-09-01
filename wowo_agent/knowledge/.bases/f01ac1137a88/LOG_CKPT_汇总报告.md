# Logs 与 Checkpoint 检查汇总报告

> 生成时间：2026-08-26
> 检查范围：
> - **日志**：`logs/`、`logs_old/`、`logs_pi05_pro/`、`logs_pi0_pro/`（infer/评测日志，含最终成功率）、`terminal/`（训练/分析日志）
> - **Checkpoint**：`checkpoints/` 下所有实验目录，检查是否包含「提示」(prompt，即 `vision_prompts` 参数)

---

## 一、结论摘要

| 项目 | 结果 |
|------|------|
| 检查的实验(checkpoint)数量 | 64 个实验目录，共 77 个任务子目录 |
| 包含提示 `vision_prompts` 的 checkpoint | **74 / 77**（绝大多数实验均含提示） |
| 不含提示的 checkpoint | `cluster-1-0-2000`（无已保存参数步）、`get_grads/get_all`、`get_grads/get_grads`（梯度分析用，非提示模型） |
| 专门提取提示的目录 | `checkpoints/prompts/spatial/.../{camera,env,light,noise}` 4 个变体，均含 `vision_prompts` |

**关于「提示」**：本项目在 pi0 模型上做 **prompt tuning**（可学习 `vision_prompts`，长度 5，`(5,2048)`）。训练后保存的 params 中带 `vision_prompts` 即视为该 ckpt 包含提示。本检查基于 params 的 `_METADATA`/`array_metadatas` 中是否含 `vision_prompt` 键进行判定（权威、且快）。

---

## 二、Checkpoint 是否包含提示（vision_prompts）

> 以下按实验目录列出。绝大多数实验包含多个子任务，均含提示。`√` 为目录名自带符号。

### 2.1 包含提示（vp=是）的实验（61 个实验目录）

| 实验目录 | 任务数 | 最大已存步数 | 含提示 |
|---|---|---|---|
| 3-spatial_cam1√ ~ cam9√ | 9 | 10000 | 是 |
| 3-spatial_env1 / env2 | 2 | 10000 / 1000 | 是 |
| 3-spatial_noise1√ ~ noise8√ | 8 | 10000 | 是 |
| cluster-0-0-1000 | 1 | 2999 | 是 |
| cluster-0-0-2000 | 1 | 2999 | 是 |
| cluster-0-0-4000（+ seed40） | 2 | 10000 / 5999 | 是 |
| cluster-1-0-1000 | 1 | 2999 | 是 |
| cluster-1-0-4000（+ seed40） | 2 | 10000 / 2000 | 是 |
| cluster-1-0-4000-s4 | 1 | 1000 | 是 |
| pi05_10_cam1~cam8 | 8 | 10000 | 是 |
| pi05_10_lgt4 / lgt5 | 2 | 10000 | 是 |
| pi05_goal_env1~env3 | 3 | 10000 | 是 |
| pi05_obj_cam1~cam5 | 5 | 10000 | 是 |
| pi05_obj_env | 1 | 10000 | 是 |
| pi05_obj_lgt1~lgt3 | 3 | 10000 | 是 |
| pi05_spatial_cam1~cam3 / camera | 6 | 10000 | 是 |
| pi05_spatial_env1 / env2 | 3 | 10000 | 是 |
| pi05_spatial_lan | 1 | 10000 | 是 |
| pi05_spatial_light / light2 | 2 | 10000 | 是 |
| pi05_spatial_no1~no3 / noise | 7 | 10000 | 是 |
| spatial-cam | 1 | 10000 | 是 |
| weight-test（weight-test / weight-test-k） | 2 | 10000 / 1000 | 是 |

### 2.2 不含提示 / 无已保存参数的实验

| 实验目录 | 任务 | 已存步数 | 说明 |
|---|---|---|---|
| cluster-1-0-2000 | cluster-1-0-2000 | 0 | 训练未产出任何已保存 params（空） |
| get_grads | get_all | 0 | 梯度分析输出，非提示模型 |
| get_grads | get_grads | 0 | 梯度分析输出，非提示模型 |

### 2.3 专门提取的提示目录 `checkpoints/prompts/`

| 路径 | 含提示 |
|---|---|
| .../camera | 是 |
| .../env | 是 |
| .../light | 是 |
| .../noise | 是 |

---

## 三、日志最终效果（成功率 / 训练指标）

> infer/评测日志统一以日志末尾的 **`Total success rate`**（总成功率）为最终效果；
> 未打印该行的表示评测未完成/中断（`NO_TOTAL_RATE`）。

### 3.1 `logs/`（共 50 个，29 个有最终成功率）

| 日志文件 | 总成功率 |
|---|---|
| 10000-libero_spatial_camera_20251224_131104 | 0.217 |
| libero_spatial_camera_20251225_004047 | 0.326 |
| libero_spatial_camera_20251225_005550 | 0.435 |
| libero_spatial_camera_20251225_063141 | 0.630 |
| libero_spatial_camera_20251225_133657 | 0.087 |
| libero_spatial_camera_20251226_021055 | 0.109 |
| libero_spatial_camera_20251226_024519 | 0.261 |
| libero_spatial_camera_20251226_112036 | 0.217 |
| libero_spatial_camera_20251227_012040 | 0.370 |
| libero_spatial_camera_20251227_012243 | 0.304 |
| libero_spatial_camera_20251227_012623 | 0.239 |
| libero_spatial_camera_20251227_025612 | 0.370 |
| libero_spatial_camera_20251228_152838 | 0.717 |
| libero_spatial_camera_20251230_234823 | 0.000 |
| libero_spatial_camera_20251231_020711 | 0.217 |
| libero_spatial_camera_20251231_031607 | 0.000 |
| libero_spatial_camera_20251231_101851 | 0.239 |
| libero_spatial_camera_20251231_103605 | 0.000 |
| libero_spatial_camera_20260103_102339 | 0.000 |
| libero_spatial_camera_20260103_125510 | 0.000 |
| libero_spatial_camera_20260103_131246 | 0.000 |
| libero_spatial_camera_20260103_135256 | 0.000 |
| libero_spatial_camera_20260106_105019 | 0.000 |
| libero_spatial_20251229_075139 | 0.940 |
| libero_spatial_20251231_071237 | 0.000 |
| libero_spatial_20251231_073749 | 0.000 |
| libero_spatial_20251231_080515 | 0.440 |
| libero_spatial_20251231_082541 | 0.720 |
| libero_spatial_20251231_095948 | 0.720 |
| （其余 21 个） | 未完成（NO_TOTAL_RATE） |

### 3.2 `logs_old/`（1 个）

| 日志文件 | 总成功率 |
|---|---|
| libero_spatial_camera_viewpoints_20251223_142227 | 0.771 |

### 3.3 `logs_pi05_pro/`（69 个，25 个有最终成功率）

| 子集 | 成功率范围（已完成的） |
|---|---|
| libero_spatial | 0.004 ~ 0.976（最高 0.976 / 0.978 / 0.938） |
| libero_goal | 0.086 ~ 0.976（最高 0.976 / 0.902 / 0.888） |
| libero_object | 0.000 ~ 0.986（最高 0.986 / 0.926 / 0.914） |
| libero_10 | 0.070 ~ 0.920（最高 0.920 / 0.724 / 0.670） |
| libero（基础） | 0.094 ~ 0.454 |
| libero-object-swap | 0.168 |

### 3.4 `logs_pi0_pro/`（16 个，全部有最终成功率）

| 子集 | 成功率 |
|---|---|
| libero_spatial | 0.09 / 0.97 / 0.97 / 0.00 |
| libero_goal | 0.756 / 0.146 / 0.952 / 0.098 |
| libero_object | 0.00 / 0.98 / 0.00 / 0.89 |
| libero_10 | 0.022 / 0.81 / 0.436 / 0.00 |

### 3.5 `terminal/`（训练/分析日志）

| 日志 | 类型 | 最终效果 |
|---|---|---|
| 3-spatial.log | 训练(prompt tuning) | step 1700，loss 0.0158 |
| cluster-0-0-1000.log | 训练 | step 2900，loss 0.0131 |
| cluster-0-0-2000.log | 训练 | step 2900，loss 0.0152 |
| cluster-0-0-4000.log | 训练 | step 10000，loss 0.0136 |
| cluster-1-0-2000.log | 训练 | step 2900，loss 0.0303 |
| cluster-1-0-4000.log | 训练 | step 10000，loss 0.0254 |
| cluster-1.log | 训练 | step 2900，loss 0.0335 |
| cluster-1-0-4000-s4.log | 训练 | **失败**（磁盘满 OSError 28） |
| weight-test.log | 训练 | step 1300，loss 0.0343 |
| grads.log | 梯度分析 | 已保存至 grad_analysis-0-all |
| mlp.log | MLP 推理测速 | 加载 4484ms / 推理 18ms，predicted class=[2] |
| mlp0.log | MLP 训练 | val acc=1.0000（loss 发散为负） |
| mlp8e-4.log | MLP 训练 | val acc=0.3750 |
| task-neg-300.log | MLP 训练 | val acc=1.0000（loss 发散为负） |

---

## 四、说明与备注

1. **提示(提示向量)判定**：`vision_prompts` 是 prompt tuning 新增的可学习参数 `(5, 2048)`，位于模型 params 顶层。判定依据为 params 检查点的 `_METADATA`/`array_metadatas/process_0` 是否含 `vision_prompt` 键，结果可靠。
2. 除 `cluster-1-0-2000`（训练无产物）和 `get_grads`（梯度分析输出）外，**所有实验 checkpoint 均包含提示**。
3. `logs/` 中大量 0.000 与未完成的日志为早期/失败的评测；`logs_pi05_pro`、`logs_pi0_pro` 记录了较理想的成功率（最高约 0.97~0.99）。
4. 详细原始数据见 `/tmp/opencode/ckpt_scan.json`（checkpoint 逐任务扫描结果）。
