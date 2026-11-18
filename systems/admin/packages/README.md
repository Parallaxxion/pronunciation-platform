# 第一周完整离线成果包

[下载第一周成果包](https://github.com/Parallaxxion/-cowork/blob/main/packages/week-01-20261116.zip)，进入文件页后使用下载按钮。也可以在仓库首页选择Code、Download ZIP获取整个仓库。

`week-01-20261116.zip` 是2026年11月16日的阶段快照，包含源码、合成音频、需求和接口文档、三人分工、PPT与讲稿、截图和验证证据。解压后从根目录README开始阅读。

`week-01-20261116.zip.sha256` 用于核对完整压缩包。包内的 `MANIFEST.sha256` 列出每个文件的相对路径与SHA-256，`week-01-20261116-files.json` 记录各文件大小与校验值。

维护者可以在仓库根目录运行：

```bash
python3 scripts/package_week01.py
```

Windows使用 `py -3 scripts/package_week01.py`。脚本会重新生成本周包，因此后续阶段应使用新的报告与包名。个人数据库、缓存、凭证、构建备份及老师的大型参考压缩包不包含在离线成果包中。
