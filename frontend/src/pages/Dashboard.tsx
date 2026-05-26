import { useNavigate } from 'react-router-dom'
import PennyBubble from '../components/PennyBubble'
import { useAuthStore } from '../store/auth'

export default function Dashboard() {
  const navigate = useNavigate()
  const brokerage = useAuthStore((s) => s.brokerage)
  const logout = useAuthStore((s) => s.logout)
  const assistant = brokerage?.assistant_name || 'Penny'

  const onLogout = async () => {
    await logout()
    navigate('/login')
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="flex items-center justify-between border-b border-gray-200 bg-white px-6 py-4">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-penny font-semibold text-white">
            {assistant.charAt(0)}
          </div>
          <span className="font-semibold text-gray-900">{brokerage?.name ?? 'Penny'}</span>
        </div>
        <button onClick={onLogout} className="text-sm font-medium text-gray-500 hover:text-gray-900">
          Log out
        </button>
      </header>

      <main className="mx-auto max-w-2xl space-y-6 px-6 py-10">
        <PennyBubble>
          You&rsquo;re all set. Drop me a contract and I&rsquo;ll get started — that part&rsquo;s coming next.
        </PennyBubble>

        <section className="rounded-2xl border border-gray-100 bg-white p-6 shadow-sm">
          <h2 className="mb-4 text-lg font-semibold text-gray-900">Brokerage</h2>
          <dl className="grid grid-cols-2 gap-y-3 text-sm">
            <Row label="Name" value={brokerage?.name} />
            <Row label="Assistant" value={brokerage?.assistant_name} />
            <Row label="State" value={brokerage?.state} />
            <Row label="Email" value={brokerage?.email} />
            <Row label="Phone" value={brokerage?.phone} />
            <Row label="Plan" value={brokerage?.subscription_tier} />
          </dl>
        </section>
      </main>
    </div>
  )
}

function Row({ label, value }: { label: string; value?: string | null }) {
  return (
    <>
      <dt className="text-gray-500">{label}</dt>
      <dd className="text-gray-900">{value || '—'}</dd>
    </>
  )
}
