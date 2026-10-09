export function embedUrl(value: string): string | null {
  try {
    const url = new URL(value)
    if (url.protocol !== 'https:') return null
    if (url.hostname === 'youtu.be') return `https://www.youtube-nocookie.com/embed/${encodeURIComponent(url.pathname.slice(1))}?rel=0`
    if (['www.youtube.com', 'youtube.com', 'www.youtube-nocookie.com'].includes(url.hostname)) {
      const id = url.searchParams.get('v') || url.pathname.split('/embed/')[1]
      return id ? `https://www.youtube-nocookie.com/embed/${encodeURIComponent(id)}?rel=0` : null
    }
    if (url.hostname === 'video.cs50.io') {
      return url.href
    }
    if (['www.bilibili.com', 'bilibili.com'].includes(url.hostname)) {
      const bvid = url.pathname.match(/BV[a-zA-Z0-9]+/)?.[0]
      return bvid ? `https://player.bilibili.com/player.html?bvid=${encodeURIComponent(bvid)}&page=${Math.max(1, Number(url.searchParams.get('p')) || 1)}&autoplay=0` : null
    }
    if (url.hostname === 'player.bilibili.com') return url.href
  } catch { /* Invalid URL has no embedded player. */ }
  return null
}
export function safeLink(value: string): string | null {
  try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? url.href : null } catch { return null }
}
