import { zodResolver } from '@hookform/resolvers/zod'
import type { ReactNode } from 'react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useNavigate } from 'react-router-dom'
import { z } from 'zod'
import PennyBubble from '../components/PennyBubble'
import { useAuthStore } from '../store/auth'

const schema = z.object({
  brokerage_name: z.string().min(1, 'Brokerage name is required'),
  email: z.string().email('Enter a valid email'),
  password: z.string().min(8, 'At least 8 characters'),
})
type FormValues = z.infer<typeof schema>

export default function Signup() {
  const navigate = useNavigate()
  const signup = useAuthStore((s) => s.signup)
  const [serverError, setServerError] = useState<string | null>(null)
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema) })

  const onSubmit = async (values: FormValues) => {
    setServerError(null)
    try {
      await signup(values)
      navigate('/onboarding')
    } catch (err: any) {
      setServerError(err?.response?.data?.detail ?? 'Something went wrong creating your account.')
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-2 px-4 py-10">
      <div className="w-full max-w-md space-y-6">
        <PennyBubble>
          Hi, I&rsquo;m Penny. Create your account and I&rsquo;ll walk you through setup next.
        </PennyBubble>

        <form
          onSubmit={handleSubmit(onSubmit)}
          className="space-y-4 rounded-2xl border border-hairline bg-surface p-6 shadow-sm"
        >
          <h1 className="text-xl font-semibold text-ink">Create your account</h1>

          <Field label="Brokerage name" error={errors.brokerage_name?.message}>
            <input className="input" placeholder="Palmetto Realty Group" {...register('brokerage_name')} />
          </Field>

          <Field label="Email" error={errors.email?.message}>
            <input type="email" autoComplete="email" className="input" {...register('email')} />
          </Field>

          <Field label="Password" error={errors.password?.message}>
            <input
              type="password"
              autoComplete="new-password"
              className="input"
              {...register('password')}
            />
          </Field>

          {serverError && <p className="text-sm text-red-600">{serverError}</p>}

          <button type="submit" disabled={isSubmitting} className="btn-primary w-full">
            {isSubmitting ? 'Creating account…' : 'Create account'}
          </button>

          <p className="text-center text-sm text-ink-muted">
            Already set up?{' '}
            <Link to="/login" className="font-medium text-penny hover:underline">
              Log in
            </Link>
          </p>
        </form>
      </div>
    </div>
  )
}

function Field({ label, error, children }: { label: string; error?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-ink">{label}</span>
      {children}
      {error && <span className="mt-1 block text-xs text-red-600">{error}</span>}
    </label>
  )
}
