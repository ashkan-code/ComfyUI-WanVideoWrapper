import { useEffect, useRef, useState } from 'react'

const BOOT = [
  'Initializing Web3 protocol...',
  'Loading Ethereum providers...',
  'Establishing secure channel...',
  'Verifying cryptographic keys...',
  'All systems operational',
]

export function Intro({ onDone }: { onDone: () => void }) {
  const [step, setStep]         = useState(0)
  const [logoIn, setLogoIn]     = useState(false)
  const [exiting, setExiting]   = useState(false)
  const onDoneRef               = useRef(onDone)
  onDoneRef.current             = onDone

  useEffect(() => {
    const t0 = setTimeout(() => setLogoIn(true), 200)
    const timers = BOOT.map((_, i) =>
      setTimeout(() => setStep(i + 1), 700 + i * 480)
    )
    const tExit = setTimeout(() => {
      setExiting(true)
      setTimeout(() => onDoneRef.current(), 750)
    }, 700 + BOOT.length * 480 + 500)

    return () => { clearTimeout(t0); timers.forEach(clearTimeout); clearTimeout(tExit) }
  }, [])

  const progress = Math.round((step / BOOT.length) * 100)

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 9999,
      background: '#020408',
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      transition: 'opacity .75s ease, transform .75s ease',
      opacity: exiting ? 0 : 1,
      transform: exiting ? 'scale(1.04)' : 'scale(1)',
    }}>
      {/* Animated grid */}
      <div className="absolute inset-0 grid-bg pointer-events-none" style={{ opacity: .6 }} />

      {/* Top glow */}
      <div style={{ position: 'absolute', top: 0, left: '50%', transform: 'translateX(-50%)', width: 700, height: 350,
        background: 'radial-gradient(ellipse, rgba(0,212,255,.07) 0%, transparent 65%)', pointerEvents: 'none' }} />
      <div style={{ position: 'absolute', bottom: 0, right: 0, width: 400, height: 400,
        background: 'radial-gradient(circle, rgba(147,51,234,.06) 0%, transparent 70%)', pointerEvents: 'none' }} />

      {/* Logo */}
      <div style={{
        transition: 'all 1s cubic-bezier(.22,1,.36,1)',
        opacity: logoIn ? 1 : 0,
        transform: logoIn ? 'scale(1) translateY(0)' : 'scale(.7) translateY(30px)',
        marginBottom: 32, display: 'flex', flexDirection: 'column', alignItems: 'center',
      }}>
        <div style={{ position: 'relative', marginBottom: 20 }}>
          <div style={{
            width: 88, height: 88, borderRadius: 26,
            background: 'linear-gradient(135deg, #0ea5e9, #7c3aed)',
            boxShadow: '0 0 80px rgba(14,165,233,.5), 0 0 160px rgba(124,58,237,.25)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 40, animation: 'float 3s ease-in-out infinite',
          }}>⟠</div>
          {/* Ripple rings */}
          {[0, 1, 2].map(i => (
            <div key={i} style={{
              position: 'absolute', inset: -12 - i * 12, borderRadius: 38 + i * 12,
              border: `1px solid rgba(0,212,255,${.3 - i * .08})`,
              animation: `ripple 2.5s ease-out ${i * .5}s infinite`,
            }} />
          ))}
        </div>
        <h1 style={{ fontSize: 32, fontWeight: 900, color: 'white', letterSpacing: '.04em', marginBottom: 4, textAlign: 'center' }}>
          Web3 Unified Wallet
        </h1>
        <p style={{ fontSize: 11, color: '#0d2030', letterSpacing: '.25em', textTransform: 'uppercase', fontWeight: 600 }}>
          AI · Multi-Chain · Non-Custodial
        </p>
      </div>

      {/* Terminal window */}
      <div style={{
        width: 500, maxWidth: '92vw',
        background: 'rgba(0,0,0,.6)',
        border: '1px solid rgba(0,212,255,.12)',
        borderRadius: 18,
        overflow: 'hidden',
        boxShadow: '0 0 60px rgba(0,212,255,.06)',
        backdropFilter: 'blur(20px)',
      }}>
        {/* Terminal title bar */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '10px 16px',
          background: 'rgba(0,212,255,.03)', borderBottom: '1px solid rgba(0,212,255,.06)' }}>
          {['#ff5f57','#febc2e','#28c840'].map((c, i) => (
            <div key={i} style={{ width: 10, height: 10, borderRadius: '50%', background: c }} />
          ))}
          <span style={{ marginLeft: 8, fontSize: 10, color: '#0d2030', letterSpacing: '.15em',
            fontFamily: 'monospace', textTransform: 'uppercase' }}>
            SYSTEM BOOT — web3-unified-wallet
          </span>
        </div>

        {/* Terminal body */}
        <div style={{ padding: '16px 20px', minHeight: 170, position: 'relative' }} className="scan-container">
          <div className="scan-line" style={{ opacity: .4 }} />
          {BOOT.slice(0, step).map((line, i) => (
            <div key={i} className="animate-slideUp"
              style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8,
                fontFamily: "'JetBrains Mono', monospace", fontSize: 12,
                color: i === step - 1 ? '#00d4ff' : '#1e3a4a',
                transition: 'color .4s',
              }}>
              <span style={{ fontSize: 10, minWidth: 14, color: i < step - 1 ? '#00ff88' : '#00d4ff' }}>
                {i < step - 1 ? '✓' : '▶'}
              </span>
              <span>{line}</span>
              {i === step - 1 && step < BOOT.length && (
                <span style={{ marginLeft: 2, animation: 'glowPulse .7s ease-in-out infinite', color: '#00d4ff' }}>_</span>
              )}
            </div>
          ))}
          {step === 0 && (
            <span style={{ fontFamily: 'monospace', color: '#00d4ff', animation: 'glowPulse .7s ease-in-out infinite' }}>_</span>
          )}
        </div>

        {/* Progress bar */}
        {step > 0 && (
          <div style={{ padding: '0 20px 16px' }}>
            <div style={{ height: 2, background: 'rgba(0,212,255,.08)', borderRadius: 2 }}>
              <div style={{
                height: '100%', borderRadius: 2,
                background: 'linear-gradient(90deg, #00d4ff, #7c3aed)',
                boxShadow: '0 0 10px rgba(0,212,255,.5)',
                width: `${progress}%`,
                transition: 'width .5s cubic-bezier(.22,1,.36,1)',
              }} />
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 5 }}>
              <span style={{ fontSize: 9, color: '#0d2030', fontFamily: 'monospace', letterSpacing: '.12em' }}>LOADING</span>
              <span style={{ fontSize: 9, color: '#00d4ff', fontFamily: 'monospace' }}>{progress}%</span>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
