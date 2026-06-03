import { zodResolver } from '@hookform/resolvers/zod'
import type { ReactNode } from 'react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useNavigate } from 'react-router-dom'
import { z } from 'zod'
import PennyBubble from '../components/PennyBubble'
import { useAuthStore } from '../store/auth'

const schema = z.object({
  email: z.string().email('Enter a valid email'),
  password: z.string().min(1, 'Password is required'),
})
type FormValues = z.infer<typeof schema>

export default function Login() {
  const navigate = useNavigate()
  const login = useAuthStore((s) => s.login)
  const [serverError, setServerError] = useState<string | null>(null)
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema) })

  const onSubmit = async (values: FormValues) => {
    setServerError(null)
    try {
      await login(values.email, values.password)
      navigate('/dashboard')
    } catch (err: any) {
      setServerError(err?.response?.data?.detail ?? 'Something went wrong logging in.')
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-2 px-4">
      <div className="w-full max-w-md space-y-6">
        <PennyBubble>Welcome back — log in and I&rsquo;ll pick up where we left off.</PennyBubble>

        <form
          onSubmit={handleSubmit(onSubmit)}
          className="space-y-4 rounded-2xl border border-hairline bg-surface p-6 shadow-sm"
        >
          <h1 className="text-xl font-semibold text-ink">Log in</h1>

          <Field label="Email" error={errors.email?.message}>
            <input
              type="email"
              autoComplete="email"
              className="input"
              {...register('email')}
            />
          </Field>

          <Field label="Password" error={errors.password?.message}>
            <input
              type="password"
              autoComplete="current-password"
              className="input"
              {...register('password')}
            />
          </Field>

          {serverError && <p className="text-sm text-red-600">{serverError}</p>}

          <button type="submit" disabled={isSubmitting} className="btn-primary w-full">
            {isSubmitting ? 'Logging in…' : 'Log in'}
          </button>

          <p className="text-center text-sm text-ink-muted">
            New brokerage?{' '}
            <Link to="/signup" className="font-medium text-penny hover:underline">
              Create an account
            </Link>
          </p>
        </form>
      </div>
    </div>
  )
}

function Field({
  label,
  error,
  children,
}: {
  label: string
  error?: string
  children: ReactNode
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-ink">{label}</span>
      {children}
      {error && <span className="mt-1 block text-xs text-red-600">{error}</span>}
    </label>
  )
}
