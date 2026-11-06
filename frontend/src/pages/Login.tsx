import { useState, type FormEvent } from 'react'
import { Navigate, useLocation } from 'react-router-dom'

import { SourceNote } from '@/components/chat/SourceNote'
import { Wordmark } from '@/components/Logo'
import { FullPageSpinner } from '@/components/ProtectedRoute'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAuth } from '@/lib/auth'
import { supabase } from '@/lib/supabase'

type Mode = 'login' | 'signup'

export default function Login() {
  const { session, loading } = useAuth()
  const location = useLocation()
  const [mode, setMode] = useState<Mode>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  if (loading) return <FullPageSpinner />
  if (session) {
    const from = (location.state as { from?: string } | null)?.from ?? '/'
    return <Navigate to={from} replace />
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setNotice(null)
    setSubmitting(true)
    try {
      if (mode === 'login') {
        const { error } = await supabase.auth.signInWithPassword({ email, password })
        if (error) setError(error.message)
      } else {
        const { data, error } = await supabase.auth.signUp({ email, password })
        if (error) setError(error.message)
        else if (!data.session) {
          setNotice('Account created. Check your email to confirm it, then log in.')
          setMode('login')
        }
      }
    } finally {
      setSubmitting(false)
    }
  }

  const switchMode = () => {
    setMode(mode === 'login' ? 'signup' : 'login')
    setError(null)
    setNotice(null)
  }

  return (
    <div className="grid min-h-svh lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
      <aside className="hidden flex-col justify-between border-r bg-sidebar p-12 lg:flex">
        <Wordmark />
        <div className="max-w-xl">
          <h2 className="text-5xl leading-[1.1] font-medium">Answers that show their source.</h2>
          <p className="mt-5 max-w-md text-base leading-relaxed text-muted-foreground">
            Add your documents, ask a question, and read the answer next to the passage it came from.
          </p>
          <div className="mt-12 grid max-w-xl grid-cols-[minmax(0,1fr)_11.5rem] gap-x-8" aria-hidden="true">
            <p className="font-serif text-[1.0625rem] leading-[1.7]">
              Returns are accepted for 30 days after delivery.{' '}
              <mark className="rounded-[2px] bg-mark px-0.5 text-mark-foreground [box-decoration-break:clone]">
                Refunds are issued within 14 days of the return arriving
              </mark>
              , to the original payment method.
            </p>
            <SourceNote
              filename="returns-policy.pdf"
              excerpt="Refunds are issued within 14 days of the return arriving at our warehouse."
              className="self-start pt-0.5"
            />
          </div>
        </div>
        <p className="text-sm text-muted-foreground">Your documents stay private to your account.</p>
      </aside>

      <main className="flex items-center justify-center px-5 py-10">
        <div className="w-full max-w-sm">
          <Wordmark className="mb-10 lg:hidden" />
          <form onSubmit={handleSubmit} className="flex flex-col gap-5">
            <div>
              <h1 className="text-3xl font-medium">{mode === 'login' ? 'Log in' : 'Create an account'}</h1>
              <p className="mt-2 text-sm text-muted-foreground">
                {mode === 'login'
                  ? 'Use your email and password to continue.'
                  : 'Sign up with an email and password.'}
              </p>
            </div>
            {error && (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            {notice && (
              <Alert>
                <AlertDescription>{notice}</AlertDescription>
              </Alert>
            )}
            <div className="flex flex-col gap-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                required
                className="h-10 bg-card px-3"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                required
                minLength={6}
                className="h-10 bg-card px-3"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            <Button type="submit" className="h-10 w-full text-sm" disabled={submitting}>
              {submitting ? 'Please wait…' : mode === 'login' ? 'Log in' : 'Sign up'}
            </Button>
            <button
              type="button"
              onClick={switchMode}
              className="rounded-md text-sm text-muted-foreground underline-offset-4 outline-none hover:text-foreground hover:underline focus-visible:ring-2 focus-visible:ring-ring/50"
            >
              {mode === 'login' ? "Don't have an account? Sign up" : 'Already have an account? Log in'}
            </button>
          </form>
        </div>
      </main>
    </div>
  )
}
