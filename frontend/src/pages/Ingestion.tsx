import { FileTextIcon, Loader2Icon, Trash2Icon, UploadIcon } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type DragEvent } from 'react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { deleteDocument, listDocuments, uploadDocument, type DocumentRow } from '@/lib/api'
import { supabase } from '@/lib/supabase'
import { cn } from '@/lib/utils'

const ACCEPT = '.pdf,.docx,.html,.htm,.md,.txt'
const MAX_MB = 10

type Uploading = { key: string; filename: string }

const inFlight = (d: DocumentRow) => d.status === 'pending' || d.status === 'processing'

/** Insert or replace a row, ignoring events older than what is already shown. */
function upsert(docs: DocumentRow[], incoming: DocumentRow): DocumentRow[] {
  const current = docs.find((d) => d.id === incoming.id)
  if (!current) return [incoming, ...docs]
  if (current.updated_at && incoming.updated_at && incoming.updated_at < current.updated_at) return docs
  return docs.map((d) => (d.id === incoming.id ? { ...d, ...incoming } : d))
}

function FileIcon({ children }: { children: React.ReactNode }) {
  return (
    <span className="flex size-9 shrink-0 items-center justify-center rounded-md border text-muted-foreground">
      {children}
    </span>
  )
}

function StatusBadge({ status }: { status: DocumentRow['status'] | 'uploading' }) {
  const busy = status === 'processing' || status === 'pending' || status === 'uploading'
  return (
    <Badge
      variant={status === 'failed' ? 'destructive' : 'outline'}
      className={cn(status === 'completed' && 'border-primary/30 bg-primary/10 text-primary')}
      data-testid="doc-status"
    >
      {busy && <Loader2Icon className="animate-spin motion-reduce:animate-none" aria-hidden="true" />}
      {status === 'pending' ? 'queued' : status}
    </Badge>
  )
}

function formatSize(bytes: number | null) {
  if (!bytes) return null
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** The facts under a filename: when, how big, and what ingestion did with it. */
function details(d: DocumentRow) {
  const parts = [new Date(d.created_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })]
  const size = formatSize(d.file_size)
  if (size) parts.push(size)
  if (d.status === 'completed') {
    parts.push(`${d.chunk_count} passage${d.chunk_count === 1 ? '' : 's'}`)
    const s = d.ingest_stats
    // Only worth showing when the record manager actually saved work.
    if (s && s.reused > 0) parts.push(`${s.embedded} new, ${s.reused} reused`)
  }
  return parts
}

