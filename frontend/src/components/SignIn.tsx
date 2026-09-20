import { useState } from 'react'
import { api, setToken } from '@/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

/**
 * The way in.
 *
 * Google first, because signing in should say who you are rather than prove
 * you know a shared secret — and because it is separate from connecting a
 * mailbox, which asks for far more and belongs to the deployment rather than
 * to whoever is looking at the screen.
 *
 * The service token stays underneath as a fallback. Greenlit keeps a password
 * form beside its Google button for the same reason: when the OAuth path
 * fails mid-demo, being locked out of your own app is worse than an extra
 * input nobody usually touches.
 */
export default function SignIn({ onDone }: { onDone: () => void }) {
  const [going, setGoing] = useState(false)
  const [token, setValue] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [showToken, setShowToken] = useState(false)

  const google = async () => {
    setGoing(true)
    setError(null)
    try {
      const { authorization_url } = await api.signInStart()
      window.location.href = authorization_url
    } catch (e) {
      setError((e as Error).message)
      setGoing(false)
    }
  }

  return (
    <div className="grid h-full place-items-center p-6">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>VS-Mail</CardTitle>
          <p className="text-sm text-muted-foreground">
            Reads an inbox of shipping mail, checks each draft bill of lading
            against its shipping instruction, and drafts the reply.
          </p>
        </CardHeader>
        <CardContent className="space-y-3">
          <Button className="w-full" size="lg" loading={going} onClick={google}>
            {going ? 'Waiting for Google…' : 'Sign in with Google'}
          </Button>

          {error && <p className="text-sm text-defect">{error}</p>}

          {!showToken ? (
            <button
              className="w-full text-center text-xs text-muted-foreground underline-offset-2 hover:underline"
              onClick={() => setShowToken(true)}
            >
              or use a service token
            </button>
          ) : (
            <div className="space-y-2 border-t pt-3">
              <p className="text-xs text-muted-foreground">
                The shared secret the server was started with, for when the
                Google path is unavailable.
              </p>
              <div className="flex gap-2">
                <input
                  type="password"
                  placeholder="Service token"
                  className="h-9 flex-1 rounded-md border bg-background px-3 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
                  value={token}
                  onChange={(e) => setValue(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && token.trim()) {
                      setToken(token)
                      onDone()
                    }
                  }}
                />
                <Button
                  variant="outline"
                  disabled={!token.trim()}
                  onClick={() => {
                    setToken(token)
                    onDone()
                  }}
                >
                  Use it
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
