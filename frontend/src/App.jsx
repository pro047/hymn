import { useEffect, useMemo, useState } from 'react'
import ScoreUploadModal from './components/ScoreUploadModal'
import './App.css'

function App() {
  const [activeTab, setActiveTab] = useState('scores')
  const [scores, setScores] = useState([])
  const [error, setError] = useState('')
  const [isUploadOpen, setIsUploadOpen] = useState(false)
  const [isUploading, setIsUploading] = useState(false)
  const apiBase = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

  const tabs = [
    { id: 'scores', label: '악보' },
    { id: 'weeks', label: '주차' },
    { id: 'uploads', label: '업로드' },
    { id: 'settings', label: '설정' },
  ]

  const weekSummaries = useMemo(() => {
    const uniqueWeeks = new Map()
    scores.forEach((score) => {
      if (!uniqueWeeks.has(score.week_of)) {
        uniqueWeeks.set(score.week_of, score)
      }
    })
    return Array.from(uniqueWeeks.values()).slice(0, 3)
  }, [scores])

  const fetchScores = async () => {
    try {
      const response = await fetch(`${apiBase}/scores`)
      if (!response.ok) {
        throw new Error('악보 목록을 불러오지 못했습니다.')
      }
      const data = await response.json()
      setScores(data)
      setError('')
    } catch (err) {
      setError(err.message)
    }
  }

  useEffect(() => {
    fetchScores()
  }, [])

  const createScoreWithUpload = async ({ title, churchId, weekOf, file }) => {
    setIsUploading(true)
    try {
      const response = await fetch(`${apiBase}/scores`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title,
          church_id: churchId,
          week_of: weekOf,
          storage_type: 's3',
          filename: file.name,
          content_type: file.type,
        }),
      })
      if (!response.ok) {
        throw new Error('악보 생성에 실패했습니다.')
      }
      const data = await response.json()
      const uploadResponse = await fetch(data.upload_url, {
        method: 'PUT',
        headers: { 'Content-Type': file.type },
        body: file,
      })
      if (!uploadResponse.ok) {
        throw new Error('S3 업로드에 실패했습니다.')
      }
      setIsUploadOpen(false)
      await fetchScores()
    } catch (err) {
      setError(err.message)
    } finally {
      setIsUploading(false)
    }
  }

  const updateScore = async (scoreId) => {
    const title = window.prompt('새 제목을 입력하세요.')
    if (!title) return
    try {
      const response = await fetch(`${apiBase}/scores/${scoreId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
      })
      if (!response.ok) {
        throw new Error('악보 수정에 실패했습니다.')
      }
      await fetchScores()
    } catch (err) {
      setError(err.message)
    }
  }

  const deleteScore = async (scoreId) => {
    const confirmed = window.confirm('정말 삭제할까요?')
    if (!confirmed) return
    try {
      const response = await fetch(`${apiBase}/scores/${scoreId}`, {
        method: 'DELETE',
      })
      if (!response.ok) {
        throw new Error('악보 삭제에 실패했습니다.')
      }
      await fetchScores()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <div className="brand-mark">H</div>
          <div>
            <p className="brand-kicker">Hymn 콘솔</p>
            <h1 className="brand-title">주간 콘티를 빠르게 정리합니다.</h1>
          </div>
        </div>
        <div className="header-actions">
          <button className="ghost-button" type="button">
            주차 만들기
          </button>
          <button className="primary-button" type="button" onClick={() => setIsUploadOpen(true)}>
            악보 업로드
          </button>
        </div>
      </header>

      <section className="tabs">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={`tab ${activeTab === tab.id ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </section>

      <main className="content">
        <section className="hero-card">
          <div>
            <p className="pill">이번 주</p>
            <h2>주일 2부 - 1월 19일</h2>
            <p className="muted">
              흐름을 정리하세요: 시작, 응답, 헌금, 성찬.
            </p>
          </div>
          <div className="hero-meta">
            <div>
              <span className="meta-label">리더</span>
              <strong>김민지</strong>
            </div>
            <div>
              <span className="meta-label">총 곡 수</span>
              <strong>5</strong>
            </div>
            <div>
              <span className="meta-label">상태</span>
              <strong>초안</strong>
            </div>
          </div>
        </section>

        {error ? <p className="error">{error}</p> : null}

        <section className="grid">
          <div className="panel">
            <div className="panel-header">
              <h3>다가오는 주차</h3>
              <span className="panel-action">달력 보기</span>
            </div>
            <ul className="list">
              {weekSummaries.length === 0 ? (
                <li>
                  <span>등록된 주차가 없습니다.</span>
                  <span className="tag">대기</span>
                </li>
              ) : (
                weekSummaries.map((item) => (
                  <li key={item.week_of}>
                    <span>
                      {item.week_of} - {item.title}
                    </span>
                    <span className="tag">초안</span>
                  </li>
                ))
              )}
            </ul>
          </div>

          <div className="panel">
            <div className="panel-header">
              <h3>최근 악보</h3>
              <span className="panel-action">라이브러리</span>
            </div>
            <ul className="list">
              {scores.length === 0 ? (
                <li>
                  <span>등록된 악보가 없습니다.</span>
                  <span className="tag">대기</span>
                </li>
              ) : (
                scores.slice(0, 3).map((score) => (
                  <li key={score.id}>
                    <span>{score.title}</span>
                    <span className="tag">등록</span>
                  </li>
                ))
              )}
            </ul>
          </div>
        </section>

        <section className="stage">
          <div className="stage-header">
            <h3>콘티</h3>
            <div className="stage-actions">
              <button className="ghost-button" type="button">
                섞기
              </button>
              <button className="primary-button" type="button">
                발행
              </button>
            </div>
          </div>
          <div className="stage-list">
            {scores.length === 0 ? (
              <div className="stage-item">
                <span className="stage-index">-</span>
                <span>먼저 악보를 등록하세요.</span>
                <span className="stage-meta">-</span>
              </div>
            ) : (
              scores.slice(0, 5).map((score, index) => (
                <div
                  key={score.id}
                  className="stage-item"
                  style={{ animationDelay: `${index * 80}ms` }}
                >
                  <span className="stage-index">{index + 1}</span>
                  <button type="button" className="stage-link" onClick={() => updateScore(score.id)}>
                    {score.title}
                  </button>
                  <div className="stage-actions-inline">
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => updateScore(score.id)}
                    >
                      수정
                    </button>
                    <button
                      type="button"
                      className="link-button danger"
                      onClick={() => deleteScore(score.id)}
                    >
                      삭제
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        </section>
      </main>
      <ScoreUploadModal
        open={isUploadOpen}
        onClose={() => setIsUploadOpen(false)}
        onSubmit={createScoreWithUpload}
        loading={isUploading}
      />
    </div>
  )
}

export default App