export default function Ingestion() {
  const [docs, setDocs] = useState<DocumentRow[]>([])
  const [uploading, setUploading] = useState<Uploading[]>([])
  const [error, setError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const [live, setLive] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const refresh = useCallback(async () => {
    try {
      setDocs(await listDocuments())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load documents')
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  // Supabase Realtime: every status change the backend writes arrives here as a row
  // event. Row-Level Security means we only ever receive our own documents.
  useEffect(() => {
    const channel = supabase
      .channel('documents-status')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'documents' }, (payload) => {
        if (payload.eventType === 'DELETE') {
          const id = (payload.old as { id?: string }).id
          setDocs((prev) => prev.filter((d) => d.id !== id))
        } else {
          setDocs((prev) => upsert(prev, payload.new as DocumentRow))
        }
      })
      .subscribe((status) => setLive(status === 'SUBSCRIBED'))
    return () => {
      void supabase.removeChannel(channel)
    }
  }, [])

  // Safety net: if the Realtime connection is down, poll while something is in flight.
  const anyInFlight = docs.some(inFlight)
  useEffect(() => {
    if (live || !anyInFlight) return
    const timer = setInterval(() => void refresh(), 3000)
    return () => clearInterval(timer)
  }, [live, anyInFlight, refresh])

  const uploadFiles = async (files: FileList | File[]) => {
    setError(null)
    for (const file of Array.from(files)) {
      const ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase()
      if (!ACCEPT.split(',').includes(ext)) {
        setError(`${file.name}: unsupported type. Allowed: ${ACCEPT.replaceAll(',', ', ')}`)
        continue
      }
      if (file.size > MAX_MB * 1024 * 1024) {
        setError(`${file.name}: larger than ${MAX_MB} MB`)
        continue
      }
      const key = `${file.name}-${Date.now()}`
      setUploading((u) => [...u, { key, filename: file.name }])
      try {
        const { action, ...doc } = await uploadDocument(file)
        setDocs((prev) => upsert(prev, doc))
        if (doc.status === 'failed') setError(`${file.name}: ${doc.error ?? 'could not be stored'}`)
        else if (action === 'unchanged') toast(`${file.name} is already up to date`, { description: 'Same content as before, so nothing was re-processed.' })
        else if (action === 'duplicate') toast(`Same content as ${doc.filename}`, { description: `${file.name} was not added again.` })
        else if (action === 'updated') toast(`Updating ${file.name}`, { description: 'Only the passages that changed are re-embedded.' })
      } catch (err) {
        setError(`${file.name}: ${err instanceof Error ? err.message : 'upload failed'}`)
      } finally {
        setUploading((u) => u.filter((x) => x.key !== key))
      }
    }
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    if (e.dataTransfer.files.length) void uploadFiles(e.dataTransfer.files)
  }

  const remove = async (id: string) => {
    setError(null)
    try {
      await deleteDocument(id)
      setDocs((prev) => prev.filter((d) => d.id !== id))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed')
      await refresh()
    }
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto flex max-w-3xl flex-col gap-9 px-5 py-12 sm:py-16">
        <div>
          <h1 className="text-[clamp(2.5rem,6vw,3.75rem)] leading-none font-normal tracking-[-0.03em]">Documents</h1>
          <p className="mt-5 max-w-[36rem] font-serif text-lg leading-relaxed text-muted-foreground">
            Add files and Glossa reads them, so it can answer from them. PDF, Word, HTML, Markdown and
            plain text, up to {MAX_MB} MB each. Add a file again and only the parts that changed are re-read.
          </p>
        </div>

        <div
          role="button"
          tabIndex={0}
          data-testid="dropzone"
          aria-label="Add files"
          onClick={() => inputRef.current?.click()}
          onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={cn(
            'group flex cursor-pointer items-center gap-5 rounded-xl border border-dashed px-6 py-7 text-left transition-colors outline-none focus-visible:border-primary focus-visible:ring-3 focus-visible:ring-ring/25',
            dragging ? 'border-primary bg-primary/10' : 'border-input hover:border-primary',
          )}
        >
          <span className="flex size-11 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground transition-transform group-hover:-translate-y-0.5 motion-reduce:transition-none">
            <UploadIcon className="size-5" />
          </span>
          <span>
            <span className="block text-base font-medium">Drop files here, or choose them</span>
            <span className="mt-0.5 block text-sm text-muted-foreground">{ACCEPT.replaceAll(',', ', ')}</span>
          </span>
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPT}
            multiple
            hidden
            data-testid="file-input"
            onChange={(e) => {
              if (e.target.files) void uploadFiles(e.target.files)
              e.target.value = ''
            }}
          />
        </div>

        {error && (
          <p className="text-sm text-destructive" role="alert">
            {error}
          </p>
        )}

        <div>
          <div className="mb-3 flex items-baseline justify-between gap-4">
            <h2 className="text-2xl font-normal">Your files</h2>
            <p className="flex items-center gap-2 text-xs text-muted-foreground" data-testid="live-status">
              <span
                className={cn('size-1.5 rounded-full', live ? 'bg-primary' : 'bg-muted-foreground/50')}
                aria-hidden="true"
              />
              {live ? 'Live status updates' : 'Connecting to live updates…'}
            </p>
          </div>
          <ul className="divide-y border-y" data-testid="document-list" aria-label="Your files">
            {uploading.map((u) => (
              <li key={u.key} className="flex items-center gap-4 py-4 text-sm">
                <FileIcon>
                  <Loader2Icon className="size-4 animate-spin motion-reduce:animate-none" />
                </FileIcon>
                <span className="flex-1 truncate text-base">{u.filename}</span>
                <StatusBadge status="uploading" />
              </li>
            ))}
            {docs.map((d) => (
              <li key={d.id} className="flex items-start gap-4 py-4 text-sm" data-testid="document-row">
                <FileIcon>
                  <FileTextIcon className="size-4" />
                </FileIcon>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-base font-medium">{d.filename}</p>
                  <p
                    className="mt-0.5 flex flex-wrap gap-x-3.5 text-sm text-muted-foreground"
                    data-testid="doc-detail"
                  >
                    {details(d).map((part) => (
                      <span key={part}>{part}</span>
                    ))}
                  </p>
                  {d.status === 'failed' && d.error && (
                    <p className="mt-1.5 text-sm text-destructive" data-testid="doc-error">
                      {d.error}
                    </p>
                  )}
                  {d.status === 'completed' && d.metadata?.summary && (
                    <p className="mt-2 line-clamp-2 max-w-[60ch] font-serif text-base leading-snug text-foreground/85">
                      {d.metadata.summary}
                    </p>
                  )}
                  {d.status === 'completed' && (d.metadata?.document_type || d.metadata?.topics?.length) && (
                    <div className="mt-2 flex flex-wrap gap-1.5" data-testid="doc-metadata">
                      {d.metadata.document_type && (
                        <Badge variant="secondary" className="capitalize">
                          {d.metadata.document_type}
                        </Badge>
                      )}
                      {d.metadata.topics?.map((t) => (
                        <Badge key={t} variant="outline" className="font-normal text-muted-foreground">
                          {t}
                        </Badge>
                      ))}
                    </div>
                  )}
                </div>
                <div className="flex h-9 items-center">
                  <StatusBadge status={d.status} />
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  className="text-muted-foreground hover:text-destructive"
                  aria-label={`Delete ${d.filename}`}
                  onClick={() => remove(d.id)}
                >
                  <Trash2Icon className="size-4" />
                </Button>
              </li>
            ))}
            {docs.length === 0 && uploading.length === 0 && (
              <li className="py-10 text-sm text-muted-foreground">No documents yet. Add one above to ask about it.</li>
            )}
          </ul>
        </div>
      </div>
    </div>
  )
}
