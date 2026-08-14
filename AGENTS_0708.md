# AI 员工手册

更新时间：2026-07-08

本文件记录长期协作规则。只有沟通方式、工作流程、长期规则或红线发生变化时才更新本文件。

## 沟通方式

- 默认使用中文沟通。
- 先读项目记忆文件，再动代码或跑实验。
- 发现信息不确定时，必须标注“待确认”，不要自行补全。
- 遇到风险、歧义或可能影响主线结果的改动，先说明判断依据。
- 给用户的结论要区分事实、推断和建议。
- 长时间任务中需要持续同步当前在做什么、发现了什么、下一步是什么。

## 工作流程

1. 新对话优先阅读：`AGENTS_0708.md`、`PR0JECT_0708.md`、`STATUS_0708.md`、`DECISIONS_0708.md`、`HANDOFF_0708.md`、`NEW_CHAT_HANDOFF_20260708.md`。
2. 开始重要工作前，先确认当前目标、相关脚本、输入输出路径和验收标准。
3. 改代码前先读相关文件，不凭记忆直接改。
4. 修改范围要尽量小，优先沿用现有项目结构和脚本风格。
5. 每完成一项重要工作，同步更新 `PR0JECT_0708.md`、`STATUS_0708.md`、`DECISIONS_0708.md` 和 `HANDOFF_0708.md`。
6. 只有工作规则变化时才更新 `AGENTS_0708.md`。
7. 如果测试或实验无法执行，必须记录原因和待补验证项。

## 长期规则

- `alpr_topk_capture.py` 是 Windows 基准主线，不要随意修改。
- Windows 实验优先使用 `alpr_topk_capture_demo.py`。
- RK3588 板端主流程重点是 `rk3588_topk_capture.py`。
- 本地 IMX585 板的 MIPI 调试参考脚本是 `rk3588_topk_capture_mipi_debug.py`。
- 远程 SC850SL 板的实时摄像头调试主脚本是后补的 `rk3588_topk_capture_mipi_debug_sc850.py`。
- 当前 OCR 主推 HyperLPR3。
- `ocr-engine none`、`PLATE` 或 `LOCK PLATE` 只是诊断/占位模式，不是最终目标。
- 板端视频测试至少跑到 frame 1000，不能只看前几百帧就下结论。
- 浏览器显示的是 `/tmp/frame.jpg`，可能是旧帧，不代表识别程序一定正在运行。
- RK 端不能机械复刻 Windows，需要围绕算力、NPU、MIPI、ISP 和实时性设计流程。

## 绝对红线

- 不得删除、覆盖或回滚用户已有工作，除非用户明确要求。
- 不得在信息不确定时编造板端状态、实验结果、模型效果或摄像头结论。
- 不得把 `ocr-engine none`、`PLATE`、`LOCK PLATE` 占位显示当作真实车牌识别完成。
- 不得把 MIPI、ISP、0 字节出帧或摄像头图像问题草率归因到 Python、模型或 ALPR 主逻辑。
- 不得未经说明就污染 Windows 基准主线 `alpr_topk_capture.py`。
- 不得直接污染 `rk3588_topk_capture_mipi_debug.py`；SC850SL 适配应放在 `rk3588_topk_capture_mipi_debug_sc850.py`。
- 不得把未验证的 deblur 收益直接接入 RK 实时主链路。
- 不得忽略 rejected 样本、summary、run_summary、vote history 等诊断信息就下优化结论。
