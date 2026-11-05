import { FileTextIcon } from 'lucide-react'
import { useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import type { Source } from '@/lib/api'
import { cn } from '@/lib/utils'

export type UiMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources?: Source[] | null
  pending?: boolean
  error?: string
}

function Sources({ sources }: { sources: Source[] }) {
  // One chip per file, tooltip shows the matched excerpt.
  const byFile = new Map<string, Source>()
  for (const s of sources) if (!byFile.has(s.filename)) byFile.set(s.filename, s)
  return (
    <div className="mt-2 flex flex-wrap gap-1.5" data-testid="sources">
      {[...byFile.values()].map((s) => (
        <span
          key={s.filename}
          title={s.content}
          className="inline-flex items-center gap-1 rounded-full border bg-background px-2 py-0.5 text-xs text-muted-foreground"
        >
          <FileTextIcon className="size-3" />
          {s.filename}
        </span>
      ))}
    </div>
  )
}

export function MessageList({ messages }: { messages: UiMessage[] }) {
  const bottomRef = useRef<HTMLDivElement>(null)
  const last = messages[messages.length - 1]
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end' })
  }, [messages.length, last?.content])

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-6">
      {messages.map((m) => (
        <div
          key={m.id}
          data-testid={`message-${m.role}`}
          className={cn('flex', m.role === 'user' ? 'justify-end' : 'justify-start')}
        >
          <div
            className={cn(
              'max-w-[85%] text-sm leading-relaxed',
              m.role === 'user'
                ? 'rounded-2xl rounded-br-sm bg-primary px-4 py-2.5 whitespace-pre-wrap text-primary-foreground'
                : 'w-full',
            )}
          >
            {m.role === 'assistant' ? (
              <>
                {m.content ? (
                  <div className="prose-chat">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                  </div>
                ) : m.pending ? (
                  <span className="inline-flex gap-1 py-2" aria-label="Thinking">
                    <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:-0.3s]" />
                    <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:-0.15s]" />
                    <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground" />
                  </span>
                ) : null}
                {m.sources && m.sources.length > 0 && <Sources sources={m.sources} />}
                {m.error && (
                  <p className="mt-2 text-xs text-destructive" role="alert">
                    {m.error}
                  </p>
                )}
              </>
            ) : (
              m.content
            )}
          </div>
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  )
}
