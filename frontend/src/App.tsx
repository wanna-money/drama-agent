import { BrowserRouter, Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { Layout } from '@douyinfe/semi-ui'
import ProjectListPage from './pages/ProjectListPage'
import NewProjectPage from './pages/NewProjectPage'
import ProjectDetailPage from './pages/ProjectDetailPage'

const { Header, Content } = Layout

const NAV_ITEMS = [
  { key: '/', label: '作品列表' },
  { key: '/new', label: '新建项目' },
]

function CinemaNav() {
  const location = useLocation()
  const navigate = useNavigate()
  const active = location.pathname === '/new' ? '/new' : '/'

  return (
    <nav style={{ display: 'flex', gap: 2 }}>
      {NAV_ITEMS.map(item => (
        <button
          key={item.key}
          onClick={() => navigate(item.key)}
          style={{
            background: active === item.key ? 'rgba(124,58,237,0.08)' : 'transparent',
            border: 'none',
            cursor: 'pointer',
            padding: '6px 16px',
            borderRadius: '100px',
            fontSize: 13,
            fontFamily: 'inherit',
            fontWeight: active === item.key ? 600 : 400,
            color: active === item.key ? '#7C3AED' : '#6B7280',
            transition: 'all 0.18s',
          }}
          onMouseEnter={e => {
            if (active !== item.key) {
              (e.currentTarget as HTMLButtonElement).style.background = 'rgba(124,58,237,0.05)'
              ;(e.currentTarget as HTMLButtonElement).style.color = '#7C3AED'
            }
          }}
          onMouseLeave={e => {
            if (active !== item.key) {
              (e.currentTarget as HTMLButtonElement).style.background = 'transparent'
              ;(e.currentTarget as HTMLButtonElement).style.color = '#6B7280'
            }
          }}
        >
          {item.label}
        </button>
      ))}
    </nav>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Layout style={{ minHeight: '100vh', background: 'transparent' }}>
        <Header
          style={{
            background: 'rgba(255,255,255,0.65)',
            backdropFilter: 'blur(24px)',
            WebkitBackdropFilter: 'blur(24px)',
            borderBottom: '1px solid rgba(255,255,255,0.85)',
            boxShadow: '0 1px 12px rgba(100,80,180,0.08)',
            padding: '0 32px',
            height: 58,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            position: 'sticky',
            top: 0,
            zIndex: 100,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 32 }}>
            {/* Logo */}
            <div style={{ display: 'flex', flexDirection: 'column', lineHeight: 1 }}>
              <span style={{
                fontSize: 17,
                fontWeight: 800,
                background: 'linear-gradient(135deg, #7C3AED, #3B82F6)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                backgroundClip: 'text',
                letterSpacing: '-0.3px',
              }}>
                Drama Agent
              </span>
              <span style={{ fontSize: 9, letterSpacing: '2px', color: '#9CA3AF', textTransform: 'uppercase', marginTop: 1 }}>
                AI Short Film Studio
              </span>
            </div>
            <CinemaNav />
          </div>
          <span style={{ fontSize: 11, color: '#D1D5DB', letterSpacing: '1px', textTransform: 'uppercase', fontWeight: 500 }}>
            Powered by LangGraph
          </span>
        </Header>
        <Content style={{ background: 'transparent', position: 'relative', zIndex: 1 }}>
          <div className="page-container">
            <Routes>
              <Route path="/" element={<ProjectListPage />} />
              <Route path="/new" element={<NewProjectPage />} />
              <Route path="/projects/:id" element={<ProjectDetailPage />} />
              <Route path="*" element={<Navigate to="/" />} />
            </Routes>
          </div>
        </Content>
      </Layout>
    </BrowserRouter>
  )
}
