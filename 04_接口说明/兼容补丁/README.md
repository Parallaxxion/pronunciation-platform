# 命题前端兼容补丁

`proposition-items.patch` 修正命题前端读取题目列表时的 `questions` / `items` 差异。它是交接补丁，当前开发和归档均未自动应用，需命题组检查后采用。

在总仓库根目录执行检查：

```bash
git apply --check --directory=02_命题端/当前开发 04_接口说明/兼容补丁/proposition-items.patch
```

确认当前版本仍适用后，以同样命令去掉 `--check` 应用到“当前开发”，再运行命题页面联调并提交 PR。若补丁已合入或代码变化导致检查失败，先比较差异，勿重复应用。归档快照保持原样。
