import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { ChatInput } from '@/components/chat/ChatInput'
import { MessageList, type UiMessage } from '@/components/chat/MessageList'
import { ThreadSidebar } from '@/components/chat/ThreadSidebar'
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
    setParams({ t: id })
  }

  const newChat = () => {
    setLoadError(null)
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
    <div className="flex h-full">
      <ThreadSidebar
        threads={threads}
        activeId={activeId}
        onSelect={selectThread}
        onNew={newChat}
        onDelete={removeThread}
        disabled={streaming}
      />
      <section className="flex min-w-0 flex-1 flex-col">
        <div className="min-h-0 flex-1 overflow-y-auto">
          {messages.length === 0 ? (
            <div className="flex h-full items-center justify-center p-6 text-center">
              <div>
                <h1 className="font-heading text-xl font-semibold">How can I help?</h1>
                <p className="mt-1 text-sm text-muted-foreground">
                  Ask anything. Upload files on the Ingestion page to chat with your documents.
                </p>
              </div>
            </div>
          ) : (
            <MessageList messages={messages} />
          )}
        </div>
        {loadError && (
          <p className="px-4 pb-2 text-center text-xs text-destructive" role="alert">
            {loadError}
          </p>
        )}
        <ChatInput onSend={send} onStop={() => abortRef.current?.abort()} streaming={streaming} />
      </section>
    </div>
  )
}
