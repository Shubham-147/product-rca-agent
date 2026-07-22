import { useEffect, useMemo, useState } from 'react'

const API_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000/comparison'
const SYSTEMS = ['A', 'B', 'C']
const LABELS = {
  dead_screen: 'dead screen', checkout_latency: 'checkout latency', cold_start: 'cold start',
  crash_concentration: 'crash concentration', payment_failure: 'payment failure',
  innocent_dropoff: 'innocent dropoff', none: 'no fault',
}

const pct = value => `${((value || 0) * 100).toFixed(1)}%`
const compact = value => Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(value || 0)
const dollars = value => `$${Number(value || 0).toFixed(2)}`

function StatusDot({ ok, muted = false }) {
  return <span className={`status-dot ${muted ? 'muted' : ok ? 'ok' : 'bad'}`} />
}

function SystemBadge({ system }) {
  return <span className={`system-badge system-${system.toLowerCase()}`}>{system}</span>
}

function App() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [fetchedAt, setFetchedAt] = useState(null)
  const [selectedId, setSelectedId] = useState('inst_001')
  const [selectedSystem, setSelectedSystem] = useState('C')

  useEffect(() => {
    fetch(API_URL)
      .then(response => response.ok ? response.json() : Promise.reject(new Error(`API ${response.status}`)))
      .then(payload => { setData(payload); setFetchedAt(new Date()); setError('') })
      .catch(err => setError(`${err.message}. Start the comparison API on port 8000.`))
  }, [])

  const selected = useMemo(
    () => data?.cases.find(item => item.instance_id === selectedId) || data?.cases[0],
    [data, selectedId],
  )
  const aggregate = data?.aggregates.find(item => item.system === selectedSystem)

  if (error) return <StateScreen title="Comparison API unavailable" detail={error} />
  if (!data || !selected) return <StateScreen title="Loading investigation data" detail="Reading A/B/C suite manifests…" />

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand"><span className="brand-mark" /> <strong>Post Hoc</strong><span className="divider" /> <span>Investigation Workbench</span></div>
        <div className="top-actions">
          <span className="case-label">Case</span><code>{selected.instance_id}</code>
          <div className="system-tabs" aria-label="Select system">
            {SYSTEMS.map(system => <button key={system} className={selectedSystem === system ? 'active' : ''} onClick={() => setSelectedSystem(system)}>{system}</button>)}
          </div>
          <span className="fetched-pill" ><i/> As Per Latest data available</span>
        </div>
      </header>

      <aside className="case-library">
        <div className="section-heading"><span>CASE LIBRARY</span><span>{data.cases.length}</span></div>
        <div className="case-list">
          {data.cases.map(item => {
            const result = item.systems[selectedSystem]
            return <button key={item.instance_id} className={`case-item ${item.instance_id === selected.instance_id ? 'selected' : ''}`} onClick={() => setSelectedId(item.instance_id)}>
              <StatusDot ok={result.top1_correct} muted={Boolean(result.error)} />
              <code>{item.instance_id}</code>
              <span className="fault-chip">{LABELS[item.gold_fault] || item.gold_fault}</span>
            </button>
          })}
        </div>
        <div className="run-card">
          <div className="eyebrow">SYSTEM {selectedSystem} · FULL SUITE</div>
          <Metric label="top-1 accuracy" value={pct(aggregate.top1_accuracy)} />
          <Metric label="cohort F1" value={aggregate.cohort_f1_mean_faultcases.toFixed(3)} />
          <Metric label="mean latency" value={`${aggregate.mean_latency_s.toFixed(1)}s`} />
          <Metric label="estimated cost" value={dollars(aggregate.est_cost_usd)} accent />
        </div>
      </aside>

      <main className="workspace">
        <section className="overview-card">
          <div className="card-title"><div><strong>System comparison</strong><span> same 24 benchmark cases · {aggregate.model}</span></div><div className="legend"><i className="good" /> correct <i className="miss" /> miss</div></div>
          <div className="system-overview">
            {data.aggregates.map(item => <button key={item.system} className={`system-column ${selectedSystem === item.system ? 'selected' : ''}`} onClick={() => setSelectedSystem(item.system)}>
              <SystemBadge system={item.system} />
              <div className="big-score">{pct(item.top1_accuracy)}</div>
              <div className="bar"><span style={{ width: pct(item.top1_accuracy) }} /></div>
              <small>{item.errors} errors · {compact(item.total_tokens)} tokens</small>
            </button>)}
          </div>
        </section>

        <div className="investigation-title"><strong>Case comparison</strong><span>{LABELS[selected.gold_fault] || selected.gold_fault} · expected root cause</span></div>
        <section className="case-comparison">
          {SYSTEMS.map(system => {
            const result = selected.systems[system]
            return <article key={system} className={`result-card ${selectedSystem === system ? 'selected' : ''}`} onClick={() => setSelectedSystem(system)}>
              <div className="result-head"><SystemBadge system={system} /><span className={result.top1_correct ? 'outcome correct' : 'outcome'}>{result.top1_correct ? '✓ TOP-1 CORRECT' : '× MISSED'}</span></div>
              <div className="result-mechanism">{LABELS[result.top_pred] || result.top_pred || 'no prediction'}</div>
              <code className="cohort">{result.top_cohort || 'cohort unavailable'}</code>
              <div className="result-stats">
                <Metric label="cohort F1" value={Number(result.cohort_f1 || 0).toFixed(3)} />
                <Metric label="latency" value={`${result.latency_s.toFixed(1)}s`} />
                <Metric label="tool calls" value={result.n_tool_calls} />
              </div>
            </article>
          })}
        </section>

        <section className="analysis-panel">
          <div className="analysis-row"><span className="analysis-icon">⌁</span><div><b>ground_truth</b><small> planted benchmark label</small><p>{LABELS[selected.gold_fault] || selected.gold_fault}</p></div><span className="tag">{selected.has_fault ? 'FAULT' : 'TRAP'}</span></div>
          {SYSTEMS.map((system, index) => {
            const result = selected.systems[system]
            return <div className={`analysis-row ${selectedSystem === system ? 'focused' : ''}`} key={system}>
              <span className="analysis-icon"><SystemBadge system={system} /></span>
              <div><b>system_{system.toLowerCase()}</b><small> rank 1 prediction</small><p>{LABELS[result.top_pred] || result.top_pred || result.error}</p></div>
              <span className={`tag ${result.top1_correct ? 'survived' : 'rejected'}`}>{result.top1_correct ? 'VERIFIED' : index === 2 && result.top_pred === 'innocent_dropoff' ? 'FALSIFIED' : 'MISSED'}</span>
            </div>
          })}
        </section>
      </main>

      <aside className="inspector">
        <div className="section-heading"><span>INSPECTOR</span></div>
        <div className="inspector-title"><SystemBadge system={selectedSystem} /><strong>{selected.instance_id}</strong><span>individual result</span></div>
        <section className="inspector-block">
          <div className="eyebrow">PREDICTION</div>
          <h2>{LABELS[selected.systems[selectedSystem].top_pred] || selected.systems[selectedSystem].top_pred || 'No output'}</h2>
          <code className="cohort wide">{selected.systems[selectedSystem].top_cohort || '—'}</code>
        </section>
        <section className="score-grid">
          <Score label="Top-1" value={selected.systems[selectedSystem].top1_correct ? 'PASS' : 'FAIL'} good={selected.systems[selectedSystem].top1_correct} />
          <Score label="Cohort F1" value={Number(selected.systems[selectedSystem].cohort_f1 || 0).toFixed(3)} good={(selected.systems[selectedSystem].cohort_f1 || 0) >= .5} />
          <Score label="Recall@3" value={selected.systems[selectedSystem].recall_at_3 ? 'YES' : 'NO'} good={selected.systems[selectedSystem].recall_at_3} />
          <Score label="False positive" value={selected.systems[selectedSystem].false_positive ? 'YES' : 'NO'} good={!selected.systems[selectedSystem].false_positive} />
        </section>
        <section className="inspector-block">
          <div className="eyebrow">RUN TELEMETRY</div>
          <Metric label="input tokens" value={compact(selected.systems[selectedSystem].input_tokens)} />
          <Metric label="output tokens" value={compact(selected.systems[selectedSystem].output_tokens)} />
          <Metric label="tool calls" value={selected.systems[selectedSystem].n_tool_calls} />
          <Metric label="latency" value={`${selected.systems[selectedSystem].latency_s.toFixed(1)}s`} />
        </section>
        <section className="verdict-box">
          <div className="eyebrow">SCORER VERDICT</div>
          <strong>{selected.systems[selectedSystem].top1_correct ? 'Verified root cause' : 'Attribution did not clear the gate'}</strong>
          <p>Expected <code>{selected.gold_fault}</code>. Prediction must match the mechanism and clear cohort F1 ≥ 0.50.</p>
        </section>
      </aside>
    </div>
  )
}

function Metric({ label, value, accent = false }) {
  return <div className="metric"><span>{label}</span><strong className={accent ? 'accent' : ''}>{value}</strong></div>
}

function Score({ label, value, good }) {
  return <div className="score"><span>{label}</span><strong className={good ? 'good-text' : 'bad-text'}>{value}</strong></div>
}

function StateScreen({ title, detail }) {
  return <div className="state-screen"><span className="brand-mark" /><h1>{title}</h1><p>{detail}</p></div>
}

export default App
