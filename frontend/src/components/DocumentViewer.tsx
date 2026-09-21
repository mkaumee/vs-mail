import { useEffect, useState } from 'react'
import { Download, ExternalLink, X } from 'lucide-react'
import { api, type DocumentPreview } from '@/api'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'

type Loaded = { preview: DocumentPreview; url: string | null }

export default function DocumentViewer({
  emailId,
  role,
  onClose,
}: {
  emailId: string
  role: 'SI' | 'BL'
  onClose: () => void
}) {
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  const [downloading, setDownloading] = useState(false)

  useEffect(() => {
    let active = true
    let objectUrl: string | null = null
    setLoaded(null)
    setError(null)

    const load = async () => {
      try {
        const preview = await api.documentPreview(emailId, role)
        if (preview.mode === 'pdf' || preview.mode === 'image') {
          const blob = await api.documentFile(emailId, role)
          objectUrl = URL.createObjectURL(blob)
        }
        if (!active) {
          if (objectUrl) URL.revokeObjectURL(objectUrl)
          objectUrl = null
          return
        }
        setLoaded({ preview, url: objectUrl })
      } catch (cause) {
        if (active) setError((cause as Error).message)
      }
    }
    void load()

    return () => {
      active = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [emailId, role, retry])

  const download = async () => {
    setDownloading(true)
    try {
      const blob = await api.documentFile(emailId, role)
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = loaded?.preview.name || `${emailId}-${role}`
      anchor.click()
      setTimeout(() => URL.revokeObjectURL(url), 0)
    } catch (cause) {
      setError((cause as Error).message)
    } finally {
      setDownloading(false)
    }
  }

  const label = role === 'SI' ? 'Shipping instruction' : 'Bill of lading'

  return (
    <section className="overflow-hidden rounded-lg border bg-background" aria-label={`${label} viewer`}>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2">
        <div className="min-w-0">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {label}
          </div>
          <div className="truncate text-sm font-medium">
            {loaded?.preview.name || 'Loading document…'}
          </div>
        </div>
        <div className="flex items-center gap-1">
          {loaded?.url && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => window.open(loaded.url!, '_blank', 'noopener,noreferrer')}
            >
              <ExternalLink />
              Full size
            </Button>
          )}
          {loaded && (
            <Button size="sm" variant="ghost" loading={downloading} onClick={download}>
              <Download />
              Download
            </Button>
          )}
          <Button size="icon-sm" variant="ghost" aria-label="Close document" onClick={onClose}>
            <X />
          </Button>
        </div>
      </div>

      {!loaded && !error && (
        <div className="flex h-48 items-center justify-center gap-2 text-sm text-muted-foreground">
          <Spinner />
          Loading document…
        </div>
      )}

      {error && (
        <div className="flex min-h-36 flex-col items-center justify-center gap-3 p-5 text-center">
          <p className="text-sm text-defect">{error}</p>
          <Button size="sm" variant="outline" onClick={() => setRetry((value) => value + 1)}>
            Try again
          </Button>
        </div>
      )}

      {loaded?.preview.mode === 'pdf' && loaded.url && (
        <iframe
          className="h-[65vh] min-h-[32rem] w-full bg-white"
          src={loaded.url}
          title={`${label}: ${loaded.preview.name}`}
        />
      )}

      {loaded?.preview.mode === 'image' && loaded.url && (
        <div className="grid max-h-[65vh] place-items-center overflow-auto bg-muted/30 p-4">
          <img className="max-w-full" src={loaded.url} alt={`${label}: ${loaded.preview.name}`} />
        </div>
      )}

      {loaded?.preview.mode === 'text' && (
        <>
          <div className="border-b bg-muted/30 px-4 py-2 text-xs text-muted-foreground">
            Content preview. Download the original for exact document formatting.
          </div>
          <pre className="max-h-[65vh] overflow-auto whitespace-pre-wrap p-4 text-sm leading-relaxed">
            {loaded.preview.text || '(No text found in this document.)'}
          </pre>
        </>
      )}

      {loaded?.preview.mode === 'download' && (
        <div className="p-5 text-sm text-muted-foreground">
          {loaded.preview.error || 'This file type cannot be previewed safely in the browser.'}
          {' '}Use Download to open the original file.
        </div>
      )}
    </section>
  )
}
