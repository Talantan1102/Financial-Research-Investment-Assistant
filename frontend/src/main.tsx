import '@ant-design/v5-patch-for-react-19'
import 'normalize.css'
import 'highlight.js/styles/github.css'
import 'katex/dist/katex.min.css'
import { createRoot } from 'react-dom/client'
import './antd.scss'
import './styles/tokens.css'
import App from './App.tsx'
import './index.css'

createRoot(document.getElementById('root')!).render(<App />)
