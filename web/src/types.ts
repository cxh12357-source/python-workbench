export type Resource = { url: string | null; status?: string }
export type Unit = {
  id: string; kind: 'week' | 'project'; week: number | null; order: number;
  titleEn: string; titleZh: string; summaryZh: string; topics: string[];
  resources: { course: Resource; notes: Resource; problemSet: Resource; officialVideo: Resource; youtube: Resource }
}
export type CourseIndex = {
  titleZh: string; units: Unit[]; verifiedOn: string;
  userVideoEntry: { url: string; reasonZh: string }
}
export type Point = { title: string; body: string; example?: string }
export type Example = { id: string; title: string; code: string; stdin?: string; argv?: string[]; explanation?: string; files?: Record<string, string>; entrypoint?: string; pytest_mode?: boolean }
export type Exercise = {
  id: string; title: string; prompt: string; starter_code: string;
  hints: string[]; solution: string; stdin?: string; argv?: string[];
  kind?: string; files?: Record<string, string>; entrypoint?: string
}
export type Lesson = { unit_id: string; points: Point[]; examples: Example[]; exercises: Exercise[]; source_note?: string }
export type UnitState = { completed_steps: string[]; note: string; code: string; selected_exercise?: string; selected_example?: string; video_url?: string; drafts?: Record<string, string>; official_status?: 'not_started' | 'working' | 'done'; official_note?: string }
export type Mistake = { id: string; unit_id: string; exercise_id: string; title: string; message: string; code?: string; created_at: string; resolved?: boolean }
export type LearningState = { current_unit: string; units: Record<string, UnitState>; mistakes: Mistake[]; exercise_progress?: Record<string, { passed: boolean; attempts: number; last_attempt_at: string }> }
export type Run = { id: string; status: string; stdout: string; stderr: string; exit_code: number | null; duration_ms: number | null; output_bytes: number; interactive?: boolean; input_open?: boolean; artifacts?: { name: string; size: number; mime: string }[] }
export type CheckResult = { exercise_id: string; passed: boolean; passed_count: number; total: number; cases: { name: string; passed: boolean; expected?: string; actual?: string; message?: string }[]; attempt_id: string }
export type Project = { files: Record<string, string>; entrypoint: string }
export type ProjectCheck = { checks: { name: string; passed: boolean; message: string }[] }
