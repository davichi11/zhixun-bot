# components/ui

shadcn/ui 基础组件放这里（Button / Input / Dialog / Table ...）。

## 为什么不用现成组件库

shadcn/ui 的做法是把组件**源码复制进项目**，而不是装一个依赖：

- 想改样式直接改文件，不用和组件库的版本/主题系统较劲
- 不会被组件库的 breaking change 绑架
- 体积可控：只有用到的组件才会被打包

## 怎么加组件

```bash
pnpm dlx shadcn@latest add button dialog table
```

组件会生成在本目录下，然后按需改造。

第 1 篇暂未引入任何组件，页面用 Tailwind 原生样式实现。
第 5 篇做审校面板时会引入 `table` / `dialog` / `textarea`。
