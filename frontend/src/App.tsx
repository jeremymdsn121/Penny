import { Navigate, Route, Routes } from 'react-router-dom'
import AppShell from './components/AppShell'
import ProtectedRoute from './components/ProtectedRoute'
import Agents from './pages/Agents'
import ComplianceSettings from './pages/ComplianceSettings'
import Dashboard from './pages/Dashboard'
import Knowledge from './pages/Knowledge'
import ListingDetail from './pages/ListingDetail'
import Listings from './pages/Listings'
import Login from './pages/Login'
import NewTransaction from './pages/NewTransaction'
import Onboarding from './pages/Onboarding'
import Reports from './pages/Reports'
import ReviewQueue from './pages/ReviewQueue'
import Signup from './pages/Signup'
import TransactionDetail from './pages/TransactionDetail'
import WhatsAppSettings from './pages/WhatsAppSettings'
import { useAuthStore } from './store/auth'

// Layout for authenticated + onboarded pages: gates access, then renders the
// shared sidebar shell with the matched page in its <Outlet/>.
function AppLayout() {
  const onboarded = useAuthStore((s) => !!s.brokerage?.onboarding_completed)
  return (
    <ProtectedRoute>
      {onboarded ? <AppShell /> : <Navigate to="/onboarding" replace />}
    </ProtectedRoute>
  )
}

export default function App() {
  const onboarded = useAuthStore((s) => !!s.brokerage?.onboarding_completed)

  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<Signup />} />
      <Route
        path="/onboarding"
        element={
          <ProtectedRoute>
            {onboarded ? <Navigate to="/dashboard" replace /> : <Onboarding />}
          </ProtectedRoute>
        }
      />

      {/* All onboarded app pages share the sidebar shell. */}
      <Route element={<AppLayout />}>
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/transactions/new" element={<NewTransaction />} />
        <Route path="/transactions/:transaction_id" element={<TransactionDetail />} />
        <Route path="/settings/whatsapp" element={<WhatsAppSettings />} />
        <Route path="/settings/compliance" element={<ComplianceSettings />} />
        <Route path="/knowledge" element={<Knowledge />} />
        <Route path="/listings" element={<Listings />} />
        <Route path="/listings/:listing_id" element={<ListingDetail />} />
        <Route path="/agents" element={<Agents />} />
        <Route path="/review" element={<ReviewQueue />} />
        <Route path="/reports" element={<Reports />} />
      </Route>

      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  )
}
