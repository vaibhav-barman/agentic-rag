import { FileTextIcon, Loader2Icon, Trash2Icon, UploadIcon } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type DragEvent } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { deleteDocument, listDocuments, uploadDocument, type DocumentRow } from '@/lib/api'
import { cn } from '@/lib/utils'

const ACCEPT = '.txt,.md,.pdf'
const MAX_MB = 10

type Uploading = { key: string; filename: string }

function FileIcon({ children }: { children: React.ReactNode }) {
  return (
    <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-secondary text-muted-foreground">
      {children}
    </span>
  )
}

function StatusBadge({ status }: { status: DocumentRow['status'] }) {
  return (
    <Badge
      variant={status === 'failed' ? 'destructive' : 'outline'}
      className={cn(status === 'completed' && 'border-primary/30 bg-primary/10 text-primary')}
      data-testid="doc-status"
    >
      {status}
    </Badge>
  )
}

export default function Ingestion() {
  const [docs, setDocs] = useState<DocumentRow[]>([])
  const [uploading, setUploading] = useState<Uploading[]>([])
  const [error, setError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
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

  const uploadFiles = async (files: FileList | File[]) => {
    setError(null)
    for (const file of Array.from(files)) {
      const ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase()
      if (!ACCEPT.split(',').includes(ext)) {
        setError(`${file.name}: unsupported type. Allowed: ${ACCEPT}`)
        continue
      }
      if (file.size > MAX_MB * 1024 * 1024) {
        setError(`${file.name}: larger than ${MAX_MB} MB`)
        continue
      }
      const key = `${file.name}-${Date.now()}`
      setUploading((u) => [...u, { key, filename: file.name }])
      try {
        const doc = await uploadDocument(file)
        if (doc.status === 'failed') setError(`${file.name}: ${doc.error ?? 'processing failed'}`)
      } catch (err) {
        setError(`${file.name}: ${err instanceof Error ? err.message : 'upload failed'}`)
      } finally {
        setUploading((u) => u.filter((x) => x.key !== key))
        await refresh()
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
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed')
    }
    await refresh()
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto flex max-w-3xl flex-col gap-8 px-5 py-10">
        <div>
          <h1 className="text-3xl font-medium">Documents</h1>
          <p className="mt-2 max-w-prose text-base leading-relaxed text-muted-foreground">
            Add files and Glossa will search them when you ask a question. Text, Markdown and PDF, up to {MAX_MB} MB each.
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
            'flex cursor-pointer flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed px-6 py-14 text-center transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/30',
            dragging ? 'border-primary bg-primary/5' : 'border-input bg-card hover:border-primary/60',
          )}
        >
          <span className="flex size-11 items-center justify-center rounded-full bg-primary/10 text-primary">
            <UploadIcon className="size-5" />
          </span>
          <p className="text-base font-medium">Drop files here or click to browse</p>
          <p className="text-sm text-muted-foreground">{ACCEPT.replaceAll(',', ', ')}</p>
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

        <ul className="divide-y border-y" data-testid="document-list" aria-label="Your files">
          {uploading.map((u) => (
            <li key={u.key} className="flex items-center gap-4 py-4 text-sm">
              <FileIcon>
                <Loader2Icon className="size-4 animate-spin motion-reduce:animate-none" />
              </FileIcon>
              <span className="flex-1 truncate text-base">{u.filename}</span>
              <Badge variant="outline">processing</Badge>
            </li>
          ))}
          {docs.map((d) => (
            <li key={d.id} className="flex items-center gap-4 py-4 text-sm" data-testid="document-row">
              <FileIcon>
                <FileTextIcon className="size-4" />
              </FileIcon>
              <div className="min-w-0 flex-1">
                <p className="truncate text-base font-medium">{d.filename}</p>
                <p className="truncate text-sm text-muted-foreground">
                  {new Date(d.created_at).toLocaleString()}
                  {d.status === 'completed' && `, ${d.chunk_count} passage${d.chunk_count === 1 ? '' : 's'}`}
                  {d.status === 'failed' && d.error && `, ${d.error}`}
                </p>
              </div>
              <StatusBadge status={d.status} />
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
            <li className="py-8 text-center text-sm text-muted-foreground">No documents yet.</li>
          )}
        </ul>
      </div>
    </div>
  )
}
