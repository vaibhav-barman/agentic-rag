import { MessageSquareIcon, PlusIcon, Trash2Icon } from 'lucide-react'

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
}

export function ThreadSidebar({ threads, activeId, onSelect, onNew, onDelete, disabled }: Props) {
  return (
    <aside className="flex w-64 shrink-0 flex-col border-r bg-muted/30">
      <div className="p-3">
        <Button className="w-full justify-start gap-2" variant="outline" onClick={onNew} disabled={disabled}>
          <PlusIcon className="size-4" /> New chat
        </Button>
      </div>
      <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-3" aria-label="Threads">
        {threads.length === 0 && (
          <p className="px-2 py-4 text-xs text-muted-foreground">No conversations yet.</p>
        )}
        <ul className="flex flex-col gap-0.5">
          {threads.map((t) => (
            <li key={t.id} className="group relative">
              <button
                type="button"
                onClick={() => onSelect(t.id)}
                disabled={disabled}
                data-testid="thread-item"
                className={cn(
                  'flex w-full items-center gap-2 rounded-md px-2 py-2 pr-8 text-left text-sm transition-colors',
                  t.id === activeId
                    ? 'bg-secondary font-medium text-secondary-foreground'
                    : 'text-muted-foreground hover:bg-secondary/60 hover:text-foreground',
                )}
              >
                <MessageSquareIcon className="size-3.5 shrink-0" />
                <span className="truncate">{t.title || 'New chat'}</span>
              </button>
              <button
                type="button"
                aria-label={`Delete ${t.title || 'chat'}`}
                onClick={() => onDelete(t.id)}
                disabled={disabled}
                className="absolute top-1/2 right-1 -translate-y-1/2 rounded p-1 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 hover:text-destructive focus-visible:opacity-100"
              >
                <Trash2Icon className="size-3.5" />
              </button>
            </li>
          ))}
        </ul>
      </nav>
    </aside>
  )
}
