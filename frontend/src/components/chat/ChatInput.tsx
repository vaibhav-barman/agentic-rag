import { ArrowUpIcon, SquareIcon } from 'lucide-react'
import { useState, type KeyboardEvent } from 'react'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'

type Props = {
  onSend: (text: string) => void
  onStop: () => void
  streaming: boolean
}

export function ChatInput({ onSend, onStop, streaming }: Props) {
  const [value, setValue] = useState('')

  const send = () => {
    const text = value.trim()
    if (!text || streaming) return
    onSend(text)
    setValue('')
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div className="mx-auto w-full max-w-[64rem] px-5 pb-4">
      <div className="lg:max-w-[44rem]">
        <div className="relative rounded-2xl border border-input bg-card transition-[border-color,box-shadow] focus-within:border-primary focus-within:ring-3 focus-within:ring-ring/15">
          <Textarea
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Ask about your documents, or anything else"
            aria-label="Message"
            rows={1}
            className="max-h-48 min-h-[3.5rem] resize-none border-0 bg-transparent px-4 py-4 pr-14 text-base shadow-none placeholder:text-muted-foreground/80 focus-visible:ring-0 dark:bg-transparent"
          />
          {streaming ? (
            <Button
              size="icon"
              variant="outline"
              className="absolute right-2.5 bottom-2.5 size-9 rounded-full"
              onClick={onStop}
              aria-label="Stop"
            >
              <SquareIcon className="size-3.5 fill-current" />
            </Button>
          ) : (
            <Button
              size="icon"
              className="absolute right-2.5 bottom-2.5 size-9 rounded-full"
              onClick={send}
              disabled={!value.trim()}
              aria-label="Send"
            >
              <ArrowUpIcon className="size-4" />
            </Button>
          )}
        </div>
        <p className="mt-2 hidden px-1 text-xs text-muted-foreground sm:block">
          Enter sends. Shift+Enter starts a new line.
        </p>
      </div>
    </div>
  )
}
