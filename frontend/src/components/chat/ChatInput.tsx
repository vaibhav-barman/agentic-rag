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
    <div className="mx-auto w-full max-w-3xl px-4 pb-4">
      <div className="relative rounded-2xl border bg-background shadow-sm focus-within:ring-2 focus-within:ring-ring/30">
        <Textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Message… (Shift+Enter for a new line)"
          aria-label="Message"
          rows={1}
          className="max-h-48 min-h-12 resize-none border-0 bg-transparent py-3 pr-14 shadow-none focus-visible:ring-0"
        />
        {streaming ? (
          <Button size="icon" variant="outline" className="absolute right-2 bottom-2 size-8 rounded-full" onClick={onStop} aria-label="Stop">
            <SquareIcon className="size-3.5" />
          </Button>
        ) : (
          <Button size="icon" className="absolute right-2 bottom-2 size-8 rounded-full" onClick={send} disabled={!value.trim()} aria-label="Send">
            <ArrowUpIcon className="size-4" />
          </Button>
        )}
      </div>
    </div>
  )
}
