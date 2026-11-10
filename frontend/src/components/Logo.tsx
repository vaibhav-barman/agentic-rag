import { cn } from '@/lib/utils'

/**
 * Glossa mark: three lines of text, the middle one glossed. The green line is the
 * cited passage and the green tick beside it is the note in the margin.
 */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" fill="none" aria-hidden="true" className={cn('size-7 shrink-0', className)}>
      <rect width="32" height="32" rx="7" className="fill-foreground" />
      <rect x="7" y="8.2" width="18" height="2.2" rx="1.1" className="fill-background" />
      <rect x="7" y="14.9" width="13" height="2.2" rx="1.1" className="fill-primary" />
      <rect x="23" y="13.4" width="2" height="5.2" rx="1" className="fill-primary" />
      <rect x="7" y="21.6" width="16" height="2.2" rx="1.1" className="fill-background" />
    </svg>
  )
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-2.5', className)}>
      <LogoMark />
      <span className="font-heading text-[1.4rem] leading-none font-medium tracking-tight">Glossa</span>
    </span>
  )
}
