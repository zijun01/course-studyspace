# Course Studyspace

一个运行在课程网页里的 Chrome 学习侧栏：

- 直接读取课程已有音频，无需播放课程即可用 Apple Metal 加速的 MLX Whisper `large-v3-turbo` 转写
- 首次转写后由 Codex 按整课语义整理标点、语句和口语冗余
- 点击音频文字语块播放对应范围，再次点击暂停或继续，到语块末尾自动停止
- 页面原文逐字逐换行保留且不可播放
- 按九大课程类别和小课程目录保存原始稿、阅读稿与笔记
- 同类别课程共享 Codex 工作区记忆，不同类别相互隔离
- 已处理课程直接读取缓存，不重复转写或重复润色
- 转写按课程内容项保存检查点；切换课程、关闭网页或服务中断后可继续

> 音频只在本机下载、转写并删除临时文件。语义润色和右侧 Agent 会把必要的文字上下文发送给已登录的 Codex 模型服务。

## 文件位置

- Chrome 扩展：`extension/`
- 本机服务：`local_server.py`
- 文字稿数据：首次运行后生成在 `data/transcripts/`
- 分类课程库：`library/<课程类别>/courses/<课程编号-标题>/`
- 临时音频：系统临时目录；每段处理结束后删除

`data/`、`library/`、`models/` 和 `research/` 包含本机生成内容或私人学习材料，默认不会提交到 Git。

## 启动本机转写服务

在终端进入本目录后运行：

```bash
./.venv-mlx/bin/python local_server.py
```

如果需要使用另一个 Whisper 环境作为备用，可以设置：

```bash
export OPENAI_WHISPER_PYTHON="$HOME/Projects/whisper-batch/.venv-uv/bin/python"
```

看到 `http://127.0.0.1:4317` 后保持终端窗口打开。

## 在 Chrome 加载扩展

1. 打开 `chrome://extensions/`。
2. 打开右上角“开发者模式”。
3. 点击“加载已解压的扩展程序”。
4. 选择本项目中的 `extension` 文件夹。
5. 打开课程页，在类别下拉框确认系统识别结果。
6. 首次点击“生成整节文字稿”；以后重新打开会直接读取本机缓存。

## 当前边界

- 首次处理会下载课程音频到系统临时目录；最高质量模型已保存在 `models/whisper-large-v3-turbo/`，无需重复下载。
- MLX 或 Metal 不可用时，服务会自动调用原有 OpenAI Whisper `turbo` 作为备用。
- Codex 临时断网时，本机原始稿和降级阅读稿仍会保存；页面会显示“重试语义整理”，重试不会重新运行 Whisper。
- 多门课程可以先后加入后台队列；Whisper 会串行处理，页面切换不会混淆课程数据。
- 网站无法明确提供课程类别时，需要在生成前手动修正一次类别下拉框。
