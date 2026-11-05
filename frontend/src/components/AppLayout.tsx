import { useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import { getMe, type Me } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { cn } from '@/lib/utils'

const navItems = [
  { to: '/', label: 'Chat', end: true },
  { to: '/ingestion', label: 'Ingestion', end: false },
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
      <header className="flex h-14 shrink-0 items-center gap-6 border-b px-4">
        <span className="font-heading text-sm font-semibold">Agentic RAG</span>
        <nav className="flex items-center gap-1">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  'rounded-md px-3 py-1.5 text-sm transition-colors',
                  isActive
                    ? 'bg-secondary text-secondary-foreground font-medium'
                    : 'text-muted-foreground hover:text-foreground',
                )
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-3">
          <span
            className={cn('text-xs', meError ? 'text-destructive' : 'text-muted-foreground')}
            data-testid="me-email"
            title={meError ? `GET /me failed: ${meError}` : 'Verified by backend GET /me'}
          >
            {meError ? 'API error' : (me?.email ?? '…')}
          </span>
          <Button variant="outline" size="sm" onClick={handleSignOut}>
            Log out
          </Button>
        </div>
      </header>
      <main className="min-h-0 flex-1">
        <Outlet />
      </main>
    </div>
  )
}
