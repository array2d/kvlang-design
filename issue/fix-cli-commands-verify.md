# kvlang CLI 命令验证报告

**验证日期**: 2026-07-10
**二进制**: ./kvlang

## 命令一览

| 命令 | 用法 | 状态 | 说明 |
|------|------|------|------|
| run file | kvlang <file.kv> | ✅ | 正确执行，输出一致 |
| -c inline | kvlang -c "code" | ✅ | 需正确引号，heredoc 最可靠 |
| pipe | echo "code" \| kvlang | ❌ | 挂起不返回 |
| redirect | kvlang < file.kv | ❌ | 挂起不返回 |
| serve | kvlang (无参数) | ⚠️ | daemon 启动但 VM 未注册到 /sys/vm/0 |
| vet | kvlang vet <file.kv> | ✅ | 语法检查正常 |
| kvspace | kvlang kvspace <cmd> | ✅ | 所有子命令正常 |
| load | kvlang load <file.kv> | ❌ | 未实现 |

## 详细验证

### ✅ run file

```bash
$ kvlang /tmp/run_test.kv
run: 2 + 5 * 5 = 35
```

线性代码正确执行，函数注册、调用、print 均正常。

### ✅ -c inline

```bash
$ kvlang -c "$(cat << 'EOF'
def test(X:int) -> (R:int) {
    X + 1 -> "./R"
    print("inline:", X, "+1=", "./R") -> "./_"
}
str.set("kvlangrun") -> "./term"
test(99) -> "./out"
EOF
)"
inline: 99 +1= 100
```

需注意 shell 引号转义。多行代码用 heredoc 传入最可靠。

**已知限制**: -c 只接收单个参数 args[1]，多行代码需在单变量中传递。

### ❌ pipe / redirect — 挂起

```bash
$ echo 'def test(X:int)->(R:int){...}' | kvlang
# 挂起，不返回，需 kill
```

isTerminal() 检测为 false → 进入 modePipe → runCode(name, os.Stdin) → 进程挂起。

**推测原因**: runCode 内部可能阻塞在 Redis 连接池或 stdin 读取上。

### ⚠️ serve (daemon)

```bash
$ kvlang &
$ kvlang kvspace get /sys/vm/0
# NOT FOUND — VM 注册缺失
$ kvlang kvspace get /sys/heartbeat/vm:0
# 心跳存在
```

- 心跳正常（2s 间隔写入 /sys/heartbeat/vm:0）
- Worker 正常启动（Pick + RunWorker 循环）
- 但 /sys/vm/0 未注册 → registerVM 调用了 kv.Set 但 key 未持久化或被清理

### ❌ load — 未实现

main.go 无 load 子命令处理。loadFunctions() 是内部函数（在 runFile 中调用），仅加载不执行功能已存在但无 CLI 入口。

**需添加**:
```go
// main.go switch 中添加
case "load":
    cmdLoad(args[1:])
```

cmdLoad 调用 loadFunctions(kv, files) 后不调 executeEntry(kv)。
