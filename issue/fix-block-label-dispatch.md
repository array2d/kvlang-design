# 🔴 br/goto 无法分发到子路径 block label

**文件**: `internal/layoutcode/layoutcode.go` → `HandleCall()`, `internal/kvcpu/controlflow.go` → `handleBr()`

**现象**: `if`/`while` lowering 后的基本块，以及手动编写的 `br`/`goto` 指令，在运行时无法找到目标 label。

**根因分析**:

### 1. lowering 生成 goto 时使用 `parent/label` 路径

```go
// lower/lower.go:166
func gotoLabel(parent, label string) *ast.Instruction {
    return &ast.Instruction{Opcode: "call", Reads: []string{parent + "/" + label}}
}
```

例如 `goto(merge)` → `call(test_func/merge)`。

### 2. HandleCall 查找函数注册

```go
// layoutcode.go:38
sig, err := kv.Get(keytree.SrcFunc(funcName))
// keytree.SrcFunc("test_func/merge") = "/src/func/test_func/merge"
```

### 3. 问题：block label 子路径未注册为函数

`loadFunctions()` 只注册顶层函数名：

```go
// cmd/kvlang/load.go:47
fn.Register(kv)  // 只注册 "/src/func/test_func"
```

但 **没有** 为 lowering 产生的 block label 子路径注册：

```
/src/func/test_func/if_cond_1   ← 不存在
/src/func/test_func/then_2      ← 不存在
/src/func/test_func/merge_4     ← 不存在
```

### 4. 手动编写的 br/goto 同样失效

```kv
entry: {
    br('./flag', then, else)  # then/else → not found
}
```

`handleBr` 用无修饰的 label 名调用 `HandleCall("then")`，但实际路径是 `/src/func/函数名/then`。

**影响**: `if/else`、`while`、基本块 `br`/`goto` 全部无法执行。

**修复方向**:
1. 在 `loadFunctions` 中，遍历每个函数的 body 子路径，为每个 block label 注册签名（可从父函数继承）
2. 或者在 `HandleCall` 中添加回退逻辑：如果 `funcName` 不存在，尝试解析为 `parent/label` 形式
