import { useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { SourceNote } from '@/components/chat/SourceNote'
import { ToolSteps } from '@/components/chat/ToolSteps'
import type { Source, Step } from '@/lib/api'

export type UiMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources?: Source[] | null
  steps?: Step[] | null
  pending?: boolean
  error?: string
}

/** Cited files and web pages sit in the right margin on wide screens and under the answer on narrow ones. */
function Sources({ sources }: { sources: Source[] }) {
  // One note per file or page; the best-matching excerpt comes first.
  const unique = new Map<string, Source>()
  for (const s of sources) {
    const key = s.url ?? s.filename ?? ''
    if (key && !unique.has(key)) unique.set(key, s)
  }
  return (
    <aside className="flex flex-col gap-4 lg:pt-1.5" data-testid="sources" aria-label="Sources">
      {[...unique.entries()].map(([key, s]) => (
        <SourceNote
          key={key}
          filename={s.url ? (s.title ?? s.url) : (s.filename ?? '')}
          url={s.url}
          excerpt={s.content}
        />
      ))}
    </aside>
  )
}

export function MessageList({ messages }: { messages: UiMessage[] }) {
  const bottomRef = useRef<HTMLDivElement>(null)
  const last = messages[messages.length - 1]
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end' })
  }, [messages.length, last?.content])

  return (
    <div className="mx-auto flex w-full max-w-[64rem] flex-col gap-10 px-5 py-10">
      {messages.map((m) =>
        m.role === 'user' ? (
          <div key={m.id} data-testid="message-user" className="lg:max-w-[44rem]">
            <p className="w-fit max-w-[90%] rounded-xl rounded-bl-sm bg-secondary px-4 py-2.5 text-[0.9375rem] leading-relaxed whitespace-pre-wrap">
              {m.content}
            </p>
          </div>
        ) : (
          <div
            key={m.id}
            data-testid="message-assistant"
            className="grid gap-x-10 gap-y-4 lg:grid-cols-[minmax(0,44rem)_15rem]"
          >
            <div className="min-w-0">
              {m.steps && m.steps.length > 0 && <ToolSteps steps={m.steps} />}
              {m.content ? (
                <div className="prose-chat">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                </div>
              ) : m.pending ? (
                <span className="inline-flex gap-1.5 py-3" role="status" aria-label="Thinking">
                  <span className="size-1.5 animate-bounce rounded-full bg-primary/70 [animation-delay:-0.3s] motion-reduce:animate-none" />
                  <span className="size-1.5 animate-bounce rounded-full bg-primary/70 [animation-delay:-0.15s] motion-reduce:animate-none" />
                  <span className="size-1.5 animate-bounce rounded-full bg-primary/70 motion-reduce:animate-none" />
                </span>
              ) : null}
              {m.error && (
                <p className="mt-3 text-sm text-destructive" role="alert">
                  {m.error}
                </p>
              )}
            </div>
            {m.sources && m.sources.length > 0 && <Sources sources={m.sources} />}
          </div>
        ),
      )}
      <div ref={bottomRef} />
    </div>
  )
}
