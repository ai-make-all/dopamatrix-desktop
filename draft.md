@Codebase 我们的四大核心节点（ScriptGen, TTS, Subtitle, Compositor）已经全部独立测试完美通过！现在进入 Phase 4：全链路大一统。

任务 1：创建 AssemblyNode (拼装流水线)
请在 src/nodes/ 目录下创建 assembler.py，实现 AssemblyNode 类。
核心逻辑：
1. 读取 Context 中的 script_data JSON，计算所有 scene 的 duration 总和，得出视频总时长。
2. 动态构建 Timeline：
   - 创建一个 Video Track，把本地测试用的视频（例如 tests/assets/bg1.mp4）放进去。如果测试视频不够长，请在 ffmpeg 构建时使用 `-stream_loop -1` 或多次添加 Clip 来铺满总时长。
   - 遍历 Context 中的多语言变体（context.variants），把对应的配音文件（如 voice_ar.mp3）放入 Audio Track。
   - 将组装好的 Timeline 放回 Context。

任务 2：编写终极印钞机入口 run_factory.py
请在项目根目录下创建一个 run_factory.py。这是整个项目的入口。在这个脚本里：
1. 加载 .env 环境变量。
2. 初始化 WorkflowContext 和 WorkflowEngine。
3. 依次添加节点：ScriptGenNode -> TTSNode -> SubtitleNode -> AssemblyNode -> FFmpegCompositorNode。
4. 给出一个真实的 Prompt 塞入 Context：“帮我生成一个 15 秒的汽车减震器出海短视频，包含英文和阿拉伯语。”
5. 执行 engine.run(context) 启动全自动流水线。

请注意各节点之间数据结构的衔接，特别是不同语言的音频和字幕如何优雅地在 Compositor 中生成出不同语言的最终双语 MP4。请完成代码编写。