# kvlang-design

Design documentation, architecture specs, Claude project rules, and todo tracking for [kvlang](https://github.com/array2d/kvlang).

## Structure

```
.claude/                        Claude project rules and standards
  claude.md                     Core design principles (p0–p4)
  最高文章规范.md               Article/doc writing standards
  测试验证清单.md               Test verification checklist
  设计文档标准审查.md           Design doc review standard

最高标准设计.md                 Root design spec (address space, execution model)

internal/
  ast/最高标准设计.md           HIR/LIR type system
  parser/最高标准设计.md        Frontend pipeline
  lower/最高标准设计.md         Control flow lowering
  layoutcode/最高标准设计.md    AST → KV layout
  kvcpu/最高标准设计.md         CPU execution model
  kvspace/最高标准设计.md       KV storage interface
  keytree/最高标准设计.md       Key tree schema
  */todo.md                     Per-package improvement todos

doc/
  LANGUAGE_SPEC.md              Formal language specification
  kvlang/正式/                  Formal grammar and dev guide
  kvlang/草稿/                  Draft design documents
  kvlang/设计/                  Design scenarios and analysis

issue/                          Tracked issues and verification notes
post/                           Blog posts and external articles
```

## Usage

This repo is consumed as a git submodule at `kvlang-design/` inside the main [kvlang](https://github.com/array2d/kvlang) repo:

```bash
git submodule update --init kvlang-design
```

## Design tree

Design specs form a tree rooted at `最高标准设计.md`.
Every package implementation must conform to all ancestor specs on its path.
See `.claude/claude.md` for the full rule set.
