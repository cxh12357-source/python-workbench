import type { CourseIndex, Lesson, LearningState, Run, CheckResult, Project, ProjectCheck } from './types'

export class ApiError extends Error { constructor(public status: number, message: string) { super(message) } }
let runnerToken = ''
let lessons: Record<string, Lesson> = {}
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { ...init, headers: { 'Content-Type': 'application/json', ...(runnerToken ? { 'X-Runner-Token': runnerToken } : {}), ...init.headers } })
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    const message = typeof data.detail === 'string' ? data.detail : typeof data.message === 'string' ? data.message : `操作暂时无法完成（${response.status}）`
    throw new ApiError(response.status, message)
  }
  return response.status === 204 ? undefined as T : response.json()
}
export const api = {
  async connect() { const session = await request<{ token: string }>('/api/session', { headers: { 'X-Runner-Bootstrap': '1' } }); runnerToken = session.token },
  async course() { const response = await request<{ index: CourseIndex; lessons: Record<string, Lesson> }>('/api/course'); lessons = response.lessons; return response.index },
  async lesson(id: string) { if (!lessons[id]) throw new Error('这个单元的学习内容还未准备好。'); return lessons[id] },
  exercises: (id: string) => lessons[id]?.exercises || [],
  state: () => request<LearningState>('/api/state'),
  save: (state: LearningState) => request<LearningState>('/api/state', { method: 'PUT', body: JSON.stringify({ current_unit: state.current_unit, units: state.units }) }),
  run: (code: string, argv: string[], timeout_seconds: number, context?: { files?: Record<string, string>; entrypoint?: string; pytest_mode?: boolean }) => request<Run>('/api/runs', { method: 'POST', body: JSON.stringify({ code, stdin: '', argv, interactive: !context?.pytest_mode, timeout_seconds, ...context }) }),
  poll: (id: string) => request<Run>(`/api/runs/${encodeURIComponent(id)}`),
  stop: (id: string) => request<Run>(`/api/runs/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  input: (id: string, text: string, eof = false) => request<Run>(`/api/runs/${encodeURIComponent(id)}/input`, { method: 'POST', body: JSON.stringify({ text, eof }) }),
  async artifact(id: string, name: string) {
    const path = name.split('/').map(encodeURIComponent).join('/')
    const response = await fetch(`/api/runs/${encodeURIComponent(id)}/artifacts/${path}`, { headers: { 'X-Runner-Token': runnerToken } })
    if (!response.ok) throw new ApiError(response.status, '运行文件暂时无法打开。')
    return response.blob()
  },
  check: (exercise_id: string, code: string) => request<CheckResult>('/api/checks', { method: 'POST', body: JSON.stringify({ exercise_id, code }) }),
  project: () => request<Project>('/api/project'),
  saveProject: (project: Project) => request<Project>('/api/project', { method: 'PUT', body: JSON.stringify(project) }),
  checkProject: () => request<ProjectCheck>('/api/project/check', { method: 'POST', body: '{}' }),
  runProject: (argv: string[], mode: 'run' | 'test', timeout_seconds: number) => request<Run>(mode === 'test' ? '/api/project/tests' : '/api/project/runs', { method: 'POST', body: JSON.stringify({ stdin: '', argv, interactive: mode === 'run', timeout_seconds }) }),
  async exportBackup() {
    const response = await fetch('/api/backup', { headers: { 'X-Runner-Token': runnerToken } })
    if (!response.ok) throw new ApiError(response.status, '备份导出失败，请稍后重试。')
    return response.blob()
  },
  async exportProject() {
    const response = await fetch('/api/project/export', { headers: { 'X-Runner-Token': runnerToken } })
    if (!response.ok) throw new ApiError(response.status, '项目导出失败，请稍后重试。')
    return response.blob()
  },
  restore: (backup: unknown) => request<LearningState>('/api/restore', { method: 'POST', body: JSON.stringify(backup) }),
}
