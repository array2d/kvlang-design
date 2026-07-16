# kvlang 全局变量（堆对象）设计分析

> `/` 开头的 kvspace 绝对路径天然就是全局变量。零语法改动，零新原语。

---

## 一、已经可用

```kvlang
0 -> /counter           # 全局写入
/counter -> x           # 全局读取
/counter + 1 -> /counter # 全局自增
```

`resolveWriteKey` / `resolveReadValue` 对 `/abs` 路径直通 `kv.Set` / `kv.Get`，
不经过 `framePath/` 拼接。全局变量和帧局部变量用同一条读写路径。

验证：
```
0 -> /counter
increment() -> ()       # /counter + 1 -> /counter
increment() -> ()
increment() -> ()
print(/counter)         # 输出: 3
```

---

## 二、与 5 种参考语言对比

| | 全局变量声明 | 访问语法 | 作用域 |
|--|------------|---------|--------|
| **C** | `int g = 0;`（文件顶层） | `g` 或 `extern int g` | 文件/跨文件 |
| **Go** | `var g = 0`（package 顶层） | `g`，跨包需大写 `G` | package |
| **Rust** | `static G: i32 = 0;` | `G`，`unsafe` 块内可变 | crate |
| **Python** | `g = 0`（模块顶层） | `g`，函数内需 `global g` | 模块 |
| **JS** | `let g = 0;`（顶层） | `g` | 模块/全局 |
| **kvlang** | `0 -> /g`（任意处写入） | `/g` | kvspace（全 VM） |

**关键差异**：
- 所有语言需要**声明** + **赋值**两步；kvlang 只需写入即存在
- 所有语言有作用域限制；kvlang 的 `/` 是真正的全 VM 可见
- C/Go/Rust 有编译期初始化；kvlang 的初始化在运行时（首次写入）

---

## 三、路径规范

| 路径 | 语义 |
|------|------|
| `/counter` | 简单全局 |
| `/data/weights` | 嵌套全局 |
| `/sys/config/limit` | 带命名空间的全局 |

建议约定：用户全局用 `/data/` 前缀，引擎保留 `.` 开头和 `/sys/`、`/func/`、`/vthread/`。

---

## 四、并发语义

kvlang 多 worker 并行，`/counter + 1 -> /counter` 不是原子的（读-改-写）。
对标 C 的 data race、Go 的 `-race` 检测、Rust 的编译期阻止——kvlang 当前不阻止，
由用户保证单一 writer（路径所有权原则：谁写谁拥有）。

---

## 五、与 for 遍历器的关系

for 遍历器 `for (v in /data) { ... }` 可直接遍历全局路径——`/data` 是绝对路径，
`resolveKVPath` 对 `/` 开头直接返回。

---

## 六、零实现代价

全局变量不需要任何新代码——`resolveReadValue`/`resolveWriteKey` 中 `isAbsolute` 分支
已经处理 `/abs` 路径。全局变量是 kvspace 路径寻址模型的天然副产品，不是后加的特性。
