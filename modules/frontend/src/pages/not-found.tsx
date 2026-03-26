import { Link } from 'react-router-dom'
import { ROUTES } from '@/lib/constants'

export default function NotFoundPage() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 p-8">
      <h1 className="text-4xl font-bold">404</h1>
      <p className="text-muted-foreground">Page not found</p>
      <Link to={ROUTES.DASHBOARD} className="text-primary hover:underline">
        Back to Dashboard
      </Link>
    </div>
  )
}
