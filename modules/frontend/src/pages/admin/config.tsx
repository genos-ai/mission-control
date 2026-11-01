import { useAdminConfig } from '@/hooks/use-admin'
import { ConfigSections } from '@/components/admin/config-sections'
import { Spinner } from '@/components/ui/spinner'

export default function AdminConfigPage() {
  const { data: config, isLoading } = useAdminConfig()

  if (isLoading) {
    return (
      <div className="flex justify-center p-12">
        <Spinner className="h-5 w-5" />
      </div>
    )
  }

  return (
    <>
      <div>
        <h2 className="text-base font-medium">Platform configuration</h2>
        <p className="mt-1 text-sm text-subtle">Non-secret configuration values. Read-only view.</p>
      </div>
      {config && <ConfigSections config={config} />}
    </>
  )
}
