import { lazy, Suspense, useEffect, useRef, useState, type ReactNode } from 'react'
import { ArrowDownToLine, ArrowRight, BookOpen, Check, CheckCircle2, ChevronRight, Circle, Code2, ExternalLink, FileCode2, FolderOpen, GraduationCap, Lightbulb, ListChecks, Menu, NotebookPen, Play, Plus, RotateCcw, Save, Settings2, Square, Terminal, Upload, X } from 'lucide-react'
import { api } from './api'
import { embedUrl, safeLink } from './video'
import type { CheckResult, CourseIndex, Example, Exercise, LearningState, Lesson, Project, ProjectCheck, Run, UnitState } from './types'

const steps = [{ id: 'video', label: '看视频' }, { id: 'points', label: '中文要点' }, { id: 'example', label: '修改示例' }, { id: 'practice', label: '做练习' }, { id: 'review', label: '复习与笔记' }]
const Editor = lazy(() => import('./Editor'))
const emptyUnit = (): UnitState => ({ completed_steps: [], note: '', code: '', drafts: {} })
const isActiveRun = (run: Run | null) => !!run && ['queued', 'running'].includes(run.status)
const runLabels: Record<string, string> = { queued: '准备运行', running: '运行中', completed: '运行完成', error: '程序报错', timeout: '运行超过时限', stopped: '已停止', output_limit: '输出超过上限' }

function Link({ href, children }: { href: string | null | undefined; children: ReactNode }) {
  return href && safeLink(href) ? <a href={href} target="_blank" rel="noreferrer">{children}<ExternalLink size={13} /></a> : null
}

