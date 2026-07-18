# 元程术语表 (Metaproc Glossary)

> 完整术语定义见 `doc/metaproc/spec-v1.md` 附录 C。
> 本文档为 Claude Code 上下文快速参考。

## 核心概念

| 术语 | 英文 | 定义 |
|------|------|------|
| 元程 | Metaproc | 一个 KV 空间实例，分布式计算的边界。类比 OS 进程。 |
| 元线程 | Vthread | 元程内的执行流。私有调用栈，共享堆数据。类比 OS 线程。 |
| KV 空间 | KV Space | Redis 实现的全局 key-value 存储。元程的运行载体。 |
| 路径空间 | Path Space | KV 空间的 key 命名规范。`/func/`、`/usr/`、`/sys/`、`/metathread/`。 |
| dxlang | DX Language | deepx 元程级编程语言（概念）；`executor/dxlang/` 是其当前 C++ 参考实现（代码）。 |

## 5 个核心 (Five Cores)

| 核心 | 英文 | 角色 |
|------|------|------|
| Redis | — | KV 空间：全局状态存储、命令队列 (List)、锁、通知 |
| pysdk | Python SDK | 算法前端：注册 dxlang 源码到 `/usr/func/`，创建 vthread |
| op-plat | Operator Platform | 计算平面：被动消费指令，执行 GPU/CPU 张量运算 |
| heap-plat | Heap Platform | 堆管理平面：tensor 对象生命周期 (shm 创建/删除/克隆) |
| VM | Virtual Machine | 解释执行：CALL eager 翻译、指令路由到 op-plat/heap-plat、状态推进 |

## 三层 IR

| 层 | 路径 (v4) | 格式 | 角色 |
|----|------|------|------|
| 源码层 | `/usr/func/<name>/` | dxlang 人类可读文本 | pysdk 写入 |
| 内置/扩展层 | `/func/builtin/` `/func/exop-<backend>/` | 算子定义 | VM 直接执行 / op-plat 执行 |
| 执行层 | `/metathread/<vtid>/` | `[addr0, addr1]` 二维坐标 | VM CALL 时 eager 翻译 |

## 路径空间 (v4)

> **单一真源**: `spec/keys.yaml` → `make gen-keys` 生成代码。禁止裸字符串。

| 命名空间 | 路径 | 说明 |
|----------|------|------|
| `/func/` | — | 函数定义 (系统保留) |
| | `/func/builtin/<category>/<op>` | VM 内置算子 (标量/控制流) |
| | `/func/exop-<backend>/<category>/<op>` | extended-op 后端算子 |
| `/usr/` | — | 用户空间 (系统保留) |
| | `/usr/func/<name>` | 用户函数签名 |
| | `/usr/func/<name>/<n>` | 用户函数第 n 条指令 |
| | `/usr/func/<name>/<n>/<branch>/<m>` | 控制流分支 |
| `/sys/` | — | 系统内部 (系统保留) |
| | `/sys/daemon/op/<instance>` | op-plat 进程注册 |
| | `/sys/daemon/heap/<instance>` | heap-plat 进程注册 |
| | `/sys/daemon/vm/<id>` | VM 实例注册 |
| | `/sys/backend/<program>/list` | 后端算子列表 |
| | `/sys/backend/<program>/ops/<opname>` | 算子元数据 |
| | `/sys/ipc/cmd/op/<instance>` | op-plat 命令队列 |
| | `/sys/ipc/cmd/heap/<program>/<device>` | heap-plat 命令队列 |
| | `/sys/ipc/notify/vm` | VM 唤醒通知 |
| | `/sys/ipc/notify/done/<vtid>` | 操作完成通知 |
| | `/sys/config` | 全局配置 |
| | `/sys/counter/vtid` | vthread ID 自增计数器 |
| | `/sys/heartbeat/<id>` | 组件心跳 |
| `/metathread/` | — | 元线程运行时 (系统保留) |
| | `/metathread/<vtid>` | vthread 自身: `{pc, status}` |
| | `/metathread/<vtid>/[addr0,0]` | 操作码 (opcode) |
| | `/metathread/<vtid>/[addr0,-n]` | 第 n 个读取参数 |
| | `/metathread/<vtid>/[addr0,n]` | 第 n 个写入参数 |
| | `/metathread/<vtid>/<name>` | 命名槽位 (局部变量) |
| | `/metathread/<vtid>/[addr0,0]/` | 子栈 (CALL 产生) |
| 其他根路径 | `/models/` `/datasets/` 等 | 用户自由使用 |

## 指令格式

**dxlang 引号约定:**

