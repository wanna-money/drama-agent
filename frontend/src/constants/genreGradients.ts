// 作品卡片头图的渐变色块,按故事类型(genre)取色。CSS 类名在 index.css 里定义
// (.project-cover-*),这里只负责"取值 → 类名"的映射,不内联颜色 style(规范 8)。
// 权威取值链:GENRES(前端展示层)← 后端 db.enums.Genre。未列出的类型(包括
// 后续新增类型)一律落到 project-cover-default,不会因为漏配而渲染出无样式的空白卡头。
const KNOWN_GENRES = new Set(['thriller', 'romance', 'action', 'fantasy', 'comedy', 'drama'])

export function genreCoverClass(genre: string): string {
  return KNOWN_GENRES.has(genre) ? `project-cover-${genre}` : 'project-cover-default'
}
