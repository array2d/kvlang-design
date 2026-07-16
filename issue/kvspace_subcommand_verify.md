# kvspace 子命令验证报告

**验证日期**: 2026-07-10  
**方式**: 运行真实 KV 程序后，逐个子命令 + 边界参数验证

## 子命令一览

| 命令 | 参数 | 状态 | 备注 |
|------|------|------|------|
| `get <key>` | key | ✅ | 不存在返回 `redis: nil` exit=1 |
| `mget <k1..kN>` | 1+ keys | ✅ | nil key 显示 `(nil)` |
| `set <key> <val>` | key+val | ✅ | 空格/JSON/Unicode/空值 均正常 |
| `del <k1..kN>` | 1+ keys | ✅ | 批量删除 |
| `list <prefix>` | prefix | ✅ | 空目录返回空 |
| `tree <prefix>` | prefix | ✅ | 递归树形显示 |
| `dump <prefix>` | prefix | ✅ | key=value，换行→`↵`，>80截断 |
| `watch <key> [--timeout d]` | key, opt timeout | ✅ | 无效值报错退出（已修） |
| `notify <key> <val>` | key+val | ✅ | 可唤醒 BLPOP watcher |
| `clear` | — | ✅ | 清空 7 个 root |
| `--addr host:port` | 全局 | ✅ | 缺 host:port 格式校验报错（已修） |

## 发现的问题

### 🟡 1. `--timeout` 无效值不报错

```bash
$ kvlang kvspace watch /key --timeout invalid
# time.ParseDuration 失败 → timeout=0 (永久阻塞)，无提示
```

**文件**: `cmd/kvlang/kvspace.go:81-87`  
**修复**: `ParseDuration` 失败时打印错误并退出

### 🟡 2. `--addr` 漏值时参数错位

```bash
$ kvlang kvspace --addr get /test
# → unknown kvspace subcommand: /test
# --addr 吞掉 "get" 当地址，"/test" 被当子命令
```

**文件**: `cmd/kvlang/kvspace.go:17-24`  
**修复**: 校验 `--addr` 的下一个参数不以 `-` 开头且不是子命令名

### 🟡 3. 连接失败 Redis pool 日志噪音

`kvlang kvspace --addr bad:port get /key` → 打印 10 行 `redis: connection pool: failed to dial` 后才显示最终错误。底层 go-redis pool 重试日志未静默。

### 🟡 4. `dump` 80 字符硬截断

长值截断到 80 字符 + `…`，无参数控制。建议加 `--full` 选项。

## 实测数据

使用 `calc(5,3)` KV 程序运行后验证：

```
get /vthread/run        → {"pc":"[1,0]","status":"done"}
get /vthread/run/out    → 16                        (5+3=8, 8*2=16 ✓)
get /src/func/calc      → def calc(A:int, B:int) -> (R:int)
tree /src/func          → calc/_block_1/ + pre_main/_block_1/
```
