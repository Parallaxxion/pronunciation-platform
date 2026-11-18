# 联调工具

目录：`integration/` 是纯 Python 适配代码，`scripts/` 是命令行入口，`tests/` 是公共逻辑检查。全部从总仓库根目录运行，无需安装第三方 Python 包。

```bash
python -m unittest discover -s 04_接口说明/联调工具/tests -v
python 04_接口说明/联调工具/scripts/check_algorithm_kit.py
python 04_接口说明/联调工具/scripts/check_repository.py
python 04_接口说明/联调工具/scripts/preview_ui.py
```

题目与诊断转换命令见[数据契约](../数据契约.md)，真实服务对接见[联调步骤](../联调步骤.md)。转换结果放在根目录 `local-data/`，该目录被 Git 忽略。

作为模块使用时，将本“联调工具”目录加入 Python 模块搜索路径，再 `from integration.adapters import ...`；CLI 已自动设置自己的导入位置。不要将样例转换结果视为真实服务验收。

归档校验只核对初始来源的 124 个归档文件，不限制三个“当前开发”目录的后续修改。需要重建专项交接包时执行：

```bash
python 04_接口说明/联调工具/scripts/package_handoff.py
```
