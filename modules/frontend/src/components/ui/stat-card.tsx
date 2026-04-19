import { Card, CardContent } from '@/components/ui/card'

export function StatCard({
  icon,
  label,
  value,
}: {
  icon?: React.ReactNode
  label: string
  value: string | number
}) {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 py-4 px-4">
        {icon && (
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-muted">
            {icon}
          </div>
        )}
        <div>
          <p className="text-xs text-muted-foreground">{label}</p>
          <p className="text-lg font-semibold">{value}</p>
        </div>
      </CardContent>
    </Card>
  )
}
