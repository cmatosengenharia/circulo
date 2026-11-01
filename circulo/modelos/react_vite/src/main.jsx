import React from 'react'
import { createRoot } from 'react-dom/client'
import { saudacao } from './saudacao.js'

createRoot(document.getElementById('root')).render(<h1>{saudacao('mundo')}</h1>)
