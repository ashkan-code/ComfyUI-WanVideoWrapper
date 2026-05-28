import { useEffect, useState } from 'react'
import { WalletState, WalletActions } from '../hooks/useWallet'

interface Props { wallet: WalletState & WalletActions }

const PARTICLES = Array.from({ length: 20 }, (_, i) => ({
  id: i,
  left: Math.random() * 100,
  top:  Math.random() * 100,
  delay: Math.random() * 4,
  size: Math.random() * 2 + 1,
  dur: Math.random() * 3 + 2,
}))

export function WalletConnect({ wallet }: Props) {
  const [mounted, setMounted] = useState(false)
  useEffect(() => { setTimeout(() => setMounted(true), 50) }, [])

  return (
    <div className="min-h-screen flex items-center justify-center relative overflow-hidden noise grid-bg"
         style={{ background: 'var(--bg)' }}>

      {/* Ambient glows */}
      <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[900px] h-[400px] pointer-events-none"
           style={{ background: 'radial-gradient(ellipse, rgba(0,212,255,.06) 0%, transparent 70%)', transform: 'translateX(-50%)' }} />
      <div className="absolute bottom-0 right-0 w-96 h-96 pointer-events-none"
           style={{ background: 'radial-gradient(circle, rgba(147,51,234,.07) 0%, transparent 70%)' }} />

      {/* Floating particles */}
      {PARTICLES.map(p => (
        <div key={p.id} className="absolute rounded-full pointer-events-none animate-glow"
             style={{
               left: `${p.left}%`, top: `${p.top}%`,
               width: p.size, height: p.size,
               background: p.id % 3 === 0 ? '#00d4ff' : p.id % 3 === 1 ? '#9333ea' : '#00ff88',
               boxShadow: `0 0 ${p.size * 4}px currentColor`,
               animationDelay: `${p.delay}s`,
               animationDuration: `${p.dur}s`,
             }} />
      ))}

      {/* Main card */}
      <div className={`relative w-full max-w-[400px] px-4 transition-all duration-700 ${mounted ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-8'}`}
           style={{ transform: mounted ? 'translateY(0)' : 'translateY(32px)' }}>

        {/* Logo */}
        <div className="flex justify-center mb-8">
          <div className="relative animate-float">
            <div className="w-24 h-24 rounded-3xl flex items-center justify-center relative"
                 style={{ background: 'linear-gradient(135deg, #0ea5e9, #7c3aed, #0ea5e9)', backgroundSize: '200%', animation: 'borderFlow 4s linear infinite', boxShadow: '0 0 60px rgba(14,165,233,.4), 0 0 120px rgba(124,58,237,.2)' }}>
              <span className="text-5xl">⟠</span>
            </div>
            {/* Ping rings */}
            <div className="absolute inset-0 rounded-3xl" style={{ animation: 'ripple 2s ease-out infinite', border: '1px solid rgba(0,212,255,.3)' }} />
            <div className="absolute inset-0 rounded-3xl" style={{ animation: 'ripple 2s ease-out .6s infinite', border: '1px solid rgba(147,51,234,.2)' }} />
          </div>
        </div>

        <h1 className="text-center text-4xl font-black mb-1 text-white">
          Web3 Unified
          <span className="block text-neon-cyan">Wallet</span>
        </h1>
        <p className="text-center text-sm mb-8" style={{ color: '#1e3a4a' }}>
          AI-powered · Multi-chain · Non-custodial
        </p>

        {/* Card */}
        <div className="neon-card p-6 scan-container">
          <div className="scan-line" />

          {wallet.error && (
            <div className="badge-red rounded-xl p-3 mb-5 flex gap-2 text-sm animate-slideUp">
              <span>⚠</span><span>{wallet.error}</span>
            </div>
          )}

          <div className="space-y-2.5">
            {/* MetaMask */}
            <button onClick={wallet.connect} disabled={wallet.isConnecting}
              className="btn-cyber w-full flex items-center gap-4 py-4 px-5 text-left group"
              style={{ borderRadius: '14px' }}>
              <div className="text-2xl w-10 h-10 flex items-center justify-center rounded-xl"
                   style={{ background: 'rgba(251,146,60,.1)', border: '1px solid rgba(251,146,60,.2)' }}>
                🦊
              </div>
              <div className="flex-1">
                <p className="font-bold text-sm text-white">{wallet.isConnecting ? 'Connecting…' : 'MetaMask'}</p>
                <p className="text-xs" style={{ color: '#1e3a4a' }}>Browser extension wallet</p>
              </div>
              {wallet.isConnecting
                ? <div className="w-5 h-5 rounded-full border-2 border-cyan-400/30 border-t-cyan-400 animate-spin" />
                : <span className="text-neon-cyan opacity-60 group-hover:opacity-100 transition-opacity">→</span>
              }
            </button>

            {/* WalletConnect */}
            <div className="tooltip w-full">
              <button disabled className="w-full flex items-center gap-4 py-4 px-5 rounded-2xl opacity-35 cursor-not-allowed"
                style={{ background: 'rgba(255,255,255,.02)', border: '1px solid rgba(255,255,255,.05)' }}>
                <div className="text-2xl w-10 h-10 flex items-center justify-center rounded-xl"
                     style={{ background: 'rgba(99,102,241,.08)', border: '1px solid rgba(99,102,241,.15)' }}>
                  🔗
                </div>
                <div className="flex-1 text-left">
                  <p className="font-bold text-sm flex items-center gap-2 text-white">
                    WalletConnect
                    <span className="badge-purple text-xs px-2 py-0.5 rounded-full font-normal">v2 Ready</span>
                  </p>
                  <p className="text-xs" style={{ color: '#0d2030' }}>Mobile & hardware wallets</p>
                </div>
              </button>
              <span className="tip">Integration ready — enable in config</span>
            </div>

            {/* Coinbase */}
            <div className="tooltip w-full">
              <button disabled className="w-full flex items-center gap-4 py-4 px-5 rounded-2xl opacity-35 cursor-not-allowed"
                style={{ background: 'rgba(255,255,255,.02)', border: '1px solid rgba(255,255,255,.05)' }}>
                <div className="text-2xl w-10 h-10 flex items-center justify-center rounded-xl"
                     style={{ background: 'rgba(37,99,235,.08)', border: '1px solid rgba(37,99,235,.15)' }}>
                  🔵
                </div>
                <div className="flex-1 text-left">
                  <p className="font-bold text-sm flex items-center gap-2 text-white">
                    Coinbase Wallet
                    <span className="text-xs px-2 py-0.5 rounded-full" style={{ background: 'rgba(255,255,255,.05)', color: '#1e3a4a' }}>Soon</span>
                  </p>
                  <p className="text-xs" style={{ color: '#0d2030' }}>Self-custody crypto wallet</p>
                </div>
              </button>
              <span className="tip">Coming in next release</span>
            </div>
          </div>

          <div className="mt-5 pt-4 flex items-center justify-center gap-3" style={{ borderTop: '1px solid rgba(0,212,255,.06)' }}>
            {['Mainnet', 'Goerli', 'Sepolia'].map(n => (
              <span key={n} className="text-xs" style={{ color: '#0d2030' }}>{n}</span>
            ))}
          </div>
        </div>

        <p className="text-center text-xs mt-4" style={{ color: '#0d2030' }}>
          Non-custodial · Your keys, your coins
        </p>
      </div>
    </div>
  )
}