| 引号 | 语义 | 示例 |
|------|------|------|
| `"..."` | 字符串字面量 | `"f32"`, `"[128]"`, `"hello"` |
| `'...'` | KV 空间 Key 路径 | `'/data/a'`, `'./ret'`, `'../parent'` |
| 无引号 | 变量名（形参/局部变量） | `A`, `alpha`, `my_var` |

**dxlang (源码层/编译层):**
```
opcode(read_p1, read_p2, ...) -> write_p1, write_p2
```

**执行层 (二维寻址):**
```
/metathread/<vtid>/[addr0, 0]  = "opcode"      ← addr1=0  → 操作码
/metathread/<vtid>/[addr0,-1]  = "param1"      ← addr1<0  → 读取参数
/metathread/<vtid>/[addr0, 1]  = "output1"     ← addr1>0  → 写入参数
```

`.` 相对路径 (`./mm`) 解析为 `/metathread/<vtid>/mm` (命名槽位)。

## Vthread 状态

| 状态 | 含义 |
|------|------|
| `init` | 已创建，待 VM 拾取 |
| `running` | VM 正在调度执行 |
| `wait` | 等待异步操作 (op-plat / heap-plat) |
| `error` | 执行出错 |
| `done` | 执行完毕，可 GC |

## CALL 语义

1. VM 读取 `/usr/func/<name>/` 源码层
2. 建立形参→实参映射
3. 逐条解析 dxlang → 形参替换 → 展开为 `[i,j]` 坐标
4. Pipeline 批量写入 `/metathread/<vtid>/[n,0]/` 子栈
5. PC 进入子栈首条指令

## RETURN 语义

1. 返回值写入父 CALL 指令的写参数槽位
2. 递归 DELETE 子栈 KV 路径
3. PC 恢复到父栈 CALL 的下一条

## 算子融合与拆分 (编译器)

| 操作 | 方向 | 说明 |
|------|------|------|
| 融合 (Fusion) | N→1 | 编译器将连续匹配指令替换为 fused 算子 |
| 拆分 (Split) | 1→N | Tensor 超过单卡上限时拆分 + 标注设备 |

编译器在 `/usr/func/` 层完成。

## Tensor 元信息

```json
{"dtype":"f32","shape":[1024,512],"byte_size":2097152,"device":"gpu0","address":{"type":"shm","shm_name":"/deepx_t_abc123"},"ctime":1714000000,"version":5}
```

## executor 目录

| 目录 | 角色 | 产出 |
|------|------|------|
| `deepx-core/` | 平台无关公共库：dtype / tensor / shmem / registry / stdutil / tensorfunc / tf / mem | `libdeepx_core.a` |
| `common-metal/` | **Metal HAL**：检测 macOS GPU 是否支持 Metal（`metal_device`），供 exop-metal / heap-metal 使用 | `libdeepx_metal_hal.a` |
| `exop-metal/` | Metal GPU 算子引擎（op-plat 实现之一） | `deepx-exop-metal` |
| `exop-cpu/` | CPU 算子引擎（op-plat 实现之一，无 HAL 依赖） | `deepx-exop-cpu` |
| `heap-metal/` | Metal GPU 堆管理（heap-plat 实现之一） | `deepx-heap-metal` |
| `heap-cpu/` | CPU 堆管理（heap-plat 实现之一，无 HAL 依赖） | `deepx-heap-cpu` |
| `io-metal/` | tensor I/O 平面（print/save/load） | `deepx-io-metal` |
| `vm/` | VM 解释执行：CALL 翻译、指令路由 | `deepx-vm` |

## 与 OS 进程对照

| OS 概念 | 元程对应 |
|---------|---------|
| 虚拟地址空间 | KV 空间 |
| 进程 | 一个 KV 空间实例 |
| 线程 | Vthread |
| 代码段 (.text) | /usr/func/ + /func/ |
| 堆段 (.data/.bss) | 非保留路径 (堆变量) |
| 栈段 | /metathread/<vtid>/ |
| PC | /metathread/<vtid> 的 pc 字段 |
| CALL/RET | CALL 翻译 → 子栈 / RETURN → DELETE 子栈 |
| 系统调用 | heap-plat / op-plat 命令 |

## codegen — Redis Key 代码生成

| 概念 | 说明 |
|------|------|
| 真源 | `spec/keys.yaml` — 唯一手动维护的 key 规范 |
| 生成器 | `tool/codegen/` — 纯 Go，读取 keys.yaml 生成三语言 SDK |
| 命令 | `make gen-keys` |
| Go 输出 | `executor/vm/internal/keys/keys.go` |
| C++ 输出 | `executor/deepx-core/include/deepx/key_defs.h` |
| TS 输出 | `tool/dashboard/frontend/src/api/keys.ts` |
