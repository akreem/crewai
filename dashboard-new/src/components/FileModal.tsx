import { useState, useEffect } from 'react'
import { fetchJSON } from '../lib/api'
import './FileModal.css'

interface Props {
  filePath: string | null
  onClose: () => void
}

export default function FileModal({ filePath, onClose }: Props) {
  const [content, setContent] = useState('Loading...')

  useEffect(() => {
    if (!filePath) return
    setContent('Loading...')
    fetchJSON<{ content: string }>(`/workspace/files/${encodeURIComponent(filePath)}`)
      .then(d => setContent(d.content))
      .catch(() => setContent('Error loading file'))
  }, [filePath])

  if (!filePath) return null

  return (
    <div className="modal-overlay active" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <span>{filePath.split('/').pop()}</span>
          <button className="modal-close" onClick={onClose}>&times;</button>
        </div>
        <div className="modal-body">{content}</div>
      </div>
    </div>
  )
}
