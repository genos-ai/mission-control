import { Eye, Shield, ShieldCheck, User } from 'lucide-react'

import { StatusPill } from '@/components/ui/status-pill'
import { cn } from '@/lib/cn'
import { statusLabel } from '@/lib/format'
import { styleFor, type StatusStyle } from '@/lib/status-tone'
import type { UserResponse } from '@/types'

type SystemRole = UserResponse['system_role']

// Keyed by the full role union, so a new role fails compilation until it has a style.
const ROLE_STYLE: Record<SystemRole, StatusStyle> = {
  sysadmin: { tone: 'violet', icon: ShieldCheck },
  admin: { tone: 'brand', icon: Shield },
  user: { tone: 'neutral', icon: User },
  viewer: { tone: 'neutral', icon: Eye },
}

// The roles an admin can hand out: the API rejects anything else, `sysadmin` included.
const ASSIGNABLE_ROLES = ['viewer', 'user', 'admin'] as const

const SELECT_BASE =
  'border border-border-strong bg-field outline-none transition-colors focus:border-brand/60 focus:ring-2 focus:ring-brand/15 disabled:cursor-not-allowed disabled:opacity-50'

export function UserRolePill({ role }: { role: string }) {
  const { tone, icon: Icon } = styleFor(ROLE_STYLE, role, 'user role')
  return (
    <StatusPill tone={tone} dot={false}>
      <Icon className="h-3 w-3" />
      {statusLabel(role)}
    </StatusPill>
  )
}

export interface UserRoleSelectProps {
  value: string
  onChange: (role: string) => void
  /** Accessible name when no visible label points at the select. */
  label?: string
  id?: string
  /** `sm` fits a table row; `md` matches the form inputs. */
  size?: 'sm' | 'md'
}

/** Native select over the assignable roles. A role outside that list is shown as the current, unselectable value. */
export function UserRoleSelect({ value, onChange, label, id, size = 'md' }: UserRoleSelectProps) {
  const assignable = ASSIGNABLE_ROLES.some((role) => role === value)
  return (
    <select
      id={id}
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={cn(
        SELECT_BASE,
        size === 'sm' ? 'h-[26px] w-[96px] rounded-chip px-2 text-xs' : 'flex h-[38px] w-full rounded-md px-3 text-md',
      )}
    >
      {!assignable && (
        <option value={value} disabled>
          {statusLabel(value)}
        </option>
      )}
      {ASSIGNABLE_ROLES.map((role) => (
        <option key={role} value={role}>
          {statusLabel(role)}
        </option>
      ))}
    </select>
  )
}
