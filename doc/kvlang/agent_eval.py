#!/usr/bin/env python3
"""agent_eval — 以 deep-dive.md 为教学文档，验证空记忆模型对 kvlang 的理解正确率。

用法:
  export KVLANG_EVAL_API_BASE=https://...   # OpenAI 兼容 API base（不含 /v1）
  export KVLANG_EVAL_API_KEY=sk-...
  export KVLANG_EVAL_MODEL=qwen3.7-plus     # 可选
  python3 doc/kvlang/agent_eval.py

对每个任务：deep-dive.md + 任务描述 → LLM 生成 kvlang 代码 → 实际运行 → stdout 比对。
生成代码与失败详情保存于 /tmp/agent_eval/。
"""
from __future__ import annotations
import json, os, re, subprocess, sys, urllib.request, uuid
from pathlib import Path

ROOT = Path("/home/peng.li24/github.com/array2d/kvlang")
KV = str(ROOT / "kvlang")
DOC = Path(__file__).resolve().parent / "deep-dive.md"
OUT = Path("/tmp/agent_eval")

API_BASE = os.environ.get("KVLANG_EVAL_API_BASE", "").rstrip("/")
API_KEY  = os.environ.get("KVLANG_EVAL_API_KEY", "")
MODEL    = os.environ.get("KVLANG_EVAL_MODEL", "qwen3.7-plus")

# (任务名, 任务描述, 期望 stdout 行)
# 覆盖 deep-dive.md 核心概念：rwir、无返回值/写参、多写参、只读参、lib、init、dict、.
TASKS = [
    ("write_param",
     "声明一个函数 add，签名包含两个读参 A:int 和 B:int，一个写参 C:int。函数体计算 A+B 并写入 C。调用 add(3,4) 将结果映射到局部变量 s，打印 s。",
     ["7"]),

    ("multi_write",
     "声明一个函数 double_triple，签名包含一个读参 n:int，两个写参 d:int 和 t:int。函数体计算 n*2→d, n*3→t。调用 double_triple(5) 将结果映射到 a 和 b，分两行打印 a 和 b。",
     ["10", "15"]),

    ("readonly_param",
     "声明一个函数 f，签名有一个读参 X:int，无写参。函数体内计算 X+1 后写入局部变量 r（不要写读参 X）。调用 f(41) 映射到 result，打印 result。",
     ["42"]),

    ("init_block",
     "在 init { } 块中，初始化 total=0，i=1，用 while 循环 i<=5 每次 total+i→total 且 i+1→i。循环结束后打印 total。不写 def main，直接用 init 块。",
     ["15"]),

    ("dict_literal",
     "用 {} 字面量创建 dict d = { name=\"kv\"; ver=1 }。分两行打印 d.name 和 d.ver。",
     ["kv", "1"]),

    ("if_else",
     "判断 42 是否能被 7 整除（用 % 取余，比较余数是否等于 0）。是则打印 yes，否则打印 no。",
     ["yes"]),

    ("while_sum",
     "用 while 循环计算 1 到 10 的累加和，循环变量 i 自行管理，结果存入 s，打印 55。",
     ["55"]),

    ("dual_arrow",
     "分别用 -> 和 <- 两种形态：先计算 3*4→r 打印 r；再 s <- 5*6 打印 s。注意每种形态写槽位置不同。用 -> 时写槽在右侧，用 <- 时写槽在左侧。",
     ["12", "30"]),

    ("number_type_cast",
     "用 int8 算子将 300 转换为 int8 类型，存入 v，打印 v 的值。",
     ["44"]),

    ("string_concat",
     "把字符串 'hello' 和 ' world' 拼接后存入 g，打印 g。",
     ["hello world"]),

    ("fib_recursive",
     "定义递归函数 fib(n) 计算第 n 个斐波那契数（fib(1)=1, fib(2)=1），使用写参形式。调用 fib(10) 并打印结果。",
     ["55"]),

    ("lib_namespace",
     "用 lib mymath { } 命名空间声明一个函数 twice，接受读参 x:int，写参 r:int，计算 x*2→r。调用 mymath.twice(21) 映射到 result 并打印 result。",
     ["42"]),
]

SYSTEM = """你是 kvlang 程序员。以下 deep-dive.md 是 kvlang 的完整设计文档，语法以其中示例为准。
只输出可直接运行、无 import 的 kvlang 代码；不要 markdown 围栏、不要解释文字。

关键注意：
- -> 写槽必须是位置（裸名、/abs、base.名），绝对不能写字面量
- 局部变量用裸名（如 r、s、total），不用 ./ 前缀
- 函数通过写参返回结果，不是 return 值；调用时用 f() -> slot 映射写参
- 读参在函数体内只读，想改值就拷贝到局部变量
- while 条件用 (cond)、循环体用 { }"""


def chat(doc_text: str, task: str) -> str:
    sid = str(uuid.uuid4())
    req = urllib.request.Request(
        API_BASE + "/v1/chat/completions",
        data=json.dumps({
            "model": MODEL,
            "temperature": 0,
            "user": sid,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"# kvlang 设计文档 (deep-dive.md)\n\n{doc_text}\n\n---\n\n任务：{task}\n程序 stdout 必须恰好满足任务要求，逐行精确。只输出 kvlang 代码。"},
            ],
        }).encode(),
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "X-Session-Id": sid,
            "Connection": "close",
        },
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        body = json.loads(r.read())
    return body["choices"][0]["message"]["content"]


def strip_fences(code: str) -> str:
    code = code.strip()
    m = re.match(r"^```[\w]*\n(.*?)\n?```$", code, re.S)
    return m.group(1) if m else code


def run_kv(path: Path) -> tuple[str, str]:
    subprocess.run(["kvspace", "clear"], capture_output=True, timeout=10)
    r = subprocess.run([KV, str(path)], capture_output=True, text=True, timeout=60, cwd=str(ROOT))
    return r.stdout, r.stderr


def main() -> None:
    if not API_BASE or not API_KEY:
        sys.exit("需设置 KVLANG_EVAL_API_BASE / KVLANG_EVAL_API_KEY 环境变量")
    doc_text = DOC.read_text()
    OUT.mkdir(parents=True, exist_ok=True)
    passed = 0
    for name, task, expect in TASKS:
        try:
            code = strip_fences(chat(doc_text, task))
        except Exception as e:
            print(f"❌ {name}: API 失败 {e}")
            continue
        src = OUT / f"{name}.kv"
        src.write_text(code + "\n")
        try:
            stdout, stderr = run_kv(src)
        except subprocess.TimeoutExpired:
            print(f"❌ {name}: 运行超时（生成代码见 {src}）")
            continue
        got = [ln for ln in stdout.strip().splitlines() if ln.strip()]
        if got == expect:
            passed += 1
            print(f"✅ {name}")
        else:
            (OUT / f"{name}.fail.txt").write_text(
                f"task: {task}\nexpect: {expect}\ngot: {got}\nstderr: {stderr[-500:]}\ncode:\n{code}\n")
            print(f"❌ {name}: 期望 {expect}，得到 {got}")
    total = len(TASKS)
    print(f"\n══ 模型 {MODEL} deep-dive 理解正确率: {passed}/{total} = {passed * 100 // total}% ══")


if __name__ == "__main__":
    main()
