import { Outlet } from 'react-router-dom'
import { AdminTabs } from '@/components/admin/admin-tabs'
import { DocumentPage } from '@/components/layout/document-page'
import { TopBar } from '@/components/layout/top-bar'

export default function AdminLayout() {
  return (
    <>
      <TopBar segments={[{ label: 'Admin' }]} />
      <DocumentPage className="gap-4 pt-4">
        <AdminTabs />
        <div className="flex flex-col gap-4">
          <Outlet />
        </div>
      </DocumentPage>
    </>
  )
}
