import { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  PenTool, Upload, FileText, Sparkles, Download, Copy, Send,
  Loader2, CheckCircle2, X, RefreshCw, Trash2, File as FileIcon
} from 'lucide-react';
import './App.css';

const API_URL = window.location.hostname === 'localhost'
  ? 'http://127.0.0.1:8000/api'
  : '/api';

// ─── Toast System ──────────────────────────────────────────
function useToast() {
  const [toasts, setToasts] = useState([]);
  const addToast = useCallback((message, type = 'info') => {
    const id = Date.now() + Math.random();
    setToasts(prev => [...prev, { id, message, type }]);
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 4000);
  }, []);
  return { toasts, addToast };
}

function ToastContainer({ toasts }) {
  return (
    <div style={{ position: 'fixed', top: 20, right: 20, zIndex: 9999, display: 'flex', flexDirection: 'column', gap: 8 }}>
      <AnimatePresence>
        {toasts.map(t => (
          <motion.div
            key={t.id}
            initial={{ opacity: 0, x: 80, scale: 0.95 }}
            animate={{ opacity: 1, x: 0, scale: 1 }}
            exit={{ opacity: 0, x: 80, scale: 0.95 }}
            transition={{ duration: 0.25 }}
            style={{
              padding: '12px 20px', borderRadius: 12, fontSize: '0.85rem', fontWeight: 500,
              backdropFilter: 'blur(20px)', border: '1px solid rgba(255,255,255,0.1)',
              boxShadow: '0 8px 32px rgba(0,0,0,0.2)', maxWidth: 360,
              background: t.type === 'error' ? 'rgba(239,68,68,0.9)' :
                          t.type === 'success' ? 'rgba(34,197,94,0.9)' : 'rgba(99,102,241,0.9)',
              color: 'white',
            }}
          >
            {t.message}
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
// MAIN APP — Single page, no auth, no navigation
// ═══════════════════════════════════════════════════════════
export default function App() {
  const [sessionId] = useState(() => crypto.randomUUID());
  const { toasts, addToast } = useToast();

  // ── Upload state ──
  const [intakeFiles, setIntakeFiles] = useState([]);
  const [sampleFile, setSampleFile] = useState(null);
  const [uploadingIntake, setUploadingIntake] = useState(false);
  const [uploadingSample, setUploadingSample] = useState(false);
  const [intakeDragActive, setIntakeDragActive] = useState(false);
  const [sampleDragActive, setSampleDragActive] = useState(false);
  const intakeInputRef = useRef(null);
  const sampleInputRef = useRef(null);

  // ── Report state ──
  const [generating, setGenerating] = useState(false);
  const [reportText, setReportText] = useState(null);
  const [refining, setRefining] = useState(false);
  const [refineInput, setRefineInput] = useState('');

  // ── Prevent browser default drag behavior ──
  useEffect(() => {
    const prevent = (e) => { e.preventDefault(); e.stopPropagation(); };
    window.addEventListener('dragover', prevent);
    window.addEventListener('drop', prevent);
    return () => {
      window.removeEventListener('dragover', prevent);
      window.removeEventListener('drop', prevent);
    };
  }, []);

  // ── API helper ──
  async function apiFetch(path, options = {}) {
    const isFormData = options.body instanceof FormData;
    const headers = { 'X-Session-ID': sessionId };
    if (!isFormData) headers['Content-Type'] = 'application/json';

    const res = await fetch(`${API_URL}${path}`, {
      ...options,
      headers: { ...headers, ...(options.headers || {}) },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Request failed' }));
      throw new Error(err.detail || 'Request failed');
    }
    return res.json();
  }

  // ── Intake Upload ──
  async function handleIntakeUpload(files) {
    if (!files.length) return;
    setUploadingIntake(true);
    try {
      const formData = new FormData();
      for (const f of files) formData.append('files', f);
      const data = await apiFetch('/upload-intake', { method: 'POST', body: formData });
      const newFiles = (data.files || []).map(f => ({ name: f.name, chars: f.chars }));
      setIntakeFiles(prev => [...prev, ...newFiles]);
      addToast(`${files.length} file${files.length > 1 ? 's' : ''} uploaded`, 'success');
    } catch (err) {
      addToast('Upload failed: ' + err.message, 'error');
    } finally {
      setUploadingIntake(false);
    }
  }

  function handleIntakeDrop(e) {
    e.preventDefault(); e.stopPropagation();
    setIntakeDragActive(false);
    const files = Array.from(e.dataTransfer.files).filter(f =>
      /\.(pdf|docx?|jpe?g|png|tiff?|bmp|webp|heic)$/i.test(f.name)
    );
    if (files.length) handleIntakeUpload(files);
  }

  function handleIntakeSelect(e) {
    const files = Array.from(e.target.files || []);
    if (files.length) handleIntakeUpload(files);
    e.target.value = '';
  }

  // ── Sample Upload ──
  async function handleSampleUpload(files) {
    const file = files[0];
    if (!file) return;
    setUploadingSample(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const data = await apiFetch('/upload-sample', { method: 'POST', body: formData });
      setSampleFile({ name: data.filename || file.name, chars: data.chars || 0 });
      addToast('Writing style sample uploaded', 'success');
    } catch (err) {
      addToast('Upload failed: ' + err.message, 'error');
    } finally {
      setUploadingSample(false);
    }
  }

  function handleSampleDrop(e) {
    e.preventDefault(); e.stopPropagation();
    setSampleDragActive(false);
    const files = Array.from(e.dataTransfer.files).filter(f =>
      /\.(pdf|docx?|doc)$/i.test(f.name)
    );
    if (files.length) handleSampleUpload(files);
  }

  function handleSampleSelect(e) {
    const files = Array.from(e.target.files || []);
    if (files.length) handleSampleUpload(files);
    e.target.value = '';
  }

  // ── Generate ──
  async function handleGenerate() {
    setGenerating(true);
    setReportText(null);
    try {
      const data = await apiFetch('/generate', { method: 'POST' });
      setReportText(data.report_text || 'Report generated.');
      addToast('Report generated successfully!', 'success');
    } catch (err) {
      addToast('Generation failed: ' + err.message, 'error');
    } finally {
      setGenerating(false);
    }
  }

  // ── Refine ──
  async function handleRefine() {
    if (!refineInput.trim()) return;
    setRefining(true);
    try {
      const data = await apiFetch('/refine', {
        method: 'POST',
        body: JSON.stringify({ instructions: refineInput.trim() }),
      });
      setReportText(data.report_text || reportText);
      setRefineInput('');
      addToast('Report refined successfully!', 'success');
    } catch (err) {
      addToast('Refinement failed: ' + err.message, 'error');
    } finally {
      setRefining(false);
    }
  }

  // ── Downloads ──
  function downloadDocx() {
    window.open(`${API_URL}/download/docx?session=${sessionId}`, '_blank');
    addToast('Downloading DOCX...', 'success');
  }
  function downloadPdf() {
    window.open(`${API_URL}/download/pdf?session=${sessionId}`, '_blank');
    addToast('Downloading PDF...', 'success');
  }
  function copyReport() {
    if (reportText) {
      navigator.clipboard.writeText(reportText);
      addToast('Report copied to clipboard', 'success');
    }
  }

  // ── Start Over ──
  function startOver() {
    setIntakeFiles([]);
    setSampleFile(null);
    setReportText(null);
    setRefineInput('');
    addToast('Ready for a new report', 'info');
  }

  const canGenerate = intakeFiles.length > 0 && sampleFile !== null;

  return (
    <>
      <ToastContainer toasts={toasts} />

      <div style={{ minHeight: '100vh', padding: '0 24px 60px' }}>
        {/* ── Header ── */}
        <header style={{ textAlign: 'center', padding: '48px 24px 12px' }}>
          <motion.div
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
          >
            <motion.div
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              transition={{ delay: 0.15, type: 'spring', stiffness: 200, damping: 15 }}
              style={{
                width: 56, height: 56, borderRadius: 16, display: 'inline-flex',
                alignItems: 'center', justifyContent: 'center', marginBottom: 16,
                background: 'linear-gradient(135deg, var(--primary) 0%, var(--accent) 100%)',
                color: 'white', boxShadow: '0 8px 30px rgba(99,102,241,0.35)',
              }}
            >
              <PenTool size={26} />
            </motion.div>
            <h1 style={{
              margin: '0 0 6px', fontSize: '2rem', fontWeight: 700,
              background: 'linear-gradient(135deg, var(--primary), var(--accent))',
              WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
            }}>
              PenStrokes AI
            </h1>
            <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: '0.95rem' }}>
              Psychological Report Synthesis
            </p>
          </motion.div>
        </header>

        <div style={{ maxWidth: 900, margin: '0 auto' }}>
          {/* ── Upload Zones ── */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2, duration: 0.5 }}
            style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginBottom: 28 }}
          >
            {/* Intake Forms */}
            <div className="glass-panel" style={{ padding: 24 }}>
              <h3 style={{ margin: '0 0 16px', fontSize: '1rem', fontWeight: 600, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 8 }}>
                <div style={{ width: 28, height: 28, borderRadius: 8, background: 'rgba(99,102,241,0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <FileText size={14} style={{ color: 'var(--primary)' }} />
                </div>
                Intake Forms
              </h3>

              <div
                className={`upload-zone ${intakeDragActive ? 'upload-zone-active' : ''}`}
                onDragEnter={(e) => { e.preventDefault(); e.stopPropagation(); setIntakeDragActive(true); }}
                onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); }}
                onDragLeave={(e) => { e.preventDefault(); e.stopPropagation(); setIntakeDragActive(false); }}
                onDrop={handleIntakeDrop}
                onClick={() => intakeInputRef.current?.click()}
              >
                <div className="upload-zone-icon">
                  {uploadingIntake ? <Loader2 size={22} className="spin" /> : <Upload size={22} />}
                </div>
                <p className="upload-zone-text">
                  {intakeDragActive ? 'Drop files here' : uploadingIntake ? 'Uploading...' : 'Drag & drop or click to browse'}
                </p>
                <p className="upload-zone-hint">PDFs, DOCX, images, scans - handwritten OK</p>
              </div>
              <input
                ref={intakeInputRef}
                type="file"
                accept=".pdf,.docx,.doc,.jpg,.jpeg,.png,.tiff,.tif,.bmp,.webp,.heic"
                multiple
                style={{ display: 'none' }}
                onChange={handleIntakeSelect}
              />

              {/* File list */}
              <AnimatePresence>
                {intakeFiles.length > 0 && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: 'auto' }}
                    exit={{ opacity: 0, height: 0 }}
                    style={{ marginTop: 12 }}
                  >
                    {intakeFiles.map((f, i) => (
                      <motion.div
                        key={f.name + i}
                        initial={{ opacity: 0, x: -10 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: i * 0.05 }}
                        style={{
                          display: 'flex', alignItems: 'center', gap: 8, padding: '6px 0',
                          fontSize: '0.82rem', color: 'var(--text-secondary)',
                        }}
                      >
                        <CheckCircle2 size={14} style={{ color: '#34d399', flexShrink: 0 }} />
                        <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.name}</span>
                        <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem', flexShrink: 0 }}>
                          {f.chars?.toLocaleString() || '?'} chars
                        </span>
                      </motion.div>
                    ))}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>

            {/* Writing Style Sample */}
            <div className="glass-panel" style={{ padding: 24 }}>
              <h3 style={{ margin: '0 0 16px', fontSize: '1rem', fontWeight: 600, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 8 }}>
                <div style={{ width: 28, height: 28, borderRadius: 8, background: 'rgba(168,85,247,0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <FileIcon size={14} style={{ color: 'var(--accent)' }} />
                </div>
                Writing Style Sample
              </h3>

              <div
                className={`upload-zone ${sampleDragActive ? 'upload-zone-active' : ''}`}
                onDragEnter={(e) => { e.preventDefault(); e.stopPropagation(); setSampleDragActive(true); }}
                onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); }}
                onDragLeave={(e) => { e.preventDefault(); e.stopPropagation(); setSampleDragActive(false); }}
                onDrop={handleSampleDrop}
                onClick={() => !sampleFile && sampleInputRef.current?.click()}
                style={sampleFile ? { cursor: 'default' } : {}}
              >
                {sampleFile ? (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <CheckCircle2 size={18} style={{ color: '#34d399' }} />
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: '0.85rem', fontWeight: 500, color: 'var(--text-primary)' }}>{sampleFile.name}</div>
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{sampleFile.chars?.toLocaleString() || '?'} characters extracted</div>
                    </div>
                    <button
                      onClick={(e) => { e.stopPropagation(); setSampleFile(null); }}
                      style={{
                        background: 'rgba(239,68,68,0.1)', border: 'none', borderRadius: 6,
                        padding: '4px 8px', cursor: 'pointer', color: '#ef4444', display: 'flex',
                        alignItems: 'center', gap: 4, fontSize: '0.75rem',
                      }}
                    >
                      <X size={12} /> Remove
                    </button>
                  </div>
                ) : (
                  <>
                    <div className="upload-zone-icon">
                      {uploadingSample ? <Loader2 size={22} className="spin" /> : <Upload size={22} />}
                    </div>
                    <p className="upload-zone-text">
                      {sampleDragActive ? 'Drop file here' : uploadingSample ? 'Uploading...' : 'Upload a sample report'}
                    </p>
                    <p className="upload-zone-hint">This defines the writing style & structure</p>
                  </>
                )}
              </div>
              <input
                ref={sampleInputRef}
                type="file"
                accept=".pdf,.docx,.doc"
                style={{ display: 'none' }}
                onChange={handleSampleSelect}
              />
            </div>
          </motion.div>

          {/* ── Generate Button ── */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.35 }}
            style={{ textAlign: 'center', marginBottom: 28 }}
          >
            <button
              className="generate-btn"
              onClick={handleGenerate}
              disabled={!canGenerate || generating}
              style={{ padding: '14px 36px', fontSize: '1rem' }}
            >
              {generating ? <Loader2 size={20} className="spin" /> : <Sparkles size={20} />}
              {generating ? 'Generating Report...' : 'Generate Report'}
            </button>
            {!canGenerate && (
              <p style={{ margin: '10px 0 0', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                Upload intake forms and a writing style sample to begin
              </p>
            )}
          </motion.div>

          {/* ── Report Preview ── */}
          <AnimatePresence>
            {reportText && (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 20 }}
                transition={{ duration: 0.4 }}
                className="glass-panel"
                style={{ padding: 28, marginBottom: 28 }}
              >
                {/* Header */}
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <CheckCircle2 size={18} style={{ color: '#34d399' }} />
                    <span style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: '1rem' }}>
                      Report Generated
                    </span>
                  </div>
                  <button
                    onClick={startOver}
                    style={{
                      background: 'rgba(99,102,241,0.1)', border: 'none', borderRadius: 8,
                      padding: '6px 14px', cursor: 'pointer', color: 'var(--primary)',
                      display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.8rem', fontWeight: 500,
                    }}
                  >
                    <RefreshCw size={13} /> Start Over
                  </button>
                </div>

                {/* Report text */}
                <div style={{
                  maxHeight: 500, overflowY: 'auto', padding: '24px 28px',
                  background: 'rgba(255,255,255,0.03)', borderRadius: 12,
                  border: '1px solid rgba(255,255,255,0.06)',
                  fontSize: '0.88rem', lineHeight: 1.7, color: 'var(--text-secondary)',
                  whiteSpace: 'pre-wrap', fontFamily: "'Georgia', serif",
                }}>
                  {reportText}
                </div>

                {/* Refine bar */}
                <div style={{
                  display: 'flex', gap: 10, marginTop: 20, alignItems: 'center',
                  background: 'rgba(255,255,255,0.03)', borderRadius: 12,
                  border: '1px solid rgba(255,255,255,0.08)', padding: '8px 8px 8px 16px',
                }}>
                  <input
                    className="modern-input"
                    type="text"
                    placeholder="e.g. Make it more formal, add detail to the cognitive section..."
                    value={refineInput}
                    onChange={(e) => setRefineInput(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleRefine()}
                    disabled={refining}
                    style={{
                      flex: 1, border: 'none', background: 'transparent',
                      padding: '8px 0', fontSize: '0.85rem', outline: 'none',
                      color: 'var(--text-primary)',
                    }}
                  />
                  <button
                    className="generate-btn"
                    onClick={handleRefine}
                    disabled={refining || !refineInput.trim()}
                    style={{ padding: '8px 16px', fontSize: '0.82rem', borderRadius: 10, flexShrink: 0 }}
                  >
                    {refining ? <Loader2 size={14} className="spin" /> : <Send size={14} />}
                    {refining ? 'Refining...' : 'Refine'}
                  </button>
                </div>

                {/* Action buttons */}
                <div style={{ display: 'flex', gap: 10, marginTop: 16, flexWrap: 'wrap' }}>
                  <button className="secondary-btn" onClick={copyReport}>
                    <Copy size={14} /> Copy to Clipboard
                  </button>
                  <button className="secondary-btn" onClick={downloadDocx}>
                    <Download size={14} /> Download DOCX
                  </button>
                  <button className="secondary-btn" onClick={downloadPdf}>
                    <Download size={14} /> Download PDF
                  </button>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* ── Footer ── */}
        <footer style={{ textAlign: 'center', padding: '32px 24px', color: 'var(--text-muted)', fontSize: '0.78rem' }}>
          Files are processed in-memory and never stored permanently
        </footer>
      </div>
    </>
  );
}
