# AI 员工手册

更新时间：2026-07-03

本文件记录长期协作规则。只有工作规则、沟通方式、流程或红线发生变化时才更新本文件。

## 沟通方式

- 默认使用中文沟通。
- 先读项目记忆文件，再动代码或跑实验。
- 发现信息不确定时，必须标注“待确认”，不要自行补全。
- 遇到风险、歧义或可能影响主线结果的改动，先说明判断依据。
- 给用户的结论要区分事实、推断和建议。
- 长时间任务中需要持续同步当前在做什么、发现了什么、下一步是什么。

## 工作流程

1. 阅读顺序优先为：`AGENTS.md`、`PROJECT.md`、`STATUS.md`、`DECISIONS.md`、`HANDOFF.md`、`PROJECT_HANDOFF.md`。
2. 开始重要工作前，先确认当前目标、相关脚本、输入输出路径和验收标准。
3. 改代码前先读相关文件，不凭记忆直接改。
4. 修改范围要尽量小，优先沿用现有项目结构和脚本风格。
5. 完成重要工作后，同步更新 `PROJECT.md`、`STATUS.md`、`DECISIONS.md` 和 `HANDOFF.md`。
6. 只有工作规则变化时才更新 `AGENTS.md`。
7. 如果测试或实验无法执行，必须记录原因和待补验证项。

## 长期规则

- `alpr_topk_capture.py` 是 Windows 基准主线，不要随意修改。
- Windows 实验优先使用 `alpr_topk_capture_demo.py`。
- RK3588 板端优化重点是 `rk3588_topk_capture.py`。
- 当前 OCR 主推 HyperLPR3。
- `ocr-engine none` 或显示 `PLATE` 只是诊断模式，不是最终目标。
- 新板 MIPI 不出帧当前判断为硬件、驱动、设备树、sensor、供电、接口或 IQ/ISP 链路问题，不要误判为 ALPR 主代码问题。
- 板端视频测试至少跑到 frame 1000，不能只看前几百帧就下结论。
- 浏览器显示的是 `/tmp/frame.jpg`，可能是旧帧，不代表识别程序一定正在运行。
- RK 端不能机械复刻 Windows，需要围绕算力、NPU、MIPI 和实时性设计流程。

## 绝对红线

- 不得删除、覆盖或回滚用户已有工作，除非用户明确要求。
- 不得在信息不确定时编造板端状态、实验结果、模型效果或摄像头结论。
- 不得把 `ocr-engine none`、`PLATE` 占位显示当作真实车牌识别完成。
- 不得把 MIPI 0 字节出帧问题草率归因到 Python、模型或 ALPR 逻辑。
- 不得未经说明就污染 Windows 基准主线 `alpr_topk_capture.py`。
- 不得把未验证的 deblur 收益直接接入 RK 实时主链路。
- 不得忽略 rejected 样本、summary、vote history 等诊断信息就下优化结论。
