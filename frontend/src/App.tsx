import { Navigate, Route, Routes } from 'react-router-dom'
import ProtectedRoute from './components/ProtectedRoute'
import Dashboard from './pages/Dashboard'
import Login from './pages/Login'
import NewTransaction from './pages/NewTransaction'
import Onboarding from './pages/Onboarding'
import Signup from './pages/Signup'
import TransactionDetail from './pages/TransactionDetail'
import { useAuthStore } from './store/auth'

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
      <Route
        path="/dashboard"
        element={
          <ProtectedRoute>
            {onboarded ? <Dashboard /> : <Navigate to="/onboarding" replace />}
          </ProtectedRoute>
        }
      />
      <Route
        path="/transactions/new"
        element={
          <ProtectedRoute>
            {onboarded ? <NewTransaction /> : <Navigate to="/onboarding" replace />}
          </ProtectedRoute>
        }
      />
      <Route
        path="/transactions/:transaction_id"
        element={
          <ProtectedRoute>
            {onboarded ? <TransactionDetail /> : <Navigate to="/onboarding" replace />}
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  )
}
