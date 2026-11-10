import { useCallback, useEffect, useRef, useState } from 'react'
import { CornerDownLeftIcon, MenuIcon } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'

import { ChatInput } from '@/components/chat/ChatInput'
import { MessageList, type UiMessage } from '@/components/chat/MessageList'
import { ThreadSidebar } from '@/components/chat/ThreadSidebar'
import { Button } from '@/components/ui/button'
import {
  createThread,
  deleteThread,
  listMessages,
  listThreads,
  streamChat,
  type Thread,
} from '@/lib/api'

const STARTERS = [
  'Summarise the document I uploaded most recently',
  'How many documents do I have, grouped by type?',
  'What topics do my documents cover?',
]

export default function Chat() {
  const [params, setParams] = useSearchParams()
  const activeId = params.get('t')
  const [threads, setThreads] = useState<Thread[]>([])
  const [messages, setMessages] = useState<UiMessage[]>([])
  const [streaming, setStreaming] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  // Thread created by the first send; its (empty) history must not overwrite the stream.
  const justCreatedRef = useRef<string | null>(null)

  const refreshThreads = useCallback(async () => {
    try {
      setThreads(await listThreads())
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : 'Failed to load threads')
    }
  }, [])

  useEffect(() => {
    void refreshThreads()
  }, [refreshThreads])

  // Load the selected thread's history.
  useEffect(() => {
    if (!activeId) {
      setMessages([])
      return
    }
    if (justCreatedRef.current === activeId) {
      justCreatedRef.current = null
      return
    }
    let active = true
    listMessages(activeId)
      .then((rows) => active && setMessages(rows))
      .catch((err: unknown) => {
        if (!active) return
        setMessages([])
        setLoadError(err instanceof Error ? err.message : 'Failed to load messages')
        setParams({}, { replace: true })
      })
    return () => {
      active = false
    }
  }, [activeId, setParams])

  const selectThread = (id: string) => {
    setLoadError(null)
    setDrawerOpen(false)
    setParams({ t: id })
  }

  const newChat = () => {
    setLoadError(null)
    setDrawerOpen(false)
    setParams({})
  }

  const removeThread = async (id: string) => {
    await deleteThread(id)
    if (id === activeId) setParams({})
    await refreshThreads()
  }

  const send = async (text: string) => {
    setLoadError(null)
    // Show the user's message and a thinking indicator immediately.
    const assistantId = `pending-${Date.now()}`
    setMessages((prev) => [
      ...prev,
      { id: `user-${Date.now()}`, role: 'user', content: text },
      { id: assistantId, role: 'assistant', content: '', pending: true },
    ])
    const patch = (fn: (m: UiMessage) => UiMessage) =>
      setMessages((prev) => prev.map((m) => (m.id === assistantId ? fn(m) : m)))

    const controller = new AbortController()
    abortRef.current = controller
    setStreaming(true)
    try {
      let threadId = activeId
      if (!threadId) {
        const thread = await createThread()
        threadId = thread.id
        justCreatedRef.current = thread.id
        setParams({ t: thread.id })
      }
      for await (const ev of streamChat(threadId, text, controller.signal)) {
        if (ev.event === 'delta') patch((m) => ({ ...m, content: m.content + ev.data.text }))
        else if (ev.event === 'tool_call') patch((m) => ({ ...m, steps: [...(m.steps ?? []), ev.data] }))
        else if (ev.event === 'tool_result')
          patch((m) => ({
            ...m,
            steps: (m.steps ?? []).map((s) => (s.id === ev.data.id ? { ...s, ...ev.data } : s)),
          }))
        else if (ev.event === 'subagent_delta')
          patch((m) => ({
            ...m,
            steps: (m.steps ?? []).map((s) =>
              s.id === ev.data.parent_id ? { ...s, text: (s.text ?? '') + ev.data.text } : s,
            ),
          }))
        else if (ev.event === 'sources')
          patch((m) => ({ ...m, sources: [...(m.sources ?? []), ...ev.data.sources] }))
        else if (ev.event === 'error') patch((m) => ({ ...m, error: ev.data.message }))
        else if (ev.event === 'done') patch((m) => ({ ...m, id: ev.data.message_id, pending: false }))
      }
    } catch (err) {
      if (!controller.signal.aborted) {
        patch((m) => ({ ...m, error: err instanceof Error ? err.message : 'Request failed' }))
      }
    } finally {
      // Anything still "running" when the stream ends (stop button, dropped connection) did not finish.
      patch((m) => ({
        ...m,
        pending: false,
        steps: m.steps?.map((s) => (s.ok == null ? { ...s, ok: false, summary: 'Stopped' } : s)),
      }))
      setStreaming(false)
      abortRef.current = null
      void refreshThreads()
    }
  }

  return (
    <div className="relative flex h-full">
      <ThreadSidebar
        threads={threads}
        activeId={activeId}
        onSelect={selectThread}
        onNew={newChat}
        onDelete={removeThread}
        disabled={streaming}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      />
      <section className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-11 shrink-0 items-center border-b px-3 md:hidden">
          <Button variant="ghost" size="sm" className="gap-2" onClick={() => setDrawerOpen(true)}>
            <MenuIcon className="size-4" /> Chats
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {messages.length === 0 ? (
            <div className="mx-auto flex h-full w-full max-w-[64rem] flex-col justify-center px-5 py-10">
              <div className="max-w-[44rem]">
                <h1 className="text-[clamp(2.75rem,7vw,4.75rem)] leading-[0.98] font-normal tracking-[-0.03em]">
                  How can I help?
                </h1>
                <p className="mt-6 max-w-[34rem] font-serif text-xl leading-relaxed text-muted-foreground">
                  Ask about your documents. Each answer comes with the passages it was drawn from, set
                  beside it like notes in a margin.
                </p>
                <ul className="mt-10 border-t" aria-label="Things to try">
                  {STARTERS.map((text) => (
                    <li key={text} className="border-b">
                      <button
                        type="button"
                        onClick={() => void send(text)}
                        disabled={streaming}
                        className="group flex w-full items-center justify-between gap-4 py-3.5 text-left text-[0.9375rem] text-foreground/85 transition-colors outline-none hover:text-primary focus-visible:text-primary"
                      >
                        {text}
                        <CornerDownLeftIcon
                          className="size-4 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"
                          aria-hidden="true"
                        />
                      </button>
                    </li>
                  ))}
                </ul>
                <p className="mt-6 text-sm text-muted-foreground">
                  Nothing uploaded yet?{' '}
                  <Link
                    to="/ingestion"
                    className="text-foreground underline decoration-primary decoration-2 underline-offset-4 outline-none hover:text-primary focus-visible:text-primary"
                  >
                    Add files
                  </Link>
                </p>
              </div>
            </div>
          ) : (
            <MessageList messages={messages} />
          )}
        </div>
        {loadError && (
          <p className="px-5 pb-2 text-center text-sm text-destructive" role="alert">
            {loadError}
          </p>
        )}
        <ChatInput onSend={send} onStop={() => abortRef.current?.abort()} streaming={streaming} />
      </section>
    </div>
  )
}
