# 跨组交接包

- `frontend-handoff-20261118.zip`：原UI基线、共享样式和偏误组件预览。
- `algorithm-format-kit-20261118.zip`：4条合成标准WAV、原始音频、清单与真实测试登记模板。
- `SHA256SUMS`：压缩包校验值。

算法包用于格式联调，gold_errors为null。不能用它报告检测准确率。前端包需要通过HTTP打开；包内README说明启动方式。

可在总仓库执行 `python 04_接口说明/联调工具/scripts/package_handoff.py` 重建两份包。子系统完整源码保存在三个小组目录的“当前开发”和周次归档中，不打进这两份专项交接包。