export default function App() {
  const [course, setCourse] = useState<CourseIndex | null>(null)
  const [state, setState] = useState<LearningState | null>(null)
  const [lesson, setLesson] = useState<Lesson | null>(null)
  const [step, setStep] = useState('video')
  const [view, setView] = useState<'learn' | 'review' | 'settings'>('learn')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [saving, setSaving] = useState('')
  const [booting, setBooting] = useState(true)
  const [run, setRun] = useState<Run | null>(null)
  const [runPending, setRunPending] = useState(false)
  const [pollRetries, setPollRetries] = useState(0)
  const [stdin, setStdin] = useState('')
  const [argv, setArgv] = useState('')
  const [runTimeout, setRunTimeout] = useState(120)
  const [inputPending, setInputPending] = useState(false)
  const [artifactPreview, setArtifactPreview] = useState<{ url: string; name: string } | null>(null)
  const [checking, setChecking] = useState(false)
  const [checkResult, setCheckResult] = useState<CheckResult | null>(null)
  const [hintCount, setHintCount] = useState(0)
  const [showAnswer, setShowAnswer] = useState(false)
  const [videoSettings, setVideoSettings] = useState(false)
  const [videoDraft, setVideoDraft] = useState('')
  const [menuOpen, setMenuOpen] = useState(false)
  const [project, setProject] = useState<Project | null>(null)
  const [activeFile, setActiveFile] = useState('project.py')
  const [projectCheck, setProjectCheck] = useState<ProjectCheck | null>(null)
  const [projectDirty, setProjectDirty] = useState(false)
  const [fileName, setFileName] = useState('')
  const [restoring, setRestoring] = useState(false)
  const stateRef = useRef(state)
  const saveChain = useRef(Promise.resolve())
  const stateSaveTimer = useRef<number | null>(null)
  const projectSaveTimer = useRef<number | null>(null)
  const pauseSaving = useRef(false)
  const saveGeneration = useRef(0)
  const projectDirtyRef = useRef(projectDirty)
  const skipSave = useRef(true)
  const restoreInput = useRef<HTMLInputElement>(null)
  const projectRef = useRef(project)
  stateRef.current = state
  projectRef.current = project
  projectDirtyRef.current = projectDirty

  useEffect(() => {
    let live = true
    async function boot() {
      try {
        await api.connect()
        const [index, saved] = await Promise.all([api.course(), api.state()])
        if (!live) return
        setCourse(index); setState(saved); setSaving('已保存在此电脑'); setBooting(false)
      } catch (err) { if (live) { setError(message(err)); setBooting(false) } }
    }
    void boot()
    return () => { live = false }
  }, [])

  const unitId = state?.current_unit || 'week-0'
  const unit = course?.units.find(item => item.id === unitId) || course?.units[0]
  const savedUnitState = state?.units[unitId] || emptyUnit()
  const practicePassed = (id: string) => { const exercises = api.exercises(id); return exercises.length === 3 && exercises.every(item => state?.exercise_progress?.[item.id]?.passed) }
  const unitState = unit?.kind === 'week' ? { ...savedUnitState, completed_steps: practicePassed(unitId) ? [...new Set([...savedUnitState.completed_steps, 'practice'])] : savedUnitState.completed_steps.filter(id => id !== 'practice') } : savedUnitState
  const exercise = lesson?.exercises.find(item => item.id === unitState.selected_exercise) || lesson?.exercises[0]
  const selectedExample = lesson?.examples.find(item => item.id === unitState.selected_example) || lesson?.examples[0]
  const editorFilename = unit?.kind === 'project' ? activeFile : (unitState.selected_exercise ? exercise?.entrypoint : selectedExample?.entrypoint) || 'main.py'
  const completedUnits = course?.units.filter(item => steps.every(s => s.id === 'practice' && item.kind === 'week' ? practicePassed(item.id) : state?.units[item.id]?.completed_steps.includes(s.id))).length || 0
  const videoUrl = unitState.video_url || unit?.resources.officialVideo.url || ''
  const videoEmbed = embedUrl(videoUrl)
  const busy = runPending || isActiveRun(run) || checking
  const canInput = isActiveRun(run) && run?.interactive && run.input_open && pollRetries === 0

  useEffect(() => {
    if (!state || !unit) return
    let live = true
    setLesson(null); setCheckResult(null); setHintCount(0); setShowAnswer(false); setStdin(''); setArgv(''); setProjectCheck(null)
    if (unit.kind === 'project') {
      api.project().then(value => { if (live) { setProject(value); setActiveFile(value.entrypoint); setProjectDirty(false) } }).catch(err => { if (live) setError(message(err)) })
    }
    api.lesson(unitId).then(value => {
      if (!live) return
      setLesson(value)
      const saved = stateRef.current?.units[unitId]
      if (!saved && unit.kind === 'week') {
        const sample = value.examples[0]
        if (sample) { updateUnit({ code: sample.code, selected_example: sample.id }); setArgv(sample.argv?.join('\n') || '') }
      }
    }).catch(err => { if (live) setError(message(err)) })
    return () => { live = false }
  }, [unitId, course])

  useEffect(() => {
    if (!state) return
    if (skipSave.current) { skipSave.current = false; return }
    if (pauseSaving.current) return
    setSaving('正在保存…')
    const timeout = window.setTimeout(() => {
      stateSaveTimer.current = null
      void enqueueSave(stateRef.current).catch(saveFailed)
    }, 650)
    stateSaveTimer.current = timeout
    return () => window.clearTimeout(timeout)
  }, [state])

  useEffect(() => {
    if (!isActiveRun(run)) return
    const timeout = window.setTimeout(() => {
      api.poll(run!.id).then(value => { setRun(value); setPollRetries(0) }).catch(err => { setError(message(err)); setPollRetries(count => count + 1) })
    }, Math.min(3000, 250 * 2 ** pollRetries))
    return () => window.clearTimeout(timeout)
  }, [run, pollRetries])

  useEffect(() => {
    if (!projectDirty || !project || pauseSaving.current) return
    const timeout = window.setTimeout(() => {
      projectSaveTimer.current = null
      void enqueueSave(null, projectRef.current).catch(saveFailed)
    }, 650)
    projectSaveTimer.current = timeout
    return () => window.clearTimeout(timeout)
  }, [project, projectDirty])

  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => { if (projectDirty || saving === '正在保存…' || isActiveRun(run)) event.preventDefault() }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [projectDirty, saving, run])

  useEffect(() => () => { if (artifactPreview) URL.revokeObjectURL(artifactPreview.url) }, [artifactPreview])

  function updateUnit(patch: Partial<UnitState>) {
    setState(previous => previous ? { ...previous, units: { ...previous.units, [unitId]: { ...(previous.units[unitId] || emptyUnit()), ...patch } } } : previous)
  }
  function editCode(code: string) {
    const key = unitState.selected_exercise || unitState.selected_example || 'example'
    updateUnit({ code, drafts: { ...unitState.drafts, [key]: code } })
    setCheckResult(null)
  }
  async function navigate(id: string, exerciseId?: string, code?: string) {
    if (projectDirtyRef.current && projectRef.current) {
      try { await flushSaves() }
      catch (err) { setError(message(err)); return }
    }
    setState(previous => previous ? { ...previous, current_unit: id, ...(exerciseId ? { units: { ...previous.units, [id]: { ...(previous.units[id] || emptyUnit()), selected_exercise: exerciseId, code: code ?? previous.units[id]?.drafts?.[exerciseId] ?? '' } } } : {}) } : previous)
    setStep('video'); setView('learn'); setMenuOpen(false); setVideoSettings(false)
  }
  function toggleStep() {
    if (step === 'practice' && unit?.kind === 'week') return
    const completed = unitState.completed_steps
    updateUnit({ completed_steps: completed.includes(step) ? completed.filter(id => id !== step) : [...completed, step] })
  }
  function pickExercise(item: Exercise) {
    updateUnit({ selected_exercise: item.id, code: unitState.drafts?.[item.id] ?? item.starter_code })
    setStdin(''); setArgv(item.argv?.join('\n') || ''); setHintCount(0); setShowAnswer(false); setCheckResult(null); setStep('practice')
  }
  function loadExample(item: Example) {
    if (unit?.kind === 'project' && project) {
      const directory = `examples/${item.id}`
      const target = `${directory}/project.py`
      const files = { ...project.files }
      for (const [name, content] of Object.entries(item.files || {})) files[`${directory}/${name}`] ??= content
      files[target] ??= item.code
      setProject({ ...project, files, entrypoint: target }); setActiveFile(target); setProjectDirty(true)
      setNotice(`示例已加入 ${directory}，你的原有项目文件保留。`)
    } else updateUnit({ selected_exercise: '', selected_example: item.id, code: unitState.drafts?.[item.id] ?? item.code })
    setStdin(''); setArgv(item.argv?.join('\n') || ''); setCheckResult(null)
  }
  function parseArgs() { return argv.split('\n').filter(value => value.length > 0) }
  async function startRun(mode: 'run' | 'test' = 'run') {
    setError(''); setRunPending(true); setRun(null); setPollRetries(0); setArtifactPreview(null)
    try {
      setStdin('')
      if (unit?.kind === 'project' && project) { await flushSaves(); setRun(await api.runProject(parseArgs(), mode, runTimeout)) }
      else { const context = unitState.selected_exercise ? { files: exercise?.files, entrypoint: exercise?.entrypoint } : { files: selectedExample?.files, entrypoint: selectedExample?.entrypoint, pytest_mode: selectedExample?.pytest_mode }; setRun(await api.run(unitState.code, parseArgs(), runTimeout, context)) }
    } catch (err) { setError(message(err)) }
    finally { setRunPending(false) }
  }
  async function stopRun() { try { if (run) setRun(await api.stop(run.id)) } catch (err) { setError(message(err)) } }
  async function sendInput(eof = false) {
    if (!run || !canInput) return
    setInputPending(true)
    try { await api.input(run.id, eof ? '' : stdin, eof); setStdin(''); setRun(await api.poll(run.id)) }
    catch (err) { setError(message(err)) }
    finally { setInputPending(false) }
  }
  async function check() {
    if (!exercise) return
    setChecking(true); setCheckResult(null); setError('')
    try {
      const result = await api.check(exercise.id, unitState.code)
      if (stateRef.current?.current_unit === unitId && stateRef.current.units[unitId]?.selected_exercise === exercise.id) setCheckResult(result)
      const refreshed = await api.state()
      setState(previous => previous ? { ...refreshed, current_unit: previous.current_unit, units: previous.units } : refreshed)
      if (lesson?.exercises.every(item => refreshed.exercise_progress?.[item.id]?.passed)) updateUnit({ completed_steps: [...new Set([...unitState.completed_steps, 'practice'])] })
    } catch (err) { setError(message(err)) }
    finally { setChecking(false) }
  }
  async function saveNow() {
    if (!stateRef.current) return
    try { await flushSaves(); setNotice('学习记录已保存。') } catch (err) { saveFailed(err) }
  }
  async function backup() {
    try {
      await flushSaves()
      const blob = await api.exportBackup(); const url = URL.createObjectURL(blob)
      const link = document.createElement('a'); link.href = url; link.download = `python-workbench-${new Date().toLocaleDateString('sv-SE')}.json`; link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000)
      setNotice('已导出备份，保存在浏览器的下载目录。')
    } catch (err) { setError(message(err)) }
  }
  async function restore(file: File | undefined) {
    if (!file) return
    try {
      const data: unknown = JSON.parse(await file.text())
      if (!window.confirm('导入会替换当前学习记录与项目文件。建议先导出一份备份。确定导入吗？')) return
      clearSaveTimers(); pauseSaving.current = true; saveGeneration.current += 1; setRestoring(true)
      await enqueueSave(stateRef.current, projectDirtyRef.current ? projectRef.current : null, true)
      const restored = await api.restore(data); skipSave.current = true; setState(restored); setProjectDirty(false)
      if (unit?.kind === 'project') setProject(await api.project())
      setNotice('备份已恢复。')
    } catch (err) { setError(message(err)) }
    finally { pauseSaving.current = false; setRestoring(false); if (restoreInput.current) restoreInput.current.value = '' }
  }
  async function validateProject() {
    if (!project) return
    setChecking(true)
    try { await flushSaves(); setProjectCheck(await api.checkProject()) } catch (err) { setError(message(err)) }
    finally { setChecking(false) }
  }
  async function exportProject() {
    if (!project) return
    try {
      await flushSaves()
      const blob = await api.exportProject(); const url = URL.createObjectURL(blob)
      const link = document.createElement('a'); link.href = url; link.download = 'my-python-project.zip'; link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000)
      setNotice('项目已导出为 ZIP 文件。')
    } catch (err) { setError(message(err)) }
  }
  async function openArtifact(name: string, preview = false) {
    if (!run) return
    try {
      const blob = await api.artifact(run.id, name); const url = URL.createObjectURL(blob)
      if (preview) setArtifactPreview({ url, name })
      else { const link = document.createElement('a'); link.href = url; link.download = name.split('/').at(-1) || name; link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000) }
    } catch (err) { setError(message(err)) }
  }
  function clearSaveTimers() {
    if (stateSaveTimer.current !== null) window.clearTimeout(stateSaveTimer.current)
    if (projectSaveTimer.current !== null) window.clearTimeout(projectSaveTimer.current)
    stateSaveTimer.current = null; projectSaveTimer.current = null
  }
  function saveFailed(err: unknown) { setSaving('保存失败'); setError(message(err)) }
  function enqueueSave(stateSnapshot: LearningState | null, projectSnapshot: Project | null = null, allowPaused = false) {
    const generation = saveGeneration.current
    const queued = saveChain.current.catch(() => {}).then(async () => {
      if (generation !== saveGeneration.current || (pauseSaving.current && !allowPaused)) return
      if (stateSnapshot) { await api.save(stateSnapshot); if (stateRef.current === stateSnapshot) setSaving('已保存在此电脑') }
      if (projectSnapshot) { await api.saveProject(projectSnapshot); if (projectRef.current === projectSnapshot) setProjectDirty(false) }
    })
    saveChain.current = queued
    return queued
  }
  async function flushSaves() {
    clearSaveTimers()
    setSaving('正在保存…')
    await enqueueSave(stateRef.current, projectDirtyRef.current ? projectRef.current : null)
    if (!pauseSaving.current) setSaving('已保存在此电脑')
  }

  if (booting) return <div className="loading-page"><Code2 size={42} /><h1>Python 工作台</h1><p>正在打开你的学习记录…</p><span className="spinner" /></div>
  if (!course || !state || !unit) return <div className="loading-page"><Code2 size={42} /><h1>工作台暂时无法打开</h1><p>{error || '请确认工作台已启动。'}</p><button className="primary" onClick={() => location.reload()}>重新连接</button></div>

  return <div className="app-shell">
    <aside inert={restoring} className={`sidebar ${menuOpen ? 'open' : ''}`}>
      <button className="brand" onClick={() => void navigate('week-0')}><span className="brand-icon"><Code2 size={24} /></span><span>Python 工作台<small>LEARN. BUILD. REPEAT.</small></span></button>
      <div className="course-caption">我的学习路径 <span>CS50P</span></div>
      <nav aria-label="课程导航" className="course-nav">{course.units.map(item => {
        const done = steps.every(s => s.id === 'practice' && item.kind === 'week' ? practicePassed(item.id) : state.units[item.id]?.completed_steps.includes(s.id))
        return <button className={view === 'learn' && item.id === unitId ? 'active' : ''} key={item.id} onClick={() => void navigate(item.id)}>
          <span className="week-marker">{item.kind === 'project' ? <GraduationCap size={18} /> : String(item.week).padStart(2, '0')}</span>
          <span><small>{item.kind === 'project' ? 'FINAL PROJECT' : `WEEK ${item.week}`}</small>{item.titleZh}</span>
          {done && <CheckCircle2 size={15} className="done-icon" />}
        </button>
      })}</nav>
      <div className="sidebar-bottom"><button className={view === 'review' ? 'selected' : ''} onClick={() => { setView('review'); setMenuOpen(false) }}><RotateCcw size={17} />错题复习<span className="count">{state.mistakes.filter(item => !item.resolved).length}</span></button><button className={view === 'settings' ? 'selected' : ''} onClick={() => { setView('settings'); setMenuOpen(false) }}><Settings2 size={17} />学习设置与备份</button></div>
      <div className="sidebar-progress"><span>课程进度<strong>{completedUnits} / {course.units.length}</strong></span><div className="progress-track"><i style={{ width: `${completedUnits / course.units.length * 100}%` }} /></div><small>一小步，也是在前进。</small></div>
    </aside>
    <main inert={restoring} className="main-area">
      <header className="topbar"><div className="breadcrumb"><button className="menu-button" aria-label="打开课程导航" onClick={() => setMenuOpen(!menuOpen)}><Menu size={22} /></button><span>我的工作台</span><ChevronRight size={14} /><strong>{view === 'learn' ? unit.kind === 'project' ? '最终项目' : `Week ${unit.week}` : view === 'review' ? '错题复习' : '学习设置'}</strong></div><div className="top-actions"><span className={`save-status ${saving === '保存失败' ? 'failed' : ''}`}><span />{saving}</span><button onClick={() => void saveNow()} title="保存学习记录"><Save size={16} /><span>保存进度</span></button></div></header>
      <div className="page-content">
        {error && <div className="banner error" role="alert"><span>{error}</span><button aria-label="关闭错误" onClick={() => setError('')}><X size={16} /></button></div>}
        {notice && <div className="banner success" role="status"><span>{notice}</span><button aria-label="关闭提示" onClick={() => setNotice('')}><X size={16} /></button></div>}
        {view === 'learn' && <>
          <section className="lesson-heading"><div><div className="eyebrow">CS50'S INTRODUCTION TO PROGRAMMING WITH PYTHON</div><h1>{unit.titleZh}<span>{unit.titleEn}</span></h1><p>{unit.summaryZh}</p></div><div className="daily-plan"><span className="daily-icon"><BookOpen size={19} /></span><div><strong>每天 30–45 分钟</strong><small>按照你的节奏，把知识写成代码。</small></div></div></section>
          <nav className="stepper" aria-label="学习步骤">{steps.map((item, index) => <button key={item.id} className={step === item.id ? 'active' : ''} onClick={() => setStep(item.id)}><span className={`step-number ${unitState.completed_steps.includes(item.id) ? 'complete' : ''}`}>{unitState.completed_steps.includes(item.id) ? <Check size={14} /> : String(index + 1).padStart(2, '0')}</span>{item.label}</button>)}</nav>
          <div className="workspace-grid">
            <section className="reading-panel">
              <div className="panel-heading"><div><span className="section-kicker">{steps.find(item => item.id === step)?.label}</span><h2>{step === 'video' ? unit.kind === 'project' ? '开始你的第一个独立项目' : '跟着课程，一步一步学' : step === 'points' ? '先理解，再动手' : step === 'example' ? '动一行代码，观察变化' : step === 'practice' ? '把学到的变成自己的' : '留给下一次的自己'}</h2></div><span className="source-badge">{step === 'video' ? '课程资源' : '工作台原创辅助'}</span></div>
              {!lesson && <div className="content-loading"><span className="spinner" />正在打开本周学习内容…</div>}
              {step === 'video' && <>
                {unit.kind === 'week' ? <><div className="video-frame">{videoEmbed ? <iframe key={videoEmbed} src={videoEmbed} title={`${unit.titleZh}课程视频`} allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; fullscreen" allowFullScreen /> : <div className="video-empty"><Play size={32} /><strong>打开本周课程视频</strong><span>可以设置本周的 B 站视频链接。</span></div>}</div><div className="video-toolbar"><Link href={videoUrl}>外部打开视频</Link><button onClick={() => { setVideoDraft(unitState.video_url || ''); setVideoSettings(!videoSettings) }}><Settings2 size={14} />设置本周视频</button></div><p className="quiet-help">如果播放器空白或无法播放，点击“外部打开视频”。</p>{videoSettings && <div className="video-settings"><label htmlFor="video-url">本周视频链接</label><input id="video-url" value={videoDraft} onChange={event => setVideoDraft(event.target.value)} placeholder="粘贴 B 站或 YouTube 视频地址" /><div><button className="primary small" onClick={() => { if (videoDraft && !safeLink(videoDraft)) { setError('请输入完整的 http 或 https 视频链接。'); return } updateUnit({ video_url: videoDraft.trim() }); setVideoSettings(false) }}>保存链接</button><button className="text-button" onClick={() => { updateUnit({ video_url: '' }); setVideoSettings(false) }}>恢复官方视频</button></div><p>视频链接仅用于当前周，不会自动推断其他分集。</p></div>}<div className="user-video-entry"><strong>你收藏的 B 站课程</strong><Link href={course.userVideoEntry.url}>打开原始入口</Link><small>分 P 与周次尚未核实，可在“设置本周视频”中手动指定。</small></div></> : <div className="project-intro"><GraduationCap size={35} /><h3>从一个你想解决的小问题开始。</h3><p>选择一个足够小的目标，写出程序、测试和使用说明。在右侧管理你的项目文件。</p><Link href={unit.resources.course.url}>阅读官方最终项目要求</Link><div className="tip"><Lightbulb size={17} />可以先做一个命令行记账本、学习计时器或待办清单。</div></div>}
                <div className="learn-intent"><strong>这一周，你会学到</strong><div className="topic-chips">{unit.topics.map(topic => <span key={topic}>{topic}</span>)}</div></div>
              </>}
              {step === 'points' && lesson && <div className="knowledge-list">{lesson.points.map((point, index) => <article key={point.title}><span className="point-index">{String(index + 1).padStart(2, '0')}</span><div><h3>{point.title}</h3><p>{point.body}</p>{point.example && <pre><code>{point.example}</code></pre>}</div></article>)}{!lesson.points.length && <p>这一单元以官方项目要求为主。</p>}</div>}
              {step === 'example' && lesson && <div className="example-list"><p className="body-copy">先运行示例，读一读结果。然后修改一处代码，再运行一次，比较发生了什么。</p>{lesson.examples.map(item => <button className="example-card" key={item.id} onClick={() => loadExample(item)}><span className="example-icon"><FileCode2 size={19} /></span><span><strong>{item.title}</strong><small>{item.explanation || (unit.kind === 'project' ? '作为独立文件加入项目，再编辑与运行' : '在右侧编辑并运行这个示例')}</small></span><ArrowRight size={17} /></button>)}<div className="tip"><Lightbulb size={17} /><span>遇到错误很正常。读输出里的最后一行，看看 Python 在提醒你什么。</span></div></div>}
              {step === 'practice' && lesson && <div className="practice-panel">{lesson.exercises.length ? <><div className="exercise-tabs" aria-label="本周自主练习">{lesson.exercises.map((item, index) => <button key={item.id} className={exercise?.id === item.id ? 'active' : ''} onClick={() => pickExercise(item)}>练习 {index + 1}{state.exercise_progress?.[item.id]?.passed && <Check size={12} />}</button>)}</div>{exercise && <><span className="practice-label">自主练习 · 本地检查</span><h3>{exercise.title}</h3><p className="exercise-prompt">{exercise.prompt}</p>{exercise.kind === "function" && <p className="kind-note">这一题编写函数。只定义函数时，直接运行可能没有输出；点击“检查我的练习”会用不同输入调用它。</p>}{exercise.kind === "pytest" && <p className="kind-note">这一题编写测试。点击“检查我的练习”，检查测试是否能发现代码中的问题。</p>}<button className="outline small" onClick={() => pickExercise(exercise)}><FileCode2 size={15} />{unitState.selected_exercise === exercise.id ? '继续编辑我的草稿' : '在编辑器中开始这道题'}</button><div className="hints"><div className="hints-title"><Lightbulb size={17} /><strong>卡住时，先试试提示</strong></div>{exercise.hints.slice(0, hintCount).map((hint, index) => <p key={index}><span>提示 {index + 1}</span>{hint}</p>)}<button className="text-button" disabled={hintCount >= exercise.hints.length} onClick={() => setHintCount(count => count + 1)}>{hintCount === 0 ? '展开第一条提示' : hintCount < exercise.hints.length ? '再看一条提示' : '已展开全部提示'}<ChevronRight size={15} /></button></div><button className="answer-toggle" onClick={() => setShowAnswer(!showAnswer)}>{showAnswer ? '收起参考答案' : '我已尝试，展开参考答案'}<ChevronRight size={15} className={showAnswer ? 'rotated' : ''} /></button>{showAnswer && <pre className="answer"><code>{exercise.solution}</code></pre>}<div className="check-action"><button className="primary" disabled={busy || unitState.selected_exercise !== exercise.id} onClick={() => void check()}><ListChecks size={17} />{checking ? '正在检查…' : '检查我的练习'}</button><small>本地自测结果，不代表哈佛官方评分。</small></div>{checkResult && <div className="check-results"><h4>{checkResult.passed && checkResult.total > 0 ? '做到了，继续下一步！' : '再调整一下，你正在接近。'}<span>{checkResult.passed_count}/{checkResult.total} 通过</span></h4>{checkResult.cases.map((item, index) => <div className={item.passed ? 'case passed' : 'case failed'} key={index}>{item.passed ? <CheckCircle2 size={16} /> : <Circle size={16} />}<div><strong>{item.name}</strong>{item.message && <p>{item.message}</p>}{!item.passed && item.expected !== undefined && <pre>期望：{item.expected}{'\n'}实际：{item.actual ?? '没有输出'}</pre>}</div></div>)}</div>}</> }</> : <div className="empty-state"><ListChecks size={32} /><h3>{unit.kind === 'project' ? '让你的项目通过真实检查' : '本周自主练习还在准备中'}</h3><p>{unit.kind === 'project' ? '在右侧运行项目与 pytest，检查项目结构，再对照官方要求完善自己的功能。' : '你可以先修改课程示例，并打开下方的官方任务。'}</p></div>}</div>}
              {step === 'review' && <div className="notes-panel"><p className="body-copy">记下今天理解的一个知识点，以及下次想继续解决的问题。</p><label htmlFor="lesson-note"><NotebookPen size={17} />我的学习笔记</label><textarea id="lesson-note" value={unitState.note} onChange={event => updateUnit({ note: event.target.value })} placeholder="今天我学会了…\n让我困惑的是…\n下次我想试试…" rows={10} /><p className="quiet-help">笔记会自动保存在这台电脑上。</p><div className="review-summary"><strong>本周待复习</strong>{state.mistakes.filter(item => item.unit_id === unitId && !item.resolved).length ? state.mistakes.filter(item => item.unit_id === unitId && !item.resolved).map(item => <button key={item.id} onClick={() => { const found = lesson?.exercises.find(ex => ex.id === item.exercise_id); if (found) pickExercise(found) }}><RotateCcw size={15} />{item.title}<ArrowRight size={15} /></button>) : <p>还没有待复习的错题。试着不看示例，写一段自己的代码。</p>}</div></div>}
              <footer className="reading-footer"><button className={`completion-button ${unitState.completed_steps.includes(step) ? 'completed' : ''}`} disabled={step === 'practice' && unit.kind === 'week'} onClick={toggleStep}>{unitState.completed_steps.includes(step) ? <CheckCircle2 size={17} /> : <Circle size={17} />}{unitState.completed_steps.includes(step) ? '已完成这一步' : step === 'practice' && unit.kind === 'week' ? '通过本周 3 题后完成' : '标记这一步已完成'}</button>{steps.findIndex(item => item.id === step) < 4 && <button className="text-button" onClick={() => setStep(steps[steps.findIndex(item => item.id === step) + 1].id)}>下一步<ArrowRight size={16} /></button>}</footer>
              <div className="official-resources"><span>官方资料</span><Link href={unit.resources.notes.url}>英文讲义</Link><Link href={unit.resources.problemSet.url}>Problem Set {unit.week}</Link>{!unit.resources.problemSet.url && <Link href={unit.resources.course.url}>{unit.kind === 'project' ? '最终项目要求' : '本周课程'}</Link>}</div>
              {(unit.resources.problemSet.url || unit.kind === 'project') && <div className="official-tracker"><div><strong>{unit.kind === 'project' ? '官方项目记录' : '官方作业记录'} · 手动记录</strong><select aria-label="官方作业状态" value={unitState.official_status || 'not_started'} onChange={event => updateUnit({ official_status: event.target.value as UnitState['official_status'] })}><option value="not_started">还未开始</option><option value="working">正在完成</option><option value="done">我已完成</option></select></div><textarea aria-label="官方作业备注" value={unitState.official_note || ''} onChange={event => updateUnit({ official_note: event.target.value })} placeholder="记录官方作业完成情况或自己的疑问" rows={2} /><p>这里保存你自己的记录，不读取哈佛官方的提交状态或成绩。</p></div>}
            </section>
            <section className="coding-panel" aria-label="Python 编辑与运行">
              <div className="code-toolbar"><div><Code2 size={17} /><strong>{unit.kind === 'project' ? '项目工作区' : '代码实验室'}</strong><span>PYTHON</span></div>{unit.kind === 'week' && !unitState.selected_exercise && selectedExample && <button className="reset-example" title="恢复当前示例的原始代码" onClick={() => { updateUnit({ code: selectedExample.code, drafts: { ...unitState.drafts, [selectedExample.id]: selectedExample.code } }); setCheckResult(null) }}><RotateCcw size={13} />重置示例</button>}<button disabled={busy || (!unitState.code && !project)} onClick={() => void startRun()}><Play size={15} fill="currentColor" />{runPending || isActiveRun(run) ? '运行中' : '运行代码'}</button></div>
              {unit.kind === 'project' && project && <div className="project-files"><div className="files-title"><FolderOpen size={15} />项目文件<span>{projectDirty ? '未保存' : '已保存'}</span></div><div className="file-list">{Object.keys(project.files).map(path => <button key={path} className={activeFile === path ? 'active' : ''} onClick={() => setActiveFile(path)}><FileCode2 size={14} />{path}</button>)}</div><div className="add-file"><input aria-label="新文件名称" value={fileName} onChange={event => setFileName(event.target.value)} placeholder="新文件，如 helpers.py" /><button aria-label="新增文件" onClick={() => { const name = fileName.trim(); if (!name || name.includes('..') || name.startsWith('/') || /[\\:]/.test(name)) { setError('请输入项目内的文件名，例如 helpers.py。'); return } if (Object.hasOwn(project.files, name)) { setError('这个文件已经存在。'); return } setProject({ ...project, files: { ...project.files, [name]: '' } }); setActiveFile(name); setFileName(''); setProjectDirty(true) }}><Plus size={15} /></button></div></div>}
              <div className="file-tab"><FileCode2 size={14} />{editorFilename}<span>{unit.kind === 'project' ? '多文件编辑' : '修改后自动保存'}</span></div>
              <Suspense fallback={<div className="editor-loading">正在打开代码编辑器…</div>}><Editor filename={editorFilename} value={unit.kind === 'project' ? project?.files[activeFile] || '' : unitState.code} onChange={code => { if (unit.kind === 'project' && project) { setProject({ ...project, files: { ...project.files, [activeFile]: code } }); setProjectDirty(true) } else editCode(code) }} /></Suspense>
              <div className="input-panel"><label htmlFor="standard-input">实时输入 <span>先运行代码，再为 input() 发送一行</span></label><div className="live-input"><input id="standard-input" value={stdin} disabled={!canInput} onChange={event => setStdin(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); void sendInput() } }} placeholder={canInput ? '输入内容，按 Enter 发送' : '程序运行后可输入'} /><button disabled={!canInput || inputPending} onClick={() => void sendInput()}>{inputPending ? '发送中' : '发送'}<ArrowRight size={13} /></button></div><button className="end-input" disabled={!canInput || inputPending} onClick={() => void sendInput(true)}>结束输入</button><details className="arguments"><summary>运行设置与命令行参数</summary><label className="timeout-setting">本次运行时限<select aria-label="运行时限" value={runTimeout} onChange={event => setRunTimeout(Number(event.target.value))}><option value={30}>30 秒</option><option value={120}>120 秒</option><option value={300}>300 秒</option></select></label><textarea aria-label="命令行参数" value={argv} onChange={event => setArgv(event.target.value)} placeholder="每行一个参数，无需填写程序文件名" rows={2} /></details>{unit.kind === 'project' && project && <><label className="entrypoint">运行入口<select aria-label="项目运行入口" value={project.entrypoint} onChange={event => { setProject({ ...project, entrypoint: event.target.value }); setProjectDirty(true) }}>{Object.keys(project.files).filter(path => path.endsWith('.py')).map(path => <option key={path}>{path}</option>)}</select></label><div className="project-actions"><button disabled={busy} onClick={() => void validateProject()}><ListChecks size={15} />检查项目结构</button><button disabled={busy} onClick={() => void startRun('test')}><CheckCircle2 size={15} />运行 pytest</button><button onClick={() => void saveNow()}><Save size={15} />保存项目</button><button onClick={() => void exportProject()}><ArrowDownToLine size={15} />导出项目 ZIP</button></div>{projectCheck && <div className="project-check">{projectCheck.checks.map(item => <p key={item.name}>{item.passed ? <CheckCircle2 size={14} /> : <Circle size={14} />}<span><strong>{item.name}</strong>{item.message}</span></p>)}</div>}</>}</div>
              <div className="output-heading"><span><Terminal size={15} />运行结果</span>{run && <small className={run.status === 'completed' ? 'run-success' : ''}>{pollRetries ? '连接中断，正在重试' : runLabels[run.status] || run.status}{run.duration_ms !== null && ` · ${run.duration_ms} ms`}</small>}{isActiveRun(run) && <button onClick={() => void stopRun()}><Square size={12} fill="currentColor" />停止</button>}</div><div className="output-console" aria-live="polite">{!run ? <div className="console-empty"><Terminal size={24} /><span>{runPending ? '正在启动程序…' : '点击“运行代码”，看看程序会说什么。'}</span></div> : <>{run.stdout && <pre>{run.stdout}</pre>}{run.stderr && <><pre className="stderr">{run.stderr}</pre>{explainError(run.stderr) && <p className="error-explanation"><Lightbulb size={14} />{explainError(run.stderr)}</p>}</>}{!run.stdout && !run.stderr && <p className="console-note">{isActiveRun(run) ? '等待程序输出…' : '程序没有输出内容。'}</p>}{run.status === 'timeout' && <p className="console-note">程序已超过运行时限并停止。看看循环是否有结束条件。</p>}{run.status === 'output_limit' && <p className="console-note">输出过多，程序已停止。试着减少重复打印。</p>}</>}</div>
              {!!run?.artifacts?.length && <div className="run-artifacts"><strong>程序生成的文件</strong>{run.artifacts.map(file => <div key={file.name}><span>{file.name}<small>{(file.size / 1024).toFixed(1)} KB</small></span>{/^image\/(png|jpeg|webp|gif)$/.test(file.mime) && <button onClick={() => void openArtifact(file.name, true)}>预览</button>}<button onClick={() => void openArtifact(file.name)}><ArrowDownToLine size={13} />下载</button></div>)}<p>下载到电脑后可长期保留；本次运行文件会在关闭工作台后清理。</p>{artifactPreview && <figure><button aria-label="关闭图片预览" onClick={() => setArtifactPreview(null)}><X size={14} /></button><img src={artifactPreview.url} alt={artifactPreview.name} /><figcaption>{artifactPreview.name}</figcaption></figure>}</div>}<div className="code-footnote"><Lightbulb size={13} />错误是线索，尝试是进步。</div>
            </section>
          </div>
          <footer className="page-footer">课程结构依据哈佛 CS50P · 中文讲解与自主练习由本工作台提供<span>学习记录保存在你的电脑</span></footer>
        </>}
        {view === 'review' && <><section className="lesson-heading"><div><div className="eyebrow">MAKE MISTAKES. MAKE PROGRESS.</div><h1>错题复习</h1><p>把还没弄懂的地方，变成下一次的小进步。</p></div></section><section className="standalone-card">{state.mistakes.length ? state.mistakes.map(item => <article className="mistake-card" key={item.id}><span className={item.resolved ? 'resolved-label' : 'practice-label'}>{item.resolved ? '已解决' : '待复习'}</span><h3>{item.title}</h3><p>{item.message}</p><div><small>{course.units.find(u => u.id === item.unit_id)?.titleZh} · {new Date(item.created_at).toLocaleDateString('zh-CN')}</small><button className="outline small" onClick={async () => { await navigate(item.unit_id, item.exercise_id, item.code); setStep('practice') }}>回到练习<ArrowRight size={15} /></button></div></article>) : <div className="empty-state"><RotateCcw size={35} /><h3>这里会留下你的进步线索</h3><p>练习检查未通过时，会自动记录到这里。修正后再检查，通过就会标记为已解决。</p><button className="primary" onClick={() => { setView('learn'); setStep('practice') }}>去做一道练习<ArrowRight size={16} /></button></div>}</section></>}
        {view === 'settings' && <><section className="lesson-heading"><div><div className="eyebrow">YOUR PERSONAL LEARNING SPACE</div><h1>学习设置与备份</h1><p>保存自己的节奏，也保存每一次尝试。</p></div></section><div className="settings-grid"><section className="standalone-card settings-card"><BookOpen size={23} /><h2>我的学习计划</h2><p>零基础 · Windows 本机 · 每天 30–45 分钟</p><div className="settings-list"><span>课程范围<strong>Week 0–9 与最终项目</strong></span><span>学习方式<strong>视频 → 要点 → 示例 → 练习 → 复习</strong></span><span>学习辅助<strong>固定中文讲解与分级提示</strong></span><span>参考答案<strong>主动展开，默认折叠</strong></span></div></section><section className="standalone-card settings-card"><ArrowDownToLine size={23} /><h2>备份学习记录</h2><p>导出代码、笔记、进度与项目文件，保存一份属于你的学习档案。</p><div className="backup-actions"><button className="primary" onClick={() => void backup()}><ArrowDownToLine size={17} />导出备份</button><button className="outline" disabled={busy} onClick={() => restoreInput.current?.click()}><Upload size={17} />从备份恢复</button><input ref={restoreInput} type="file" accept=".json,application/json" hidden onChange={event => void restore(event.target.files?.[0])} /></div><p className="quiet-help">恢复前会请你确认。请先导出当前记录。</p></section><section className="standalone-card settings-card"><GraduationCap size={23} /><h2>课程与原始资料</h2><p>官方学习任务与本地自主练习分别记录。课程视频的实际播放取决于你的网络和视频网站。</p><div className="resource-links"><Link href="https://cs50.harvard.edu/python/">CS50P 官方课程</Link><Link href={course.userVideoEntry.url}>你提供的 B 站入口</Link></div><p className="quiet-help">每周可单独指定视频，B 站分集对应关系尚未核实。</p></section></div></>}
      </div>
    </main>
    {restoring && <div className="restore-overlay" role="status"><span className="spinner" /><strong>正在恢复学习记录…</strong><p>请稍候，恢复完成后会重新打开你的工作台。</p></div>}{menuOpen && <button aria-label="关闭导航" className="menu-backdrop" onClick={() => setMenuOpen(false)} />}
  </div>
}

function message(error: unknown) { return error instanceof Error ? error.message : '操作暂时无法完成，请重试。' }

function explainError(stderr: string): string | null {
  const hints: Record<string, string> = {
    EOFError: '程序需要输入，但输入已经结束。重新运行，在“实时输入”中为每次 input() 发送一行。',
    ValueError: '输入内容无法转换成需要的值。检查输入格式，例如 int() 需要整数文字。',
    NameError: 'Python 找不到这个名称。检查变量拼写，并确认先赋值、再使用。',
    TypeError: '数据类型或函数参数不符合要求。检查字符串与数字的区别，以及参数个数。',
    IndentationError: '代码的缩进不符合要求。检查冒号之后的代码块，保持同一层使用相同缩进。',
    SyntaxError: '这一行的写法不符合 Python 语法。根据报错行号检查冒号、引号和括号。',
    ModuleNotFoundError: '导入的模块还找不到。检查模块名称与项目文件名；需要第三方库时，先确认学习环境中已安装。',
  }
  const errors = [...stderr.matchAll(/\b(EOFError|ValueError|NameError|TypeError|IndentationError|SyntaxError|ModuleNotFoundError):/g)]
  const last = errors.at(-1)
  return last ? hints[last[1]] : null
}









