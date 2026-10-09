import CodeMirror from '@uiw/react-codemirror'
import { python } from '@codemirror/lang-python'
import { oneDark } from '@codemirror/theme-one-dark'

const extensions = [python()]
export default function Editor({ value, onChange, filename = 'main.py' }: { value: string; onChange: (code: string) => void; filename?: string }) {
  return <CodeMirror aria-label={`${filename} 代码编辑器`} value={value} onChange={onChange} theme={oneDark} extensions={filename.endsWith('.py') ? extensions : []} height="340px" basicSetup={{ lineNumbers: true, foldGutter: true, highlightActiveLine: true, autocompletion: true, bracketMatching: true, indentOnInput: true }} />
}
