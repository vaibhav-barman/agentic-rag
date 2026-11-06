import { PlusIcon, Trash2Icon, XIcon } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import type { Thread } from '@/lib/api'
import { cn } from '@/lib/utils'

type Props = {
  threads: Thread[]
  activeId: string | null
  onSelect: (id: string) => void
  onNew: () => void
  onDelete: (id: string) => void
  disabled?: boolean
  /** Mobile drawer state; on md+ the sidebar is always visible. */
  open: boolean
  onClose: () => void
}

const GROUPS = ['Today', 'Yesterday', 'Previous 7 days', 'Earlier'] as const
type Group = (typeof GROUPS)[number]

function groupOf(t: Thread, now: Date): Group {
  const when = new Date(t.updated_at ?? t.created_at)
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const day = 86_400_000
  const ts = when.getTime()
  if (ts >= startOfToday) return 'Today'
  if (ts >= startOfToday - day) return 'Yesterday'
  if (ts >= startOfToday - 7 * day) return 'Previous 7 days'
  return 'Earlier'
}

export function ThreadSidebar({ threads, activeId, onSelect, onNew, onDelete, disabled, open, onClose }: Props) {
  const [now] = useState(() => new Date())
  const grouped = GROUPS.map((g) => ({ label: g, items: threads.filter((t) => groupOf(t, now) === g) })).filter(
    (g) => g.items.length > 0,
  )

  return (
    <>
      {open && (
        <button
          type="button"
          aria-label="Close chat list"
          onClick={onClose}
          className="absolute inset-0 z-20 bg-foreground/30 md:hidden"
        />
      )}
      <aside
        className={cn(
          'absolute inset-y-0 left-0 z-30 flex w-72 shrink-0 flex-col border-r bg-sidebar transition-transform duration-200 motion-reduce:transition-none',
          'md:static md:z-auto md:w-64 md:translate-x-0',
          open ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        <div className="flex items-center gap-2 p-3">
          <Button className="flex-1 justify-start gap-2 bg-card" variant="outline" onClick={onNew} disabled={disabled}>
            <PlusIcon className="size-4" /> New chat
          </Button>
          <Button variant="ghost" size="icon" className="md:hidden" onClick={onClose} aria-label="Close chat list">
            <XIcon className="size-4" />
          </Button>
        </div>
        <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-3" aria-label="Chats">
          {threads.length === 0 && (
            <p className="px-2 py-4 text-sm text-muted-foreground">No conversations yet.</p>
          )}
          {grouped.map((g) => (
            <section key={g.label} className="mt-3 first:mt-0">
              <h2 className="px-2 pb-1 font-sans text-xs font-medium text-muted-foreground">{g.label}</h2>
              <ul className="flex flex-col gap-0.5">
                {g.items.map((t) => (
                  <li key={t.id} className="group relative">
                    <button
                      type="button"
                      onClick={() => onSelect(t.id)}
                      disabled={disabled}
                      data-testid="thread-item"
                      aria-current={t.id === activeId ? 'page' : undefined}
                      className={cn(
                        'flex w-full items-center rounded-lg border px-2.5 py-2 pr-9 text-left text-sm transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:opacity-60',
                        t.id === activeId
                          ? 'border-border bg-card font-medium text-foreground'
                          : 'border-transparent text-muted-foreground hover:bg-sidebar-accent hover:text-foreground',
                      )}
                    >
                      <span className="truncate">{t.title || 'New chat'}</span>
                    </button>
                    <button
                      type="button"
                      aria-label={`Delete ${t.title || 'chat'}`}
                      onClick={() => onDelete(t.id)}
                      disabled={disabled}
                      className="absolute top-1/2 right-1.5 -translate-y-1/2 rounded-md p-1.5 text-muted-foreground opacity-0 transition-opacity outline-none group-hover:opacity-100 hover:text-destructive focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ring/50 max-md:opacity-100"
                    >
                      <Trash2Icon className="size-3.5" />
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </nav>
      </aside>
    </>
  )
}
