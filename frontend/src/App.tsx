import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  Link2,
  TrendingUp,
  ClipboardList,
  Activity,
  Settings as SettingsIcon,
} from 'lucide-react'
import Overview from './pages/Overview'
import OptionsChain from './pages/OptionsChain'
import Positions from './pages/Positions'
import Orders from './pages/Orders'
import StrategyMonitor from './pages/StrategyMonitor'
import Settings from './pages/Settings'

const navItems = [
  { to: '/',         icon: LayoutDashboard, label: 'Overview'  },
  { to: '/chain',    icon: Link2,           label: 'Options'   },
  { to: '/positions',icon: TrendingUp,      label: 'Positions' },
  { to: '/orders',   icon: ClipboardList,   label: 'Orders'    },
  { to: '/strategy', icon: Activity,        label: 'Strategy'  },
  { to: '/settings', icon: SettingsIcon,    label: 'Settings'  },
]

export default function App() {
  return (
    <BrowserRouter>
      <div className="flex h-screen overflow-hidden" style={{ background: '#050608' }}>
        {/* Sidebar */}
        <aside
          className="flex flex-col flex-shrink-0"
          style={{
            width: '220px',
            background: '#07080C',
            borderRight: '1px solid #1A1F2E',
          }}
        >
          {/* Logo */}
          <div
            className="flex items-center gap-3 px-5"
            style={{ height: '60px', borderBottom: '1px solid #1A1F2E' }}
          >
            <div
              className="flex items-center justify-center rounded-md"
              style={{
                width: 32,
                height: 32,
                background: 'linear-gradient(135deg, #0ECFB3, #099A84)',
              }}
            >
              <span style={{ fontFamily: 'Syne', fontWeight: 800, fontSize: 14, color: '#050608' }}>
                AT
              </span>
            </div>
            <div>
              <div style={{ fontFamily: 'Syne', fontWeight: 700, fontSize: 13, color: '#E8EAF0', letterSpacing: '0.06em' }}>
                ALPACA
              </div>
              <div style={{ fontFamily: 'JetBrains Mono', fontSize: 9, color: '#6B7280', letterSpacing: '0.12em' }}>
                TRADER v3
              </div>
            </div>
          </div>

          {/* Nav */}
          <nav className="flex-1 py-4" style={{ padding: '16px 10px' }}>
            {navItems.map(({ to, icon: Icon, label }) => (
              <NavLink
                key={to}
                to={to}
                end={to === '/'}
                style={({ isActive }) => ({
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  padding: '9px 12px',
                  borderRadius: 6,
                  marginBottom: 2,
                  textDecoration: 'none',
                  fontFamily: 'Syne',
                  fontSize: 13,
                  fontWeight: isActive ? 600 : 400,
                  color: isActive ? '#0ECFB3' : '#6B7280',
                  background: isActive ? 'rgba(14,207,179,0.08)' : 'transparent',
                  border: `1px solid ${isActive ? 'rgba(14,207,179,0.15)' : 'transparent'}`,
                  transition: 'all 0.12s',
                })}
              >
                <Icon size={16} />
                {label}
              </NavLink>
            ))}
          </nav>

          {/* Footer */}
          <div
            className="px-4 py-3"
            style={{ borderTop: '1px solid #1A1F2E' }}
          >
            <div style={{ fontFamily: 'JetBrains Mono', fontSize: 10, color: '#2A2F3E' }}>
              PAPER TRADING
            </div>
          </div>
        </aside>

        {/* Main */}
        <main className="flex-1 overflow-y-auto bg-grid">
          <Routes>
            <Route path="/"         element={<Overview />} />
            <Route path="/chain"    element={<OptionsChain />} />
            <Route path="/positions"element={<Positions />} />
            <Route path="/orders"   element={<Orders />} />
            <Route path="/strategy" element={<StrategyMonitor />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}
