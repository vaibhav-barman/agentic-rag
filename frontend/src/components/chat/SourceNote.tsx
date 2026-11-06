import { FileTextIcon } from 'lucide-react'

import { cn } from '@/lib/utils'

const MAX_CHARS = 150

/** One cited file, shown as a marginal note: filename plus the matched passage, highlighted. */
export function SourceNote({
  filename,
  excerpt,
  className,
}: {
  filename: string
  excerpt: string
  className?: string
}) {
  const flat = excerpt.replace(/\s+/g, ' ').trim()
  // Cut at a word boundary so the excerpt never ends mid-word.
  const cut = flat.slice(0, MAX_CHARS)
  const short = flat.length > MAX_CHARS ? `${cut.slice(0, cut.lastIndexOf(' ')).trimEnd()}…` : flat
  return (
    <figure className={cn('border-l-2 border-primary/60 pl-3 text-[0.8125rem] leading-snug', className)} title={flat}>
      <figcaption className="flex items-center gap-1.5 font-medium text-foreground">
        <FileTextIcon className="size-3.5 shrink-0 text-primary" aria-hidden="true" />
        <span className="truncate">{filename}</span>
      </figcaption>
      {short && (
        <blockquote className="mt-1.5 font-serif text-[0.875rem] leading-relaxed text-muted-foreground">
          <mark className="rounded-[2px] bg-mark px-0.5 text-mark-foreground [box-decoration-break:clone]">
            {short}
          </mark>
        </blockquote>
      )}
    </figure>
  )
}
