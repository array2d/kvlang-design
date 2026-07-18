# deepx 全项目硬编码审计汇总

> 日期: 2026-05-01 | 更新: 2026-05-01 (根因归类 + 最佳方案)
> 来源: 5 份组件审计报告合并 + deepx 设计文档对照分析

---

## 一、总体概览

| 组件 | 语言 | 硬编码数 | 最高严重度 |
|------|------|----------|-----------|
| deepx-core | C++ | 23 | 🔴 P0 |
| executor (heap/exop) | C++ | ~55 | 🔴 P0 |
| VM | Go | 80+ | 🔴 P0 |
| deepxctl | Go | 60+ | 🔴 P0 |
| dashboard | Go/TS/CSS | 50+ | 🔴 P0 |

**合计 ~270 处硬编码**，按问题归类为 6 大根因：

| 根因类别 | 数量 | 本质 | 对应设计文档 |
|----------|------|------|-------------|
| A. Redis Key 无集中定义 | 80+ | 设计已有完整规范，但实现散落为裸字符串 | [deepx-design.md §2](../metaproc/deepx-design.md#2-redis-key-路径约定) |
| B. 配置值无统一入口 | 60+ | 超时/端口/魔数各组件独立定义，无覆盖机制 | [spec-v1.md §2](../metaproc/spec-v1.md#2-kv-空间要求) |
| C. 构建/部署路径不可移植 | 20+ | 平台/用户路径硬编码，跨环境失效 | 启动流程约定 |
| D. 共享逻辑被复制粘贴 | ~400 行 | parser↔ir, heap-cpu↔heap-metal 重复 | [deepx-design.md §1.2](../metaproc/deepx-design.md#12-进程的被动性) |
| E. 字符串 dispatch 无查找表 | ~600 行 | opcode/dtype 用 if-else 链而非表驱动 | [deepx-design.md §2.7](../metaproc/deepx-design.md#27-op-plat-算子注册) |
| F. 命名/规范不一致 | 30+ | 命名空间污染、include guard、API 命名 | [design.md §1](../design.md) |

---

## 二、根因分析（对照设计文档）

将 ~270 处硬编码按产生原因分为 6 大类，每类都与设计文档中已确立的架构原则对照。

### 2.1 根因 A: Redis Key 无集中定义

**设计文档已明确规定**了完整的 Redis key 命名空间（[deepx-design.md §2](../metaproc/deepx-design.md#2-redis-key-路径约定)）：

```
保留路径:
  /src/func/              函数源码
  /op/<backend>/func/     编译产物
  /op/<backend>/list      算子列表
  /vthread/               执行状态
  /sys/                   系统信息
  /cmd/                   命令队列
  /notify/                通知队列
  /done/                  完成通知
```

**现实问题**：5 个组件用裸字符串 `"/vthread/"` `"/src/func/"` `"cmd:op-"` 散落在 30+ 个文件中。重构 key 格式时需修改 15+ 文件，遗漏一处即产生 bug。

**根因本质**：设计定义了规范，但规范没有以代码形式落地。规范是文档，实现是字符串——两者之间存在不可验证的断层。

| 影响文件举例 | 散落 key 样例 |
|-------------|--------------|
| `vm/sched.go` | `KEYS /vthread/*` |
| `vm/router.go` | `KEYS /op/*/list`, `KEYS /sys/op-plat/*` |
| `vm/dispatch.go` | `cmd:heap-metal:0`, `cmd:op-%s` |
| `vm/codegen.go` | `KEYS /vthread/<vtid>/*` |
| `deepxctl/boot.go` | `/sys/heartbeat/term:`, `/sys/op-plat/` |
| `deepxctl/run.go` | `/func/main` (6 次) |
| `dashboard/read.go` | `/sys/heartbeat/term:dashboard` |
| `executor/*/main.cpp` | `cmd:heap-cuda:0`, `done:` |

### 2.2 根因 B: 配置值无统一入口、无覆盖层级

**设计文档**要求 KV 空间提供基础操作能力（[spec-v1.md §2](../metaproc/spec-v1.md#2-kv-空间要求)），但**未定义各组件的运行时配置如何管理**。

**现实问题**：

```
超时值                       散落位置
──────────────────────      ──────────────────────
200ms (服务心跳)              7 处 (boot/run/shutdown)
5s (heap op 超时)             6 处 (dispatch + 各 executor)
30s (BLPOP wait)              3 处 (state + dispatch)
2s (heartbeat interval)       4 处 (各 executor main.cpp)
60 (dashboard 默认超时)       2 处 (run.go + CodeEditor.tsx)
```

```
端口不一致:
  6379    VM server mode, VM single mode, executor C++
  16379   loader, deepxctl
```

**根因本质**：每个开发者独立选择了"看起来合理"的值，没有统一的配置入口来强制一致性。设计文档的进程通信模型天然适合集中配置管理——所有组件通过 Redis 通信，没有直接组件间调用——但这一优势未被利用。

### 2.3 根因 C: 构建/部署路径不可移植

路径硬编码分为三类：

| 类别 | 示例 | 根因 |
|------|------|------|
| **平台特定** | `/opt/homebrew/opt/...` | macOS 本地开发环境泄漏到跨平台构建 |
| **架构特定** | `/usr/lib/x86_64-linux-gnu/...` | 假设 x86_64，arm64 不可编译 |
| **临时路径误用** | `/tmp/deepx/`（PID 文件、日志、二进制） | `/tmp` 语义是易失的，不应存放持久状态 |

### 2.4 根因 D: 共享逻辑被复制粘贴

| 重复内容 | 位置 | 行数 | 根因 |
|----------|------|------|------|
| `parseInfix`/`parseParamList`/`stripQuotes` | `parser/parser.go` ↔ `ir/instruction.go` | ~200 | VM 内部 parser 和 IR 各自独立解析，未提取共用 grammar 包 |
| `lifecycle.cpp`/`.h`/`registry_file.h`/`main.cpp` | `heap-cpu/` ↔ `heap-metal/` | ~300 | 两个 heap 后端的生命周期逻辑相同但未提取到 deepx-core |
| Backend list `["op-metal","op-cuda","op-cpu"]` | `vm/vm.go` + `router.go` | 2 处 | 后端类型是系统级概念，应在一处定义 |
| `isRelative` | `termio/native.go` + `dispatch.go` | 2 处 | 路径解析是平台无关工具函数，应集中在公共包 |
| 服务列表 | `boot.go` + `shutdown.go` (4 处独立副本) | 4 处 | 服务拓扑应由注册表决定，不应在每个命令中硬编码 |

### 2.5 根因 E: 字符串 dispatch 无查找表

**设计文档**定义了 op-plat 算子注册（[deepx-design.md §2.7](../metaproc/deepx-design.md#27-op-plat-算子注册)）：

```
/op/op-cuda/list → ["matmul", "add", "relu", "softmax", ...]
/op/op-cuda/<opname> → {category, dtype, max_shape, ...}
```

VM 的 `router.go:Select()` 已经用 **表驱动** 的方式利用这个注册信息做指令路由。但 executor 层（exop-cpu, exop-metal）仍然用 **600 行 if-else 链** 进行 opcode/dtype 分发。

**根因本质**：设计文档已经定义了以数据驱动的算子注册表，但 executor 实现层没有遵循这个模式。这是设计理念与实现选择之间的不一致。

### 2.6 根因 F: 命名/规范不一致

这些不是独立的设计问题，而是缺少 linter/formatter 或编码规范执行机制：

| 问题 | 数量 | 根因 |
|------|------|------|
| `using namespace std;` 在头文件 | 10 处 | C++ 编码规范未强制 |
| include guard 命名不一致 | 4 处 | 无 lint 检查 |
| `#include "string"` 而非 `<string>` | 2 处 | IDE 自动补全错误 |
| `toYaml()` 函数实际用 JSON | 1 处 | API 重命名未及时更新 |

---

## 三、各组件详情

### 3.1 deepx-core (C++ 公共库)

| # | 严重度 | 问题 | 文件 | 根因 |
|---|--------|------|------|------|
| 1 | P0 | CMake `include_directories(/opt/homebrew/...)` — Linux 不可构建 | CMakeLists.txt:10 | C |
| 2 | P1 | `shm_tensor.cpp` 页大小 fallback `16384` + "Apple Silicon" 注释 | shm_tensor.cpp:15 | B+C |
| 3 | P1 | `shm_tensor.h` 注释提及 `MTLBuffer` — Metal API 泄漏到 POSIX 头文件 | shm_tensor.h:10 | F |
| 4 | P2 | `Shape::operator==` 参数名遮蔽成员，**始终返回 true** | shape.hpp:32 | F |
| 5 | P2 | include guard 命名不一致 (4 处: 缺少 DEEPX_ 前缀/旧名残留/多余下划线) | 4 个 .hpp | F |
| 6 | P2 | `#include "string"` / `#include "iostream"` — 标准库应用 `<>` | 2 处 | F |
| 7 | P2 | `toYaml()`/`fromYaml()` — 实际用 nlohmann/json，函数名残留 | shape.hpp:41 | F |
| 8 | P2 | `.data` 扩展名硬编码在头文件 | tensor.hpp:168 | A |
| 9 | P2 | `int tempidx = 0;` 死字段 | mem.hpp:20 | F |
| 10 | P3 | `using namespace std;` 在头文件中 (10 处) | 9 个 .hpp | F |

### 3.2 executor (heap-cpu / heap-metal / exop-cpu / exop-metal)

| # | 严重度 | 问题 | 影响面 | 根因 |
|---|--------|------|--------|------|
| 1 | 🔴 BUG | `byte_size = element_count * 4` — 非 f32 类型写错误 byte_size | heap-cpu + heap-metal (3 处) | B |
| 2 | 🔴 BUG | exop-cpu `Dockerfile` 全部路径过时 (ubuntu:18.04 EOL) | exop-cpu | C |
| 3 | 🔴 BUG | changeshape ops stub — 始终返回 "not available" | exop-cpu | D |
| 4 | 🔴 | 4 组 Redis Key/Queue 无参数化 (`cmd:heap-metal:0` 等) | 全部 4 个进程 | A |
| 5 | 🔴 | CMake 绝对路径: `/opt/homebrew/` + `/usr/lib/x86_64-linux-gnu/` | 全部 CMakeLists.txt | C |
| 6 | 🟡 | Redis 默认地址 `127.0.0.1:6379` — 无环境变量 fallback | 全部 4 个 main.cpp | B |
| 7 | 🟡 | 超时/心跳硬编码: `BLOCK_TIMEOUT=5`, `HEARTBEAT=2s`, `retry sleep(1)` | 各 4 份副本 | B |
| 8 | 🟡 | `device` 字段硬编码: CPU 进程写 `"gpu0"` ⚠️ | heap-cpu | A |
| 9 | 🟡 | `node="n1"` 硬编码 | heap-cpu + heap-metal | B |
| 10 | 🟡 | ~600 行 if-else 字符串 opcode/dtype dispatch | exop-cpu + exop-metal | E |
| 11 | 🟡 | heap-cpu ↔ heap-metal 代码完全重复 (lifecycle.cpp/.h, registry_file.h, main.cpp) | 2 个目录 | D |
| 12 | 🟢 | `"done:"` / `"/deepx_t_"` 魔法前缀 + `"ok"/"error"` 裸字符串 | 全部 | A |

### 3.3 VM (Go)

| # | 严重度 | 问题 | 影响面 | 根因 |
|---|--------|------|--------|------|
| 1 | 🔴 | `KEYS /vthread/*` — 生产代码用 KEYS O(N) 全库扫描 | sched.go | A |
| 2 | 🔴 | `KEYS /vthread/<vtid>/*` — HandleReturn 扫描子栈 | codegen.go + cache.go | A |
| 3 | 🔴 | `KEYS /op/*/list` + `KEYS /sys/op-plat/*` — 每次 Select 扫描 | router.go | A |
| 4 | 🔴 | Redis key 前缀散落 15+ 文件 (`/vthread/`, `/src/func/`, `/sys/`) | 全局 | A |
| 5 | 🔴 | `cmd:heap-metal:0` — heap queue 硬编码实例 0，不支持多实例 | dispatch.go:207 | A |
| 6 | 🔴 | Redis 端口不一致: server `6379` vs loader `16379` | main.go 2 处 | B |
| 7 | 🟡 | ~200 行 parser↔ir 代码完全重复 | parser.go + instruction.go | D |
| 8 | 🟡 | 12 处 magic timeout 散落 (`2s`, `30s`, `5s`...) | 8 个文件 | B |
| 9 | 🟡 | 全局 WebSocket 连接池 + 文件句柄 map 无 TTL | term_ws.go | B |
| 10 | 🟢 | 状态字符串 `"init"/"running"/"wait"/"done"/"error"` 遍布 8 个文件 | 全局 | A |
| 11 | 🟢 | Backend list 重复定义 | vm.go + router.go | D |

### 3.4 deepxctl (Go CLI)

| # | 严重度 | 问题 | 根因 |
|---|--------|------|------|
| 1 | 🔴 | PID 文件 `/tmp/deepx-boot.json` — 多用户冲突、重启丢失 | C |
| 2 | 🔴 | 日志目录 `/tmp/deepx/logs` — 多实例覆盖 | C |
| 3 | 🔴 | 二进制路径全部硬编码 `/tmp/deepx/...` — 与 Makefile 无一致性校验 | C |
| 4 | 🔴 | Dashboard dist 路径 — 非 repo root 启动 FATAL | C |
| 5 | 🔴 | `bash` + `make` 硬编码 — Alpine 无 bash | C |
| 6 | 🔴 | Redis DefaultAddr 与环境变量/flag 优先级不明确 | B |
| 7 | 🔴 | `splitRedisAddr` 回退值与 `DefaultAddr` 重复定义 | B |
| 8 | 🔴 | Dashboard 端口 `:8080` 不可配置 | B |
| 9 | 🔴 | Dashboard CORS `Allow-Origin: *` | B |
| 10 | 🟡 | 18+ Redis key 常量散落 (boot/run/shutdown) | A |
| 11 | 🟡 | 19+ 超时/间隔常量散落（`200ms` 出现 7 次） | B |
| 12 | 🟡 | 服务列表 `{"op-metal","heap-metal","vm","dashboard"}` 4 处副本 | D |
| 13 | 🟡 | `/func/main` 在 run.go 中出现 6 次 | A |
| 14 | 🟡 | Loader 输出解析依赖魔法字符串（`"OK"`, `"ENTRY /func/main →"`） | A |
| 15 | 🟡 | `/dev/null` 硬编码（应用 `os.DevNull`） | F |
| 16 | 🟢 | 版本号 `"0.2.0"` 硬编码、文件权限 `0644`/`0755` 散落 | F |

### 3.5 dashboard (Go + React/TypeScript/CSS)

| # | 严重度 | 问题 | 根因 |
|---|--------|------|------|
| 1 | 🔴 | 超时 `60` 前后端各一份（run.go + CodeEditor.tsx） | B |
| 2 | 🔴 | 入口函数 `"main"` 前后端各一份（run.go + CodeEditor.tsx + OutputPanel.tsx） | A+B |
| 3 | 🔴 | `"/api/status/stream"` client.ts + App.tsx 重复 | A |
| 4 | 🔴 | `"/sys/heartbeat/term:dashboard"` read.go + terminal.go 重复 | A |
| 5 | 🔴 | 端口 `:8080` main.go + vite.config.ts 耦合 | B |
| 6 | 🟡 | xterm 主题 20 个颜色值 — 与 CSS 变量重复 | B |
| 7 | 🟡 | 终端 `"dashboard"` 实例名 + shell `/bin/bash` 硬编码 | B |
| 8 | 🟡 | 13 处魔数: 缓冲 `4096`/`256`/`8`、重连 `2000`/`3000`、轮询 `500`/`3000` | B |
| 9 | 🟡 | localStorage key 字符串散落 | A |
| 10 | 🟢 | 面板尺寸 `260`/`320`、字体 `13`、滚动 `5000` | B |

---

## 四、跨文件重复常量（前后端不一致风险）

| 值 | 出现位置 | 风险 | 根因 |
|----|----------|------|------|
| `60` (默认超时秒) | `run.go` + `CodeEditor.tsx` | 一端改另一端行为异常 | B |
| `"main"` (默认入口) | `run.go` + `CodeEditor.tsx` + `OutputPanel.tsx` | 同上 | A |
| `"/api/status/stream"` | `client.ts` + `App.tsx` | 重复定义 | A |
| `"/sys/heartbeat/term:dashboard"` | `read.go` + `terminal.go` | 改键名一端 404 | A |
| `"127.0.0.1"` | `terminal.go` + `read.go` | 非本地不可达 | B |
| `:8080` | `main.go` + `vite.config.ts` | 端口变更改多处 | B |
| `16379` vs `6379` | VM ↔ loader ↔ executor | Redis 连接失败 | B |

---

## 五、修复方案（按根因类别）

### 5.1 根因 A: Redis Key 集中定义 → `deepx/keys` 包 + `key_defs.h`

**原理**：设计文档已经定义了完整的 key 命名空间（三层架构、vthread 路径、命令队列）。
我们应该在代码中精确表达这个规范，使规范即代码，代码即规范。

**Go 侧: `executor/vm/internal/keys/keys.go` (所有 Go 组件共享)**

```go
// Package keys 提供 Redis key 的集中定义和构造函数。
// 所有 key 均源自 doc/metaproc/deepx-design.md §2 的规定。
package keys

import "fmt"

// ============================================================
// §2.1 保留路径前缀
// ============================================================
const (
    PrefixSrcFunc  = "/src/func/"        // 函数源码
    PrefixOp       = "/op/"              // 后端编译产物
    PrefixVthread  = "/vthread/"         // 执行状态
    PrefixSys      = "/sys/"             // 系统信息
    PrefixCmd      = "cmd:"              // 命令队列
    PrefixNotify   = "notify:"           // 通知队列
    PrefixDone     = "done:"             // 完成通知
)

// ============================================================
// §2.2 Func 路径 (三层架构)
// ============================================================

// SrcFunc 源码层: /src/func/<name>
func SrcFunc(name string) string { return PrefixSrcFunc + name }

// SrcFuncInst 源码层指令: /src/func/<name>/<n>
func SrcFuncInst(name string, n int) string {
    return fmt.Sprintf("%s%s/%d", PrefixSrcFunc, name, n)
}

// OpFunc 编译层: /op/<backend>/func/<name>
func OpFunc(backend, name string) string {
    return fmt.Sprintf("/op/%s/func/%s", backend, name)
}

// OpFuncInst 编译层指令: /op/<backend>/func/<name>/<n>
func OpFuncInst(backend, name string, n int) string {
    return fmt.Sprintf("/op/%s/func/%s/%d", backend, name, n)
}

// ============================================================
// §2.3 Vthread 路径 (执行层)
// ============================================================

// Vthread 对应 /vthread/<vtid>
func Vthread(vtid string) string { return PrefixVthread + vtid }

// VthreadInst 指令坐标 [addr0, addr1]: /vthread/<vtid>/[addr0,addr1]
func VthreadInst(vtid, pc string, addr1 int) string {
    if addr1 == 0 {
        return fmt.Sprintf("%s%s/%s,0]", PrefixVthread, vtid, pc)
    }
    return fmt.Sprintf("%s%s/%s,%d]", PrefixVthread, vtid, pc, addr1)
}

// VthreadNamedSlot 命名槽位: /vthread/<vtid>/<name>
func VthreadNamedSlot(vtid, name string) string {
    return PrefixVthread + vtid + "/" + name
}

// VthreadStatus vthread 自身的状态 key
func VthreadStatus(vtid string) string { return PrefixVthread + vtid }

// ============================================================
// §2.4 命令队列
// ============================================================

func CmdOpPlat(instance string) string    { return "cmd:op-" + instance }
func CmdHeapPlat(program, device string) string { return fmt.Sprintf("cmd:%s:%s", program, device) }
func DoneQueue(vtid string) string        { return PrefixDone + vtid }
func NotifyVM() string                    { return "notify:vm" }

// ============================================================
// §2.5 系统路径
// ============================================================

func SysOpPlat(instance string) string    { return fmt.Sprintf("/sys/op-plat/%s", instance) }
func SysHeapPlat(instance string) string  { return fmt.Sprintf("/sys/heap-plat/%s", instance) }
func SysVM(id string) string              { return fmt.Sprintf("/sys/vm/%s", id) }
func VtidCounter() string                 { return "/sys/vtid_counter" }
func SysConfig() string                   { return "/sys/config" }

// ============================================================
// §2.7 算子注册（程序级）
// ============================================================

func OpList(program string) string       { return fmt.Sprintf("/op/%s/list", program) }
func OpMetaWildcard() string             { return "/op/*/list" }
func SysOpPlatWildcard() string          { return "/sys/op-plat/*" }

// ============================================================
// 常用状态值 (§5.5)
// ============================================================

type VthreadStatus string
const (
    StatusInit    VthreadStatus = "init"
    StatusRunning VthreadStatus = "running"
    StatusWait    VthreadStatus = "wait"
    StatusError   VthreadStatus = "error"
    StatusDone    VthreadStatus = "done"
)

// ============================================================
// 常用通知事件
// ============================================================

const (
    EventNewVthread = "new_vthread"
)
```

**C++ 侧: `executor/deepx-core/include/deepx/key_defs.h`**

```cpp
#pragma once
#include <string>

namespace deepx::keys {

// §2.1 保留路径前缀
inline constexpr std::string_view kPrefixSrcFunc  = "/src/func/";
inline constexpr std::string_view kPrefixVthread  = "/vthread/";
inline constexpr std::string_view kPrefixSys      = "/sys/";
inline constexpr std::string_view kPrefixCmd      = "cmd:";
inline constexpr std::string_view kPrefixDone     = "done:";
inline constexpr std::string_view kPrefixNotify   = "notify:";

// §2.4 命令队列构造
inline std::string CmdHeapPlat(const char* program, int device) {
    return std::string(kPrefixCmd) + program + ":" + std::to_string(device);
}
inline std::string DoneQueue(const char* vtid) {
    return std::string(kPrefixDone) + vtid;
}

// §2.5 系统路径
inline std::string SysOpPlat(const char* id) {
    return std::string(kPrefixSys) + "op-plat/" + id;
}
inline std::string SysHeapPlat(const char* id) {
    return std::string(kPrefixSys) + "heap-plat/" + id;
}

// 状态常量
inline constexpr std::string_view kStatusOK    = "ok";
inline constexpr std::string_view kStatusError = "error";

// 通知事件
inline constexpr std::string_view kEventNewVthread = "new_vthread";

} // namespace deepx::keys
```

**TypeScript 侧: `tool/dashboard/frontend/src/api/keys.ts`**

```typescript
// 前端所需的一小部分 key 常量（API 路径与 Redis 键名）
export const API = {
  STATUS_STREAM: '/api/status/stream',
  SYS_HEARTBEAT: '/sys/heartbeat/term:dashboard',
} as const;

export const DEFAULTS = {
  ENTRY_FUNC: 'main',
  TIMEOUT_SEC: 60,
} as const;
```

**核心收益**：
- key 格式变更只需修改 1 个文件，IDE 的「查找引用」可看到全部影响面
- 函数签名强制传入参数，消除 `fmt.Sprintf` 格式错误
- C++/Go/TS 各自的类型系统保证 key 不会因拼写错误而失效

### 5.2 根因 B: 统一配置入口 + 环境变量覆盖

**原理**：所有组件通过 Redis 通信（无直接组件间调用），所以天然适合**集中配置**。
设计文档的进程模型（被动消费指令队列）意味着配置变化可以在一个入口生效。

**方案：`deepx.Config` 结构体 + 三层优先级**

```
优先级 (高→低):
  1. 命令行 flag (--redis-addr, --timeout, --port, ...)
  2. 环境变量 (DEEPX_REDIS_ADDR, DEEPX_HEARTBEAT, DEEPX_LOG_DIR, ...)
  3. 代码中的合理默认值
```

**Go 侧 (`executor/vm/internal/config/config.go`)：**

```go
package config

import (
    "os"
    "time"
)

// Config 全局运行时配置。所有时间、端口、地址等运行时参数都从这里取。
// 环境变量前缀: DEEPX_
type Config struct {
    // Redis
    RedisAddr string

    // Timeouts (所有超时集中在一处，注释说明用途)
    HeartbeatInterval time.Duration // 心跳间隔
    OpBLPOPTimeout    time.Duration // 等待 op-plat 完成的最大时间
    HeapBLPOPTimeout  time.Duration // 等待 heap-plat 完成的最大时间
    VMNotifyTimeout   time.Duration // VM 等待新 vthread 的最大阻塞时间
    DashboardTimeout  time.Duration // Dashboard 代码执行默认超时

    // Paths
    LogDir string
    PIDFile string
    DataDir string

    // Network
    DashboardPort   string
    DashboardCORS   string
}

// Default 返回从环境变量覆盖的默认配置。
func Default() *Config {
    return &Config{
        RedisAddr:         getEnv("DEEPX_REDIS_ADDR", "127.0.0.1:6379"),
        HeartbeatInterval: getEnvDuration("DEEPX_HEARTBEAT", 2*time.Second),
        OpBLPOPTimeout:    getEnvDuration("DEEPX_OP_TIMEOUT", 30*time.Second),
        HeapBLPOPTimeout:  getEnvDuration("DEEPX_HEAP_TIMEOUT", 5*time.Second),
        VMNotifyTimeout:   getEnvDuration("DEEPX_VM_NOTIFY_TIMEOUT", 0), // 0 = 无限
        DashboardTimeout:  getEnvDuration("DEEPX_DASHBOARD_TIMEOUT", 60*time.Second),
        LogDir:            getEnv("DEEPX_LOG_DIR", "/tmp/deepx/logs"),
        PIDFile:           getEnv("DEEPX_PID_FILE", "/tmp/deepx/deepx.pid"),
        DataDir:           getEnv("DEEPX_DATA_DIR", ""),
        DashboardPort:     getEnv("DEEPX_DASHBOARD_PORT", "8080"),
        DashboardCORS:     getEnv("DEEPX_CORS", "*"),
    }
}

func getEnv(key, fallback string) string {
    if v := os.Getenv(key); v != "" { return v }
    return fallback
}

func getEnvDuration(key string, fallback time.Duration) time.Duration {
    if v := os.Getenv(key); v != "" {
        if d, err := time.ParseDuration(v); err == nil { return d }
    }
    return fallback
}
```

**C++ 侧同理**：引入 `deepx::Config` 从环境变量读取，各 executor main.cpp 统一调用。

**TypeScript 侧**：构建时通过 `VITE_DEEPX_*` 环境变量注入（Vite 原生支持 `import.meta.env`）。

**核心收益**：
- 调优只需改环境变量，不需要 grep + 改代码 + 重新编译
- 容器部署时通过 Docker env / K8s ConfigMap 注入
- 默认值在代码中明确，环境变量作为覆盖入口文档化

### 5.3 根因 C: 构建/部署路径可移植化

**原理**：System V / POSIX 定义了清晰的路径语义。`/tmp` 是易失的临时文件，持久状态应走 XDG 规范或 `DEEPX_HOME` 约定。

**方案**：

| 问题 | 当前 | 优化方案 |
|------|------|---------|
| CMake 依赖 `/opt/homebrew/` | `include_directories(/opt/homebrew/...)` | `find_package(hiredis REQUIRED)` / `pkg_check_modules` |
| CMake 依赖 `/usr/lib/x86_64-linux-gnu/` | 硬编码 | `find_library` 动态查找 |
| PID 文件 `/tmp/deepx-boot.json` | 多用户冲突 | `$DEEPX_HOME/boot.json`（默认 `~/.deepx/`） |
| 日志 `/tmp/deepx/logs` | 重启丢失 | `$DEEPX_HOME/logs`（默认 `~/.deepx/logs`） |
| 二进制 `/tmp/deepx/...` | 与 Makefile 耦合 | `$DEEPX_OUT` 环境变量（默认 `./build/bin/`） |
| Dashboard dist 路径 | 依赖 CWD | `embed.FS` 嵌入 Go 二进制 |
| `bash`+`make` 硬编码 | Alpine 不可用 | `sh` + 消除 make 外部依赖 |
| Dockerfile `ubuntu:18.04` | EOL | `ubuntu:24.04` 或 `debian:bookworm-slim` |

**路径解析优先级**：

```go
func DEEPXHome() string {
    if v := os.Getenv("DEEPX_HOME"); v != "" { return v }
    if home := os.Getenv("HOME"); home != "" { return filepath.Join(home, ".deepx") }
    return "/tmp/deepx" // 兜底
}
```

**CMake 修复示例（被影响的 5 个 CMakeLists.txt）**：

```cmake
# 修复前 (不可移植)
include_directories(/opt/homebrew/opt/hiredis/include)
link_directories(/opt/homebrew/opt/hiredis/lib)

# 修复后 (可移植)
find_package(PkgConfig REQUIRED)
pkg_check_modules(HIREDIS REQUIRED hiredis)
include_directories(${HIREDIS_INCLUDE_DIRS})
link_directories(${HIREDIS_LIBRARY_DIRS})
```

### 5.4 根因 D: 消除代码重复 → 提取共享模块

**原理**：设计文档定义了清晰的分层（[deepx-design.md §1.1](../metaproc/deepx-design.md#11-五个核心)），每个核心有明确角色。共享逻辑应放在对应层中，而非复制。

**方案**：

| 重复内容 | 提取到 | 影响文件 |
|----------|--------|---------|
| `parseInfix`/`parseParamList`/`stripQuotes` (~200 行) | 新建 `executor/vm/internal/grammar/` 包 | `parser/parser.go`, `ir/instruction.go` |
| `lifecycle.cpp`/`.h`/`registry_file.h`/`main.cpp` (~300 行) | 已有 `executor/deepx-core/`，将公共逻辑移入 | `heap-cpu/src/`, `heap-metal/src/` |
| Backend list `["op-metal","op-cuda","op-cpu"]` | `executor/vm/internal/keys/` 或 `config/` | `vm/vm.go`, `platform/router.go` |
| `isRelative` (2 处) | `executor/vm/internal/keys/`（与路径构造在一起） | `termio/native.go`, `platform/dispatch.go` |
| 服务列表 4 处副本 | `deepxctl` 中提取服务注册表 `ServiceRegistry` | `cmd/boot.go`, `cmd/shutdown.go` |

**heap-cpu/heap-metal 去重具体方案**：

```cpp
// executor/deepx-core/include/deepx/heap_lifecycle.h
// 此前 heap-cpu 和 heap-metal 各自维护一份 lifecycle.cpp
// 现在提取为公共模板，两个后端仅注入设备相关的 shm 分配逻辑。

namespace deepx::heap {

// 公共: tensor 创建/删除/克隆的状态机逻辑
int handle_newtensor(const HeapTask& task, ShmAllocator* alloc);
int handle_deltensor(const HeapTask& task, ShmAllocator* alloc);
int handle_clonetensor(const HeapTask& task, ShmAllocator* alloc);

// 各后端仅需实现这个接口
class ShmAllocator {
public:
    virtual void* alloc(size_t byte_size, const char* device) = 0;
    virtual void free(void* ptr) = 0;
    virtual void memcpy_dev_to_dev(void* dst, const void* src, size_t n) = 0;
};

} // namespace deepx::heap
```

### 5.5 根因 E: 字符串 dispatch → 表驱动

**原理**：设计文档的 op-plat 注册机制（[deepx-design.md §2.7](../metaproc/deepx-design.md#27-op-plat-算子注册)）本身就是一个**以数据为中心的查找表**。算子能力存储在 Redis 的 `/op/<program>/list` 中，运行时可查询。executor 层硬编码 if-else 是与这一设计相悖的实现选择。

**方案：C++ executor 内部构建静态 dispatch table**

```cpp
// executor/exop-metal/src/op_registry.hpp
// 编译期构建查找表，替换 ~300 行 if-else

#pragma once
#include <string>
#include <unordered_map>
#include <functional>

namespace exop::metal {

using OpFunc = std::function<int(const TensorArgs&)>;

// 单一真源：opcode → 处理函数映射
inline const std::unordered_map<std::string, OpFunc> kOpDispatch = {
    {"add",     op_add},
    {"sub",     op_sub},
    {"mul",     op_mul},
    {"div",     op_div},
    {"matmul",  op_matmul},
    {"relu",    op_relu},
    {"softmax", op_softmax},
    // ... 所有支持的算子
};

// 单一真源：dtype → byte_size
inline const std::unordered_map<std::string, size_t> kDtypeBytes = {
    {"f16", 2},  {"f32", 4},  {"f64", 8},
    {"bf16", 2}, {"i8", 1},  {"i16", 2},
    {"i32", 4},  {"i64", 8}, {"u8", 1},
};

// 使用: 替换 byte_size = element_count * 4 (bug!)
inline size_t byte_size_of(const std::string& dtype, size_t element_count) {
    auto it = kDtypeBytes.find(dtype);
    if (it == kDtypeBytes.end()) {
        throw std::runtime_error("unsupported dtype: " + dtype);
    }
    return it->second * element_count;
}

} // namespace exop::metal
```

**VM 侧（Go）**：`router.go:Select()` 已经用表驱动的方式使用 Redis 注册表做指令路由，是正确的模式。需要将 `dispatch.go` 中的 `save/load/print` 等特殊 opcode 也改为表驱动：

```go
var specialOps = map[string]func(context.Context, *redis.Client, string, string, *ir.Instruction) error{
    "save":  handleSave,
    "load":  handleLoad,
    "print": handlePrint,
}

func Execute(ctx context.Context, rdb *redis.Client, vtid, pc string, inst *ir.Instruction) error {
    if handler, ok := specialOps[inst.Opcode]; ok {
        return handler(ctx, rdb, vtid, pc, inst)
    }
    // 默认: 分发到 op-plat
    return Compute(ctx, rdb, vtid, pc, inst)
}
```

**核心收益**：
- `byte_size = element_count * 4` bug 通过 dtype→bytesize 查找表消除
- 新增算子只需在 map 中添加一条，不需要修改执行逻辑
- dispatch 逻辑可通过单测覆盖全部 opcode，if-else 链则难以穷举

### 5.6 根因 F: 命名/规范自动化

这些问题是**工具可解决的**，不应依赖人工审查。

| 问题 | 自动化方案 |
|------|---------|
| include guard 不一致 | `.clang-tidy` 规则 `llvm-header-guard`，或统一为 `#pragma once` |
| `#include "string"` → `<string>` | `.clang-tidy` 规则 `llvm-include-order` |
| `using namespace std;` 在头文件 | `.clang-tidy` 规则 `google-build-using-namespace` |
| 死字段 `tempidx` | `-Wunused-private-field` (Clang) / 静态分析 |
| 函数名残留 `toYaml()` | IDE 重命名 + grep 确认 |
| 版本号硬编码 | `-ldflags "-X main.version=$(git describe --tags)"` |
| 文件权限散落 | 提取为 `const` 常量在单一位置 |

**.clang-tidy 配置建议**：

```yaml
Checks: >
  -*,llvm-header-guard,
  google-build-using-namespace,
  llvm-include-order,
  readability-identifier-naming

CheckOptions:
  - key: readability-identifier-naming.ClassCase
    value: CamelCase
  - key: readability-identifier-naming.NamespaceCase
    value: lower_case
```

---

## 六、修复优先级与实施路径

### P0 — 阻塞性（立即修复，预计 3 人天）

| # | 问题 | 方案 | 对应根因 |
|---|------|------|---------|
| 1 | `byte_size = element_count * 4` BUG | 引入 `kDtypeBytes` 查找表（§5.5） | E |
| 2 | `Shape::operator==` 始终返回 true | 重命名参数避免遮蔽成员 | F |
| 3 | CMake 绝对路径不可移植 | `find_package` / `pkg_check_modules`（§5.3） | C |
| 4 | Dockerfile EOL + 路径过时 | 更新 base image + 路径（§5.3） | C |
| 5 | `KEYS` 命令滥用 (5 处) | 确定性 key 构造（§5.1）+ SCAN 兜底 | A |
| 6 | `cmd:heap-metal:0` 硬编码实例 | 使用 `keys.CmdHeapPlat()` 动态路由（§5.1） | A |

### P1 — 高优先（架构级改进，预计 5 人天）

| # | 问题 | 方案 | 对应根因 |
|---|------|------|---------|
| 7 | Redis Key 全项目常量化 | 实施 `executor/vm/internal/keys/` 包 + `key_defs.h`（§5.1） | A |
| 8 | 消除 parser↔ir 200 行重复 | 提取 `executor/vm/internal/grammar/` 包（§5.4） | D |
| 9 | 消除 heap-cpu↔heap-metal 300 行重复 | 提取到 deepx-core `heap_lifecycle.h`（§5.4） | D |
| 10 | 统一超时/端口配置 | `deepx.Config` 结构体 + 环境变量覆盖（§5.2） | B |
| 11 | 前后端共享常量 (超时/入口函数/API) | `keys.ts` + 构建时注入（§5.1, §5.2） | A+B |
| 12 | deepxctl 路径可移植化 | `DEEPX_HOME` / `DEEPX_OUT` 环境变量（§5.3） | C |
| 13 | Dashboard dist 嵌入二进制 | `embed.FS`（§5.3） | C |
| 14 | Redis 端口统一 | 全部使用 `DEEPX_REDIS_ADDR` 环境变量，默认 6379 | B |

### P2 — 中优先（代码卫生，预计 3 人天）

| # | 问题 | 方案 | 对应根因 |
|---|------|------|---------|
| 15 | 状态字符串常量化 | 纳入 `keys.VthreadStatus` 类型（§5.1） | A |
| 16 | Backend list 统一 | 移入 `keys/` 或 `config/`（§5.1） | A+D |
| 17 | 字符串 dispatch → 表驱动 | executor 层实施 `kOpDispatch` 查找表（§5.5） | E |
| 18 | Loader 输出解析 | 改为 JSON 格式输出（§5.2） | A |
| 19 | xterm 主题 | 从 CSS 变量动态读取 | F |
| 20 | WebSocket TTL | 连接池清理逻辑 | B |
| 21 | `using namespace std;` | `.clang-tidy` 自动修复（§5.6） | F |
| 22 | include guard 统一 | 全部改为 `#pragma once` + lint（§5.6） | F |

### P3 — 低优先（锦上添花，预计 1 人天）

| # | 问题 | 方案 | 对应根因 |
|---|------|------|---------|
| 23 | 版本号硬编码 | `-ldflags` 注入 | F |
| 24 | 文件权限散落 | 提取为 const | F |
| 25 | `/dev/null` → `os.DevNull` | 直接替换 | F |
| 26 | `toYaml()` → `toJson()` | IDE 重命名 | F |
| 27 | `#include "string"` → `<string>` | `.clang-tidy` 自动修复 | F |
| 28 | 魔数面板尺寸 | 提取为常量 | B |
| 29 | localStorage key | 提取为常量 | A |

---

## 七、实施路径图

```
Phase 1 (P0, 3d): 堵住出血点
  ├── 1. byte_size bug 修复 (E: dtype查找表)
  ├── 2. Shape::operator== 修复 (F: 参数重命名)
  ├── 3. CMake 可移植 (C: find_package)
  ├── 4. Dockerfile 更新 (C: base image)
  ├── 5. KEYS → 确定性构造 (A: 第一批 keys 函数)
  └── 6. heap queue 动态路由 (A: CmdHeapPlat)

Phase 2 (P1, 5d): 架构治本
  ├── 7. keys 包 + key_defs.h 全面落地 (A)
  ├── 8. grammar/ 包提取 (D: parser↔ir 去重)
  ├── 9. deepx-core heap_lifecycle 提取 (D: heap 去重)
  ├── 10. Config 结构体 (B: 超时/端口集中)
  ├── 11. 前后端共享常量 (B: 消除跨边界不一致)
  ├── 12. DEEPX_HOME / DEEPX_OUT (C: 路径可移植)
  ├── 13. embed.FS (C: dashboard 嵌入)
  └── 14. 统一 Redis 端口 6379 (B: 消除不一致)

Phase 3 (P2 + P3, 4d): 代码卫生 + 自动化
  ├── 15-16. 状态字符串 + Backend list 常量化 (A)
  ├── 17. executor dispatch 表驱动 (E)
  ├── 18-20. Loader JSON / xterm / WebSocket TTL (B)
  ├── 21-29. .clang-tidy + 命名修正 (F)
  └── CI: 加入 clang-tidy + go vet + shellcheck
```

---

## 八、度量指标

| 指标 | 当前 | 目标 (Phase 2 完成后) |
|------|------|----------------------|
| 裸 Redis key 字符串（非 keys 包构造） | 80+ | 0 |
| 超时魔数散落文件数 | 15+ | 1 (`config.go`) |
| 重复代码块 (>20 行) | 5 处 (~700 行) | 0 |
| if-else 字符串 dispatch 行数 | ~600 行 | 0（全部改查表） |
| 跨组件端口不一致 | 2 个 (6379/16379) | 1 个（统一 6379） |
| 跨平台不可编译的 CMake | 5 个 CMakeLists.txt | 0 |
| 前后端重复常量 | 7 处 | 0 |
