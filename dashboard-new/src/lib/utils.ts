/** Escape HTML for safe insertion */
export function esc(s: string): string {
  const d = document.createElement('div')
  d.textContent = s
  return d.innerHTML
}

/** Format ms elapsed into human string */
export function formatElapsed(ms: number): string {
  const s = Math.floor(ms / 1000)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const rem = s % 60
  return `${m}m ${rem < 10 ? '0' : ''}${rem}s`
}

/** Simple markdown → HTML renderer (matches original dashboard) */
export function renderMarkdown(text: string): string {
  if (!text) return ''
  let html = text
  html = html.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_m, _lang, code) =>
    `<pre><code>${code.trim()}</code></pre>`)
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>')
  html = html.replace(/^#### (.+)$/gm, '<h4>$1</h4>')
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>')
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>')
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>')
  html = html.replace(/^---$/gm, '<hr>')
  html = html.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>')
  html = html.replace(/^[ \t]*\*[ \t]+(.+)$/gm, '<li>$1</li>')
  html = html.replace(/^[ \t]*-[ \t]+(.+)$/gm, '<li>$1</li>')
  html = html.replace(/((?:<li>.*<\/li>\n?)+)/g, '<ul>$1</ul>')
  html = html.replace(/^\d+\.[ \t]+(.+)$/gm, '<li>$1</li>')
  html = html.replace(/((?:<li>.*<\/li>\n?){2,})/g, (match) =>
    match.indexOf('<ul>') === -1 ? `<ol>${match}</ol>` : match)
  html = html.replace(/\$\\text\{([^}]+)\}\$/g, '$1')
  html = html.replace(/\n\n+/g, '</p><p>')
  html = html.replace(/([^>])\n([^<])/g, '$1<br>$2')
  html = `<p>${html}</p>`
  html = html.replace(/<p><\/p>/g, '')
  html = html.replace(/<p>(<h[1-4]>)/g, '$1')
  html = html.replace(/(<\/h[1-4]>)<\/p>/g, '$1')
  html = html.replace(/<p>(<ul>)/g, '$1')
  html = html.replace(/(<\/ul>)<\/p>/g, '$1')
  html = html.replace(/<p>(<ol>)/g, '$1')
  html = html.replace(/(<\/ol>)<\/p>/g, '$1')
  html = html.replace(/<p>(<pre>)/g, '$1')
  html = html.replace(/(<\/pre>)<\/p>/g, '$1')
  html = html.replace(/<p>(<hr>)/g, '$1')
  html = html.replace(/(<hr>)<\/p>/g, '$1')
  return html
}

/** Parse <thought> tags from assistant content */
export function parseThoughts(text: string): Array<{ type: 'thought' | 'text'; text: string }> {
  const parts: Array<{ type: 'thought' | 'text'; text: string }> = []
  const re = /<thought>([\s\S]*?)<\/thought>/gi
  let last = 0
  let match: RegExpExecArray | null
  while ((match = re.exec(text)) !== null) {
    if (match.index > last) parts.push({ type: 'text', text: text.substring(last, match.index) })
    parts.push({ type: 'thought', text: match[1] })
    last = re.lastIndex
  }
  if (last < text.length) parts.push({ type: 'text', text: text.substring(last) })
  return parts
}

/** Copy text to clipboard */
export async function copyToClipboard(text: string): Promise<void> {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text)
    return
  }
  const ta = document.createElement('textarea')
  ta.value = text
  ta.style.position = 'fixed'
  ta.style.left = '-9999px'
  document.body.appendChild(ta)
  ta.select()
  document.execCommand('copy')
  document.body.removeChild(ta)
}
