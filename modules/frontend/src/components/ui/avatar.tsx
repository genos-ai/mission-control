import { cn } from '@/lib/cn'

interface AvatarProps {
  name: string
  className?: string
}

export function Avatar({ name, className }: AvatarProps) {
  const initials = name
    .split(' ')
    .map((w) => w[0])
    .join('')
    .toUpperCase()
    .slice(0, 2)

  return (
    <div
      className={cn(
        'flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-full bg-line text-[10.5px] font-semibold text-text-3',
        className,
      )}
    >
      {initials}
    </div>
  )
}
