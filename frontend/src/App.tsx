import { createBrowserRouter, RouterProvider, Navigate, Outlet, useLocation, useNavigate, useParams } from 'react-router-dom'
import { Layout, Nav, Button, Space, Typography } from '@douyinfe/semi-ui'
import { IconArrowLeft } from '@douyinfe/semi-icons'
import ThemeToggle from './components/ThemeToggle'
import ProjectListPage from './pages/ProjectListPage'
import NewProjectPage from './pages/NewProjectPage'
import ProjectEpisodesPage from './pages/ProjectEpisodesPage'
import NewCreationPage from './pages/NewCreationPage'
import ProjectDetailPage from './pages/ProjectDetailPage'
import ProvidersPage from './pages/ProvidersPage'
import StoragePage from './pages/StoragePage'
import AssetsPage from './pages/AssetsPage'
import CharactersPage from './pages/CharactersPage'
import StoriesPage from './pages/StoriesPage'
import StoryDetailPage from './pages/StoryDetailPage'
import ScriptDetailPage from './pages/ScriptDetailPage'

const { Header, Content } = Layout
const { Text } = Typography

const NAV_ITEMS = [
  { itemKey: '/', text: '作品列表' },
  // 剧本不作一级入口:它是某段原文的改编方案,归在故事详情页里。
  // 单独列一个"剧本库"会让用户以为那是个可以独立创作的地方,而它自己建不出任何东西 ——
  // 每一条都是从剧集沉淀或改编切分而来。
  { itemKey: '/stories', text: '故事' },
  { itemKey: '/assets', text: '素材库' },
  { itemKey: '/providers', text: '模型管理' },
  { itemKey: '/storage', text: '存储管理' },
]

// 顶级页(导航目的地)不显示返回 —— 那里"返回上一页"没有意义
const TOP_LEVEL = ['/', '/stories', '/assets', '/providers', '/storage']

function RootLayout() {
  const location = useLocation()
  const navigate = useNavigate()
  const selected = location.pathname.startsWith('/providers')
    ? '/providers'
    : location.pathname.startsWith('/storage')
      ? '/storage'
      : location.pathname.startsWith('/assets')
        ? '/assets'
        // 方案详情(/scripts/:id)也高亮「故事」—— 它是故事底下的一层,
        // 从故事详情/改编面板/剧集页进入,不再有独立的一级入口
        : location.pathname.startsWith('/stories') || location.pathname.startsWith('/scripts')
          ? '/stories'
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
          footer={<ThemeToggle />}
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

/** 旧路径 /projects/:id/episodes/new → 新入口。带上 id,不能直接 Navigate 常量路径。 */
function NewEpisodeRedirect() {
  const { id } = useParams<{ id: string }>()
  return <Navigate to={`/projects/${id}/create`} replace />
}

const router = createBrowserRouter([
  {
    element: <RootLayout />,
    children: [
      { path: '/', element: <ProjectListPage /> },
      { path: '/new', element: <NewProjectPage /> },
      { path: '/projects/:id', element: <ProjectEpisodesPage /> },
      { path: '/projects/:id/characters', element: <CharactersPage /> },
      { path: '/projects/:id/create', element: <NewCreationPage /> },
      // 旧链接不死:改名前的路径重定向到新入口
      { path: '/projects/:id/episodes/new', element: <NewEpisodeRedirect /> },
      { path: '/episodes/:episodeId', element: <ProjectDetailPage /> },
      { path: '/providers', element: <ProvidersPage /> },
      { path: '/storage', element: <StoragePage /> },
      { path: '/assets', element: <AssetsPage /> },
      { path: '/stories', element: <StoriesPage /> },
      // 组内详情与总览是同一页的两态(StoriesPage 按 groupKey 分流);
      // 放在 /stories/:id 之前,否则 "group" 会被当成故事 id 匹配掉
      { path: '/stories/group/:groupKey', element: <StoriesPage /> },
      { path: '/stories/:id', element: <StoryDetailPage /> },
      // 方案详情保留,但没有列表页 —— 剧本在故事详情页的「改编方案」区块里列
      { path: '/scripts/:id', element: <ScriptDetailPage /> },
      { path: '*', element: <Navigate to="/" /> },
    ],
  },
])

export default function App() {
  return <RouterProvider router={router} />
}
