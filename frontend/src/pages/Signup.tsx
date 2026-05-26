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
  assistant_name: z.string().min(1).default('Penny'),
  email: z.string().email('Enter a valid email'),
  password: z.string().min(8, 'At least 8 characters'),
  state: z.string().optional(),
  phone: z.string().optional(),
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
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { assistant_name: 'Penny' },
  })

  const onSubmit = async (values: FormValues) => {
    setServerError(null)
    try {
      await signup(values)
      navigate('/dashboard')
    } catch (err: any) {
      setServerError(err?.response?.data?.detail ?? 'Something went wrong creating your account.')
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4 py-10">
      <div className="w-full max-w-md space-y-6">
        <PennyBubble>
          Hi, I&rsquo;m Penny. Set up your brokerage and I&rsquo;ll start handling the paperwork.
        </PennyBubble>

        <form
          onSubmit={handleSubmit(onSubmit)}
          className="space-y-4 rounded-2xl border border-gray-100 bg-white p-6 shadow-sm"
        >
          <h1 className="text-xl font-semibold text-gray-900">Create your brokerage account</h1>

          <Field label="Brokerage name" error={errors.brokerage_name?.message}>
            <input className="input" placeholder="Palmetto Realty Group" {...register('brokerage_name')} />
          </Field>

          <Field label="Assistant name" error={errors.assistant_name?.message}>
            <input className="input" {...register('assistant_name')} />
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

          <div className="grid grid-cols-2 gap-3">
            <Field label="State" error={errors.state?.message}>
              <input className="input" placeholder="TX" {...register('state')} />
            </Field>
            <Field label="Phone" error={errors.phone?.message}>
              <input className="input" {...register('phone')} />
            </Field>
          </div>

          {serverError && <p className="text-sm text-red-600">{serverError}</p>}

          <button type="submit" disabled={isSubmitting} className="btn-primary w-full">
            {isSubmitting ? 'Creating account…' : 'Create account'}
          </button>

          <p className="text-center text-sm text-gray-500">
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
      <span className="mb-1 block text-sm font-medium text-gray-700">{label}</span>
      {children}
      {error && <span className="mt-1 block text-xs text-red-600">{error}</span>}
    </label>
  )
}
