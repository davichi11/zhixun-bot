/**
 * Markdown 相关工具。
 *
 * 渲染交给 react-markdown（在组件里用），这里只放纯函数：
 * 提取标题、粗略估算字数、去掉 Markdown 标记等。
 */

/** 从 Markdown 中提取第一个一级/二级标题作为稿件标题。 */
export function extractTitle(markdown: string): string {
  const match = markdown.match(/^#{1,2}\s+(.+)$/m)
  return match ? match[1].trim() : ''
}

/** 去掉 Markdown 标记，得到纯文本（用于预览摘要）。 */
export function stripMarkdown(markdown: string): string {
  return markdown
    .replace(/```[\s\S]*?```/g, '')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, '')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/[*_>~-]/g, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}
