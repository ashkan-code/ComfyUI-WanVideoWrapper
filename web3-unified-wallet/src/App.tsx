import { useCallback, useState } from 'react'
import { useWallet } from './hooks/useWallet'
import { useTransactions } from './hooks/useTransactions'
import { Intro } from './components/Intro'
import { WalletConnect } from './components/WalletConnect'
import { Dashboard } from './components/Dashboard'
import { SendEth } from './components/SendEth'
import { TransactionList } from './components/TransactionList'
import { ContractReader } from './components/ContractReader'

type Tab = 'dashboard' | 'send' | 'history' | 'contracts'

interface TabMeta {
  id:    Tab
  icon:  string
  label: string
  color: string
  title: string
  desc:  string
  features: string[]
}

const TABS: TabMeta[] = [
  {
    id: 'dashboard', icon: '◈', label: 'Dashboard', color: '#00d4ff',
    title: 'Wallet Dashboard',
    desc: 'Real-time overview of your connected wallet. See your ETH balance, network status, and account details at a glance.',
    features: ['Live ETH balance', 'Network switcher', 'Etherscan links', 'Copy address'],
  },
  {
    id: 'send', icon: '↗', label: 'Send ETH', color: '#a855f7',
    title: 'Transfer ETH',
    desc: 'Send ETH to any address with EIP-1559 gas estimation. Preview the exact fee before you confirm.',
    features: ['EIP-1559 + Legacy gas', 'Address validation', 'Fee preview', 'Live tx tracking'],
  },
  {
    id: 'history', icon: '⧖', label: 'History', color: '#f59e0b',
    title: 'Transaction Log',
    desc: 'Every transaction you send is logged here with live status updates — from pending to confirmed or failed.',
    features: ['Pending / Confirmed / Failed', 'Etherscan deep links', 'Time elapsed', 'One-click clear'],
  },
  {
    id: 'contracts', icon: '⬡', label: 'Contracts', color: '#00ff88',
    title: 'ERC-20 Reader',
    desc: 'Call any ERC-20 smart contract directly. Read token balances for USDC, USDT, LINK or any custom contract.',
    features: ['USDC · USDT · LINK presets', 'Any ERC-20 contract', 'Direct on-chain call', 'No API key needed'],
  },
]

