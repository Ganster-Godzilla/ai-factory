// 与后端 /api/v1/office 对齐的类型(orchestrator/dashboard/office.py)
export interface TicketCard {
  id: string
  project: string
  summary: string
  state: string
  last_update: string
  blocked: string | null
  bubbles: string[]
  artifacts: string[]
  tasks_done: number
  tasks_total: number
}

export interface Role {
  key: string
  title: string
  nick: string
  icon: string
  count: number
  status: 'active' | 'idle'
  tickets: TicketCard[]
}

export interface OfficeData {
  synced_at: string
  project: string | null
  projects: string[]
  kpi: {
    running: number
    pending_approval: number
    suspended: number
    today_done: number
    ds_today: number
  }
  roles: Role[]
  attention: TicketCard[]
  observation: TicketCard[]
}

export async function fetchOffice(project: string | null): Promise<OfficeData> {
  const url = '/api/v1/office' + (project ? `?project=${encodeURIComponent(project)}` : '')
  const r = await fetch(url)
  if (!r.ok) throw new Error(`office ${r.status}`)
  return r.json()
}
