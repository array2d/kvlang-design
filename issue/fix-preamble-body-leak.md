# 🔴 IfStmt/WhileStmt String() 多行 → inBody 匹配失败 → preamble 泄漏

**文件**: `internal/parser/file.go` → `parseLines()`, `internal/ast/ast.go` → `IfStmt.String()` / `WhileStmt.String()`

## 现象

`pre_main` 中混入其他函数的控制流指令，导致 VThread 卡死：

```
pre_main body (泄漏后):
  [0,0] = "if"          ← 来自 if_fn 体，不该在此
  [1,0] = "str.set"     ← 来自 while_fn 体，不该在此
  [2,0] = "str.set"     
  [3,0] = "while"       
  [4,0] = "str.set"     ← 真正的 preamble 开始
```

## 根因

`parseLines()` 区分函数体行和 preamble 行时，使用字符串比较：

```go
// file.go:108-110
for _, fn := range df.Funcs {
    for _, bl := range fn.Body {
        if bl.String() == line {
            inBody = true
        }
    }
}
```

但 `IfStmt.String()` 返回**多行字符串**：

```go
func (s *IfStmt) String() string {
    r := "if (" + s.Cond + ") {\n"
    for _, st := range s.Then { r += "\t" + st.String() + "\n" }
    r += "}" ...
    return r
}
```

源码行 `if ('./flag') {` 与多行 String 永不相等 → `inBody` 始终为 false → 控制流函数体行被当作 preamble。

## 复现

任意包含 `if`/`while`/`block` 的 .kv 文件，`pre_main` 都会混入错误指令。

```bash
kvlang kvspace list /src/func/pre_main/_block_1
# 可见非 preamble 的 if/while 指令
```

## 修复方向

1. **改 parseLines**：用 brace depth 或 AST 结构判断是否在函数体内，不依赖 String() 字符串匹配
2. **改 String()**：加一个 `FirstLine() string` 方法，只返回首行用于匹配
3. **改 isBody**：对 Stmt 加 `MatchSourceLine(line string) bool` 接口方法
