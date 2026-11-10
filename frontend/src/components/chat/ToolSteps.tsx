import {
  BotIcon,
  CheckIcon,
  ChevronRightIcon,
  DatabaseIcon,
  FileSearchIcon,
  FileTextIcon,
  GlobeIcon,
  Loader2Icon,
  SearchIcon,
  WrenchIcon,
  XIcon,
  type LucideIcon,
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import type { Step } from '@/lib/api'
import { cn } from '@/lib/utils'

const str = (v: unknown) => (typeof v === 'string' ? v : v == null ? '' : String(v))

/** A plain-language label for each tool call: what the agent did, not the function name. */
function describe(step: Step): {
  icon: LucideIcon
  label: string
  detail?: string
  /** The label already says it all; only show the summary if the step failed. */
  quiet?: boolean
} {
  const a = step.arguments ?? {}
  switch (step.name) {
    case 'file_search':
      return { icon: FileSearchIcon, label: 'Searched your documents', detail: str(a.query) }
    case 'query_database':
      return { icon: DatabaseIcon, label: 'Queried your library data' }
    case 'web_search':
      return { icon: GlobeIcon, label: 'Searched the web', detail: str(a.query) }
    case 'analyze_document':
      // The summary ("Read handbook.md (48,210 characters)") says the rest once it is done.
      return {
        icon: BotIcon,
        label: step.ok == null ? 'A sub-agent is reading the whole document' : 'A sub-agent read the whole document',
        detail: undefined,
      }
    case 'search_in_document':
      return { icon: SearchIcon, label: 'Searched inside the document', detail: str(a.query) }
    case 'read_passages':
      return {
        icon: FileTextIcon,
        label: `Read passages ${str(a.start)}–${str(a.end)}`,
        quiet: true,
      }
    default:
      return { icon: WrenchIcon, label: step.name }
  }
}

function StatusIcon({ step }: { step: Step }) {
  if (step.ok == null)
    return (
      <Loader2Icon
        className="size-3.5 animate-spin text-primary motion-reduce:animate-none"
        role="status"
        aria-label="Running"
      />
    )
  return step.ok ? (
    <CheckIcon className="size-3.5 text-primary" aria-label="Done" />
  ) : (
    <XIcon className="size-3.5 text-destructive" aria-label="Failed" />
  )
}

function Rows({ columns, rows }: { columns: string[]; rows: Record<string, unknown>[] }) {
  if (!rows.length) return <p className="text-muted-foreground">No rows.</p>
  return (
    <div className="max-w-full overflow-x-auto">
      <table className="border-collapse text-xs" data-testid="sql-rows">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c} className="border bg-muted px-2 py-1 text-left font-medium">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c} className="max-w-64 truncate border px-2 py-1 align-top">
                  {typeof row[c] === 'object' && row[c] !== null ? JSON.stringify(row[c]) : str(row[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

type SearchResult = { filename: string; passage: number; score: number | null; vector_rank: number | null; keyword_rank: number | null }
type WebResult = { title: string; url: string }

/** The expandable part of a step: what went in and what came back. */
function Detail({ step, steps }: { step: Step; steps: Step[] }) {
  const data = step.data ?? {}
  const children = steps.filter((s) => s.parent_id === step.id)

  if (step.name === 'analyze_document') {
    return (
      <div
        className="mt-2 border-l-2 border-primary/70 py-1 pl-4"
        data-testid="subagent"
      >
        <p className="text-primary">Working in its own context, with only this document and this task:</p>
        <p className="mt-1 text-foreground/90">{str(step.arguments?.task)}</p>
        {children.length > 0 && (
          <ol className="mt-2 flex flex-col gap-1.5" aria-label="Sub-agent steps">
            {children.map((child) => (
              <StepRow key={child.id} step={child} steps={steps} />
            ))}
          </ol>
        )}
        {step.text && (
          <div
            className="prose-chat mt-3 text-[0.9375rem] leading-relaxed text-foreground/85"
            data-testid="subagent-text"
          >
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{step.text}</ReactMarkdown>
          </div>
        )}
      </div>
    )
  }

  if (step.name === 'query_database') {
    return (
      <div className="mt-2 flex flex-col gap-2">
        <pre className="overflow-x-auto rounded-md border bg-card p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap" data-testid="sql-query">
          {str(data.sql ?? step.arguments?.sql)}
        </pre>
        {step.ok && Array.isArray(data.rows) && (
          <Rows columns={(data.columns as string[]) ?? []} rows={data.rows as Record<string, unknown>[]} />
        )}
        {step.ok && Number(data.row_count) > (data.rows as unknown[] | undefined ?? []).length && (
          <p className="text-muted-foreground">Showing the first {(data.rows as unknown[]).length} of {str(data.row_count)} rows.</p>
        )}
      </div>
    )
  }

  if (step.name === 'file_search') {
    const filters = Object.entries((data.filters as Record<string, unknown>) ?? {})
    const results = (data.results as SearchResult[]) ?? []
    return (
      <div className="mt-2 flex flex-col gap-1.5 text-muted-foreground">
        {filters.length > 0 && (
          <p>
            Filters:{' '}
            {filters.map(([k, v]) => `${k.replace('_', ' ')} = ${Array.isArray(v) ? v.join(', ') : str(v)}`).join('; ')}
          </p>
        )}
        {results.length > 0 && (
          <ul className="flex flex-col gap-0.5">
            {results.map((r, i) => (
              <li key={i} className="flex flex-wrap gap-x-2">
                <span className="text-foreground">{r.filename}</span>
                <span>passage {r.passage}</span>
                {r.score != null && <span>relevance {r.score.toFixed(2)}</span>}
                {(r.keyword_rank != null || r.vector_rank != null) && (
                  <span>
                    ({[r.keyword_rank != null && `keyword #${r.keyword_rank}`, r.vector_rank != null && `semantic #${r.vector_rank}`].filter(Boolean).join(', ')})
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    )
  }

  if (step.name === 'web_search') {
    const results = (data.results as WebResult[]) ?? []
    return (
      <ul className="mt-2 flex flex-col gap-0.5">
        {results.map((r) => (
          <li key={r.url} className="truncate">
            <a href={r.url} target="_blank" rel="noreferrer" className="text-primary underline decoration-primary/40 underline-offset-2 hover:decoration-primary">
              {r.title}
            </a>
          </li>
        ))}
      </ul>
    )
  }
  return null
}

function StepRow({ step, steps }: { step: Step; steps: Step[] }) {
  const { icon: Icon, label, detail, quiet } = describe(step)
  const isSubagent = step.name === 'analyze_document'
  const hasDetail = isSubagent || ['query_database', 'file_search', 'web_search'].includes(step.name)
  const header = (
    <>
      <Icon className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
      <span className="min-w-0">
        <span className="text-foreground">{label}</span>
        {detail && <span className="text-muted-foreground"> “{detail}”</span>}
        {step.summary && !(quiet && step.ok) && (
          <span className={cn('block text-muted-foreground', step.ok === false && 'text-destructive')}>
            {step.summary}
          </span>
        )}
      </span>
      <span className="ml-auto flex shrink-0 items-center pl-2">
        <StatusIcon step={step} />
      </span>
    </>
  )
  return (
    <li data-testid="tool-step" data-tool={step.name} data-status={step.ok == null ? 'running' : step.ok ? 'ok' : 'failed'}>
      {hasDetail ? (
        // The sub-agent block opens by itself so its work is visible while it runs.
        <details className="group/step" open={isSubagent || undefined}>
          <summary className="flex cursor-pointer list-none items-start gap-2 rounded-md py-0.5 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/40 [&::-webkit-details-marker]:hidden [&>svg]:mt-0.5">
            <ChevronRightIcon className="size-3.5 shrink-0 text-muted-foreground transition-transform group-open/step:rotate-90" aria-hidden="true" />
            {header}
          </summary>
          <div className="pb-1 pl-[1.375rem]">
            <Detail step={step} steps={steps} />
          </div>
        </details>
      ) : (
        <div className="flex items-start gap-2 py-0.5 pl-[1.375rem] [&>svg]:mt-0.5">{header}</div>
      )}
    </li>
  )
}

/**
 * What the agent did before answering: each tool call in order, with a sub-agent's
 * own steps and text nested under the step that started it.
 */
export function ToolSteps({ steps }: { steps: Step[] }) {
  const top = steps.filter((s) => !s.parent_id)
  if (!top.length) return null
  return (
    <ol
      className="mb-6 flex max-w-[68ch] flex-col gap-2 text-[0.8125rem] leading-snug"
      data-testid="tool-steps"
      aria-label="Steps taken"
    >
      {top.map((step) => (
        <StepRow key={step.id} step={step} steps={steps} />
      ))}
    </ol>
  )
}
