import { createBrowserRouter, RouterProvider, Navigate, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Layout, Nav, Button, Space, Typography } from '@douyinfe/semi-ui'
import { IconArrowLeft } from '@douyinfe/semi-icons'
import ProjectListPage from './pages/ProjectListPage'
import NewProjectPage from './pages/NewProjectPage'
import ProjectEpisodesPage from './pages/ProjectEpisodesPage'
import NewEpisodePage from './pages/NewEpisodePage'
import ProjectDetailPage from './pages/ProjectDetailPage'
import ProvidersPage from './pages/ProvidersPage'
import AssetsPage from './pages/AssetsPage'
import CharactersPage from './pages/CharactersPage'
import ScriptsPage from './pages/ScriptsPage'
import ScriptDetailPage from './pages/ScriptDetailPage'

const { Header, Content } = Layout
const { Text } = Typography

const NAV_ITEMS = [
  { itemKey: '/', text: '作品列表' },
  { itemKey: '/scripts', text: '剧本' },
  { itemKey: '/assets', text: '素材库' },
  { itemKey: '/providers', text: '模型管理' },
]

// 顶级页(导航目的地)不显示返回 —— 那里"返回上一页"没有意义
const TOP_LEVEL = ['/', '/scripts', '/assets', '/providers']

function RootLayout() {
  const location = useLocation()
  const navigate = useNavigate()
  const selected = location.pathname.startsWith('/providers')
    ? '/providers'
    : location.pathname.startsWith('/assets')
      ? '/assets'
      : location.pathname.startsWith('/scripts')
        ? '/scripts'
        : '/'
  const showBack = !TOP_LEVEL.includes(location.pathname)
  // 返回浏览器历史上一页;若是直接打开的深链接(无历史)则兜底回作品列表
  const goBack = () => { if (location.key !== 'default') navigate(-1); else navigate('/') }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header style={{ backgroundColor: 'var(--semi-color-bg-1)' }}>
        <Nav
          mode="horizontal"
          selectedKeys={[selected]}
          onSelect={({ itemKey }) => navigate(itemKey as string)}
          items={NAV_ITEMS}
          header={
            <Space align="center">
              {showBack && (
                <Button
                  theme="borderless" type="tertiary" icon={<IconArrowLeft />}
                  onClick={goBack}
                >返回</Button>
              )}
              <Text strong>Drama Agent</Text>
            </Space>
          }
        />
      </Header>
      <Content style={{ display: 'flex', flexDirection: 'column', padding: '24px' }}>
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', width: '100%' }}>
          <Outlet />
        </div>
      </Content>
    </Layout>
  )
}

const router = createBrowserRouter([
  {
    element: <RootLayout />,
    children: [
      { path: '/', element: <ProjectListPage /> },
      { path: '/new', element: <NewProjectPage /> },
      { path: '/projects/:id', element: <ProjectEpisodesPage /> },
      { path: '/projects/:id/characters', element: <CharactersPage /> },
      { path: '/projects/:id/episodes/new', element: <NewEpisodePage /> },
      { path: '/episodes/:episodeId', element: <ProjectDetailPage /> },
      { path: '/providers', element: <ProvidersPage /> },
      { path: '/assets', element: <AssetsPage /> },
      { path: '/scripts', element: <ScriptsPage /> },
      { path: '/scripts/:id', element: <ScriptDetailPage /> },
      { path: '*', element: <Navigate to="/" /> },
    ],
  },
])

export default function App() {
  return <RouterProvider router={router} />
}
