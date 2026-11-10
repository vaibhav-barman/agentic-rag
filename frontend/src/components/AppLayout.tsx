import { useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'

import { Wordmark } from '@/components/Logo'
import { Button } from '@/components/ui/button'
import { Toaster } from '@/components/ui/sonner'
import { getMe, type Me } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { cn } from '@/lib/utils'

const navItems = [
  { to: '/', label: 'Chat', end: true },
  { to: '/ingestion', label: 'Documents', end: false },
]

export function AppLayout() {
  const { signOut, session } = useAuth()
  const navigate = useNavigate()
  const [me, setMe] = useState<Me | null>(null)
  const [meError, setMeError] = useState<string | null>(null)

  // Confirms the backend accepts our Supabase token (GET /me).
  const accessToken = session?.access_token
  useEffect(() => {
    if (!accessToken) return
    let active = true
    getMe()
      .then((data) => {
        if (!active) return
        setMe(data)
        setMeError(null)
      })
      .catch((err: unknown) => {
        if (active) setMeError(err instanceof Error ? err.message : 'Backend unreachable')
      })
    return () => {
      active = false
    }
  }, [accessToken])

  const handleSignOut = async () => {
    await signOut()
    navigate('/login', { replace: true })
  }

  return (
    <div className="flex h-svh flex-col bg-background text-foreground">
      <header className="flex h-14 shrink-0 items-center gap-4 border-b bg-card/60 px-4 sm:gap-8 sm:px-5">
        <Wordmark />
        <nav className="flex h-full items-stretch gap-1" aria-label="Main">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  'relative flex items-center px-2.5 text-sm transition-colors outline-none focus-visible:text-foreground focus-visible:underline',
                  'after:absolute after:inset-x-2.5 after:bottom-0 after:h-0.5 after:rounded-full after:transition-colors',
                  isActive
                    ? 'font-medium text-foreground after:bg-primary'
                    : 'text-muted-foreground after:bg-transparent hover:text-foreground',
                )
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="ml-auto flex min-w-0 items-center gap-3">
          <span
            className={cn(
              'hidden max-w-56 truncate text-sm sm:block',
              meError ? 'text-destructive' : 'text-muted-foreground',
            )}
            data-testid="me-email"
            title={meError ? `GET /me failed: ${meError}` : 'Verified by backend GET /me'}
          >
            {meError ? 'API error' : (me?.email ?? '…')}
          </span>
          <Button variant="ghost" size="sm" onClick={handleSignOut}>
            Log out
          </Button>
        </div>
      </header>
      <main className="min-h-0 flex-1">
        <Outlet />
      </main>
      <Toaster position="bottom-right" theme="light" />
    </div>
  )
}
