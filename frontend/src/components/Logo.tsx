import { cn } from '@/lib/utils'

/** Glossa mark: a line of text with one passage highlighted, like a marginal note. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" fill="none" aria-hidden="true" className={cn('size-7 shrink-0', className)}>
      <rect width="32" height="32" rx="8" className="fill-primary" />
      <rect x="7" y="8" width="18" height="2.4" rx="1.2" className="fill-primary-foreground" />
      <rect x="5.5" y="13.6" width="15.5" height="5.2" rx="1.4" className="fill-mark" />
      <rect x="7.5" y="15" width="12" height="2.4" rx="1.2" className="fill-mark-foreground" />
      <rect x="7" y="21.6" width="11" height="2.4" rx="1.2" className="fill-primary-foreground" />
    </svg>
  )
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-2.5', className)}>
      <LogoMark />
      <span className="font-heading text-[1.35rem] leading-none font-semibold tracking-tight">Glossa</span>
    </span>
  )
}