export function App() {
  const wallet = useWallet()
  const { transactions, addTransaction, updateTransaction, clearTransactions } = useTransactions()
  const [activeTab, setActiveTab]   = useState<Tab>('dashboard')
  const [hoveredTab, setHoveredTab] = useState<Tab | null>(null)
  const [showIntro, setShowIntro]   = useState(true)

  const handleIntroDone = useCallback(() => setShowIntro(false), [])

  const pendingCount = transactions.filter(t => t.status === 'pending').length
  const activeMeta   = TABS.find(t => t.id === activeTab)!
  const hoverMeta    = hoveredTab ? TABS.find(t => t.id === hoveredTab) : null

  if (showIntro) return <Intro onDone={handleIntroDone} />
  if (!wallet.isConnected) return <WalletConnect wallet={wallet} />

  return (
    <div className="flex min-h-screen noise" style={{ background: 'var(--bg)' }}>

      {/* ── Ambient glows ─────────────────────── */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden z-0">
        <div style={{ position: 'absolute', top: 0, left: '50%', transform: 'translateX(-50%)', width: 900, height: 350,
          background: `radial-gradient(ellipse, ${activeMeta.color}07 0%, transparent 65%)`,
          transition: 'background 1s ease' }} />
        <div style={{ position: 'absolute', bottom: 0, right: 0, width: 500, height: 500,
          background: 'radial-gradient(circle, rgba(147,51,234,.05) 0%, transparent 70%)' }} />
        <div className="absolute inset-0 grid-bg" />
      </div>

      {/* ── Sidebar ───────────────────────────── */}
      <nav className="relative z-20 w-[76px] flex flex-col items-center py-6 gap-1.5 shrink-0"
           style={{ background: 'rgba(0,0,0,.4)', borderRight: '1px solid rgba(0,212,255,.06)', backdropFilter: 'blur(20px)' }}>

        {/* Logo */}
        <div className="w-12 h-12 rounded-2xl flex items-center justify-center mb-6 animate-float cursor-default"
             style={{ background: 'linear-gradient(135deg, #0ea5e9, #7c3aed)',
               boxShadow: '0 0 30px rgba(14,165,233,.35), 0 0 60px rgba(124,58,237,.15)' }}>
          <span style={{ fontSize: 22, fontWeight: 900, color: 'white' }}>⟠</span>
        </div>

        {TABS.map(tab => {
          const isActive  = activeTab  === tab.id
          const isHovered = hoveredTab === tab.id
          return (
            <button key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              onMouseEnter={() => setHoveredTab(tab.id)}
              onMouseLeave={() => setHoveredTab(null)}
              style={{
                position: 'relative', width: 48, height: 48, borderRadius: 16,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 18, cursor: 'pointer', border: 'none', outline: 'none',
                transition: 'all .2s',
                background: isActive  ? `${tab.color}12` : isHovered ? 'rgba(255,255,255,.04)' : 'transparent',
                color:      isActive  ? tab.color : isHovered ? '#475569' : '#1e3a4a',
                boxShadow:  isActive  ? `0 0 20px ${tab.color}18, inset 0 0 0 1px ${tab.color}30` : 'none',
                transform:  isHovered && !isActive ? 'scale(1.08)' : 'scale(1)',
              }}>
              {tab.icon}
              {tab.id === 'history' && pendingCount > 0 && (
                <span style={{
                  position: 'absolute', top: -4, right: -4, width: 16, height: 16,
                  borderRadius: '50%', background: 'var(--amber)',
                  fontSize: 9, fontWeight: 900, color: '#000',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  boxShadow: '0 0 10px rgba(245,158,11,.5)',
                }}>{pendingCount}</span>
              )}
            </button>
          )
        })}

        <div style={{ flex: 1 }} />

        {/* Connected pill */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4, marginBottom: 4 }}>
          <div style={{ width: 8, height: 8, borderRadius: '50%', background: '#00ff88',
            boxShadow: '0 0 10px #00ff88', animation: 'glowPulse 2s ease-in-out infinite' }} />
          <span style={{ fontSize: 8, color: '#0d2030', fontFamily: 'monospace', letterSpacing: '.1em',
            writingMode: 'vertical-rl', transform: 'rotate(180deg)', textTransform: 'uppercase' }}>Live</span>
        </div>
      </nav>

      {/* ── Hover Description Panel ───────────── */}
      <div style={{
        position: 'fixed', left: 76, top: 0, bottom: 0, zIndex: 19,
        width: hoverMeta ? 280 : 0,
        overflow: 'hidden',
        transition: 'width .28s cubic-bezier(.22,1,.36,1)',
        pointerEvents: hoverMeta ? 'auto' : 'none',
      }}
        onMouseEnter={() => hoverMeta && setHoveredTab(hoverMeta.id)}
        onMouseLeave={() => setHoveredTab(null)}>

        {hoverMeta && (
          <div style={{
            width: 280, height: '100%',
            background: 'rgba(2,4,8,.92)',
            borderRight: `1px solid ${hoverMeta.color}20`,
            backdropFilter: 'blur(24px)',
            padding: '32px 24px',
            display: 'flex', flexDirection: 'column', justifyContent: 'center',
          }}>
            {/* Section icon */}
            <div style={{
              width: 56, height: 56, borderRadius: 18, marginBottom: 20,
              background: `${hoverMeta.color}10`,
              border: `1px solid ${hoverMeta.color}25`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 24, color: hoverMeta.color,
              boxShadow: `0 0 30px ${hoverMeta.color}12`,
            }} className="animate-slideUp">
              {hoverMeta.icon}
            </div>

            {/* Title */}
            <p className="animate-slideUp" style={{ fontSize: 18, fontWeight: 800, color: 'white', marginBottom: 8,
              animationDelay: '.05s' }}>
              {hoverMeta.title}
            </p>

            {/* Description */}
            <p className="animate-slideUp" style={{ fontSize: 12, color: '#334155', lineHeight: 1.7, marginBottom: 20,
              animationDelay: '.1s' }}>
              {hoverMeta.desc}
            </p>

            {/* Feature list */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {hoverMeta.features.map((f, i) => (
                <div key={f} className="animate-slideUp"
                  style={{ display: 'flex', alignItems: 'center', gap: 10,
                    animationDelay: `${.15 + i * .06}s` }}>
                  <div style={{ width: 4, height: 4, borderRadius: '50%', background: hoverMeta.color,
                    boxShadow: `0 0 6px ${hoverMeta.color}`, flexShrink: 0 }} />
                  <span style={{ fontSize: 12, color: '#475569' }}>{f}</span>
                </div>
              ))}
            </div>

            {/* CTA */}
            <button onClick={() => { setActiveTab(hoverMeta.id); setHoveredTab(null) }}
              className="animate-slideUp" style={{
                marginTop: 28, padding: '10px 0', borderRadius: 12, border: 'none', cursor: 'pointer',
                background: `${hoverMeta.color}14`,
                color: hoverMeta.color, fontWeight: 700, fontSize: 12,
                outline: `1px solid ${hoverMeta.color}25`,
                animationDelay: '.35s',
                transition: 'all .2s',
              }}
              onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.background = `${hoverMeta.color}22` }}
              onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.background = `${hoverMeta.color}14` }}>
              Open {hoverMeta.label} →
            </button>
          </div>
        )}
      </div>

      {/* ── Main content ──────────────────────── */}
      <main className="relative z-10 flex-1 overflow-y-auto" style={{ transition: 'margin-left .28s cubic-bezier(.22,1,.36,1)' }}>
        <div style={{ maxWidth: 620, margin: '0 auto', padding: '32px 28px' }}>

          {/* Header */}
          <div className="flex items-center justify-between mb-8 animate-fadeIn">
            <div>
              <p style={{ fontSize: 10, fontWeight: 700, color: '#0d2030', letterSpacing: '.2em',
                textTransform: 'uppercase', marginBottom: 4 }}>
                {activeMeta.label}
              </p>
              <h1 style={{ fontSize: 26, fontWeight: 900, color: 'white' }}>
                {activeMeta.title}
              </h1>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 14px', borderRadius: 99,
              background: 'rgba(0,255,136,.05)', border: '1px solid rgba(0,255,136,.12)' }}>
              <span style={{ width: 7, height: 7, borderRadius: '50%', background: '#00ff88',
                boxShadow: '0 0 8px #00ff88', animation: 'glowPulse 2s ease-in-out infinite' }} />
              <span style={{ fontSize: 11, fontWeight: 700, color: '#00ff88' }}>{wallet.networkName}</span>
            </div>
          </div>

          {/* Tab content */}
          {activeTab === 'dashboard'  && <Dashboard   wallet={wallet} />}
          {activeTab === 'send'       && <SendEth      wallet={wallet} onTransactionSent={addTransaction} onTransactionConfirmed={updateTransaction} />}
          {activeTab === 'history'    && <TransactionList transactions={transactions} onClear={clearTransactions} />}
          {activeTab === 'contracts'  && <ContractReader wallet={wallet} />}
        </div>
      </main>
    </div>
  )
}
