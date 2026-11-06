import { useCallback, useEffect, useRef, useState } from 'react'
import { MenuIcon } from 'lucide-react'
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
      patch((m) => ({ ...m, pending: false }))
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
            <div className="flex h-full items-center justify-center p-6">
              <div className="max-w-md">
                <h1 className="text-4xl leading-tight font-medium">How can I help?</h1>
                <p className="mt-3 text-base leading-relaxed text-muted-foreground">
                  Ask a question and I'll answer it. Add files and I'll answer from them, with the passage I
                  used shown beside each answer.
                </p>
                <Button asChild variant="outline" className="mt-5 h-9 bg-card px-3.5">
                  <Link to="/ingestion">Upload files</Link>
                </Button>
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
