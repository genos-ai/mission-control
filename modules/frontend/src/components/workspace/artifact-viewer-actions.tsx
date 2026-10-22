/**
 * Copy and Download for the artifact on screen. Both act on the stored
 * content exactly as the API returned it, not on the rendered view.
 */

import { Copy, Download } from 'lucide-react'
import toast from 'react-hot-toast'
import { Button } from '@/components/ui/button'
import type { MissionArtifact } from '@/hooks/use-mission-artifacts'

// File extension and media type by content type; anything else saves as plain text.
const FILE_KIND: Record<string, { ext: string; mime: string }> = {
  markdown: { ext: 'md', mime: 'text/markdown' },
  json: { ext: 'json', mime: 'application/json' },
}
const PLAIN_TEXT = { ext: 'txt', mime: 'text/plain' }

function fileNameFor(artifact: MissionArtifact, ext: string): string {
  const base = artifact.title.trim().replace(/[^\w.-]+/g, '-').replace(/^-+|-+$/g, '') || 'artifact'
  // A title that already names a file (watchlist.csv) keeps its own extension.
  return /\.\w{1,5}$/.test(base) ? base : `${base}.${ext}`
}

export function ArtifactViewerActions({ artifact }: { artifact: MissionArtifact }) {
  const text = artifact.content_text
  const hasContent = !!text

  async function copy() {
    if (!text) return
    try {
      await navigator.clipboard.writeText(text)
      toast.success('Copied to clipboard')
    } catch {
      toast.error('Could not copy to the clipboard')
    }
  }

  function download() {
    if (!text) return
    const kind = FILE_KIND[artifact.content_type] ?? PLAIN_TEXT
    const url = URL.createObjectURL(new Blob([text], { type: `${kind.mime};charset=utf-8` }))
    const link = document.createElement('a')
    link.href = url
    link.download = fileNameFor(artifact, kind.ext)
    // Attached for the click because some browsers ignore a detached anchor;
    // the URL is released afterwards so the download can start first.
    document.body.appendChild(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 0)
  }

  return (
    <div className="flex shrink-0 items-center gap-2">
      <Button variant="secondary" disabled={!hasContent} onClick={copy}>
        <Copy className="h-3.5 w-3.5" />
        Copy
      </Button>
      <Button variant="secondary" disabled={!hasContent} onClick={download}>
        <Download className="h-3.5 w-3.5" />
        Download
      </Button>
    </div>
  )
}
