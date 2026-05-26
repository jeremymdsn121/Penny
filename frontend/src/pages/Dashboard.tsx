import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import PennyBubble from '../components/PennyBubble'
import { transactionsApi, type Transaction } from '../lib/api'
import { useAuthStore } from '../store/auth'

const STAGE_LABELS: Record<string, string> = {
  under_contract: 'Under Contract',
  pending: 'Pending',
  closed: 'Closed',
  cancelled: 'Cancelled',
}

const STAGE_COLORS: Record<string, string> = {
  under_contract: 'bg-blue-100 text-blue-700',
  pending: 'bg-yellow-100 text-yellow-700',
  closed: 'bg-green-100 text-green-700',
  cancelled: 'bg-gray-100 text-gray-600',
}

function StageBadge({ stage }: { stage?: string | null }) {
  const s = stage ?? 'under_contract'
  return (
    <span
      className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${
        STAGE_COLORS[s] ?? 'bg-gray-100 text-gray-600'
      }`}
    >
      {STAGE_LABELS[s] ?? s}
    </span>
  )
}

export default function Dashboard() {
  const navigate = useNavigate()
  const brokerage = useAuthStore((s) => s.brokerage)
  const logout = useAuthStore((s) => s.logout)
  const assistant = brokerage?.assistant_name || 'Penny'

  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [txLoading, setTxLoading] = useState(true)

  useEffect(() => {
    transactionsApi
      .list()
      .then(setTransactions)
      .catch(() => {/* silently degrade */})
      .finally(() => setTxLoading(false))
  }, [])

  const onLogout = async () => {
    await logout()
    navigate('/login')
  }

  const pennyMessage =
    transactions.length === 0
      ? "Drop me a contract and I'll get started right away."
      : `You have ${transactions.length} active transaction${transactions.length !== 1 ? 's' : ''}. Click one to view details, or start a new one.`

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
        <PennyBubble>{pennyMessage}</PennyBubble>

        {/* Brokerage info */}
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

        {/* Transactions */}
        <section className="rounded-2xl border border-gray-100 bg-white shadow-sm">
          <div className="flex items-center justify-between border-b border-gray-100 px-6 py-4">
            <h2 className="text-lg font-semibold text-gray-900">Transactions</h2>
            <button
              onClick={() => navigate('/transactions/new')}
              className="btn-primary"
            >
              + New transaction
            </button>
          </div>

          {txLoading ? (
            <div className="flex justify-center py-10">
              <div className="h-6 w-6 animate-spin rounded-full border-4 border-penny border-t-transparent" />
            </div>
          ) : transactions.length === 0 ? (
            <div className="px-6 py-10 text-center">
              <p className="text-sm text-gray-400">No transactions yet.</p>
              <button
                onClick={() => navigate('/transactions/new')}
                className="mt-4 text-sm font-medium text-penny hover:underline"
              >
                Upload your first contract →
              </button>
            </div>
          ) : (
            <ul className="divide-y divide-gray-50">
              {transactions.map((tx) => (
                <li key={tx.id}>
                  <button
                    onClick={() => navigate(`/transactions/${tx.id}`)}
                    className="flex w-full items-start justify-between gap-4 px-6 py-4 text-left transition-colors hover:bg-gray-50"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-gray-900">
                        {tx.address
                          ? `${tx.address}${tx.city ? `, ${tx.city}` : ''}`
                          : 'Address not set'}
                      </p>
                      <p className="mt-0.5 truncate text-xs text-gray-400">
                        {tx.buyer_name ? `Buyer: ${tx.buyer_name}` : ''}
                        {tx.closing_date ? `  ·  Closes ${tx.closing_date}` : ''}
                      </p>
                    </div>
                    <StageBadge stage={tx.stage} />
                  </button>
                </li>
              ))}
            </ul>
          )}
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
