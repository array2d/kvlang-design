# kvlang 运行时问题

| # | 文件 | 状态 | 问题 |
|---|------|------|------|
| 1 | [preamble_body_leak.md](preamble_body_leak.md) | ❌ 根因 | IfStmt.String() 多行 → inBody 匹配失败 |
| 2 | [block_label_dispatch.md](block_label_dispatch.md) | ❌ | block label 未注册函数签名，br/goto 不可达 |
| 3 | [kvspace_subcommand_verify.md](kvspace_subcommand_verify.md) | 📋 | kvspace 子命令验证 (4 个小问题) |
| 4 | [cli_commands_verify.md](cli_commands_verify.md) | 📋 | CLI 命令验证 (pipe/redirect 挂起, load 未实现) |

修复顺序：先 #1 → 再 #2。
