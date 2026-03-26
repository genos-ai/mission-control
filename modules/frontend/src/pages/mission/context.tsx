import { FileText } from 'lucide-react'
import { EmptyState } from '@/components/ui/empty-state'

export default function ContextPage() {
  return (
    <div className="p-6">
      <EmptyState
        icon={<FileText className="h-6 w-6 text-muted-foreground" />}
        title="No context yet"
        description="Context builds automatically as workflows run."
      />
    </div>
  )
}
