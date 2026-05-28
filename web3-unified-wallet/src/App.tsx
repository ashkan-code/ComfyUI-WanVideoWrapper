import { useState } from 'react'
import { useWallet } from './hooks/useWallet'
import { useTransactions } from './hooks/useTransactions'
import { WalletConnect } from './components/WalletConnect'
import { Dashboard } from './components/Dashboard'
import { SendEth } from './components/SendEth'
import { TransactionList } from './components/TransactionList'
import { ContractReader } from './components/ContractReader'

type Tab = 'dashboard' | 'send' | 'history' | 'contracts'

interface TabItem { id: Tab; label: string; icon: string; tip: string }

const TABS: TabItem[] = [
  { id: 'dashboard', label: 'Dashboard', icon: '◈', tip: 'Wallet overview' },
  { id: 'send',      label: 'Send ETH',  icon: '↗', tip: 'Transfer ETH'   },
  { id: 'history',   label: 'History',   icon: '⧖', tip: 'Transaction log' },
  { id: 'contracts', label: 'Contracts', icon: '⬡', tip: 'Read ERC-20'    },
]

export function App() {
  const wallet = useWallet()
  const { transactions, addTransaction, updateTransaction, clearTransactions } = useTransactions()
  const [activeTab, setActiveTab] = useState<Tab>('dashboard')

  const pendingCount = transactions.filter(t => t.status === 'pending').length

  if (!wallet.isConnected) return <WalletConnect wallet={wallet} />

  return (
    <div className="flex min-h-screen noise" style={{ background: 'var(--bg)' }}>

      {/* Ambient bg glows */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden z-0">
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[800px] h-[300px]"
             style={{ background: 'radial-gradient(ellipse, rgba(0,212,255,.04) 0%, transparent 70%)' }} />
        <div className="absolute bottom-0 right-0 w-96 h-96"
             style={{ background: 'radial-gradient(circle, rgba(147,51,234,.05) 0%, transparent 70%)' }} />
        {/* Animated grid */}
        <div className="absolute inset-0 grid-bg opacity-100" />
      </div>

      {/* ── Sidebar ──────────────────────────── */}
      <nav className="relative z-10 w-[76px] flex flex-col items-center py-6 gap-1.5 shrink-0"
           style={{ background: 'rgba(0,212,255,.015)', borderRight: '1px solid rgba(0,212,255,.06)' }}>

        {/* Logo */}
        <div className="w-12 h-12 rounded-2xl flex items-center justify-center mb-5 animate-float"
             style={{ background: 'linear-gradient(135deg, #0ea5e9, #7c3aed)', boxShadow: '0 0 30px rgba(14,165,233,.3), 0 0 60px rgba(124,58,237,.15)' }}>
          <span className="text-2xl font-black text-white">⟠</span>
        </div>

        {TABS.map(tab => (
          <div key={tab.id} className="tooltip w-full flex justify-center">
            <button onClick={() => setActiveTab(tab.id)}
              className="relative w-12 h-12 rounded-2xl flex items-center justify-center text-lg transition-all duration-200"
              style={activeTab === tab.id
                ? { background: 'rgba(0,212,255,.08)', border: '1px solid rgba(0,212,255,.2)', color: '#00d4ff', boxShadow: '0 0 20px rgba(0,212,255,.1)' }
                : { color: '#1e3a4a', border: '1px solid transparent' }
              }
              onMouseEnter={e => { if (activeTab !== tab.id) { const b = e.currentTarget; b.style.color='#475569'; b.style.background='rgba(255,255,255,.03)' } }}
              onMouseLeave={e => { if (activeTab !== tab.id) { const b = e.currentTarget; b.style.color='#1e3a4a'; b.style.background='transparent' } }}>
              {tab.icon}
              {tab.id === 'history' && pendingCount > 0 && (
                <span className="absolute -top-1 -right-1 w-4 h-4 rounded-full text-black text-xs font-black flex items-center justify-center"
                      style={{ background: 'var(--amber)', boxShadow: '0 0 8px rgba(245,158,11,.4)' }}>
                  {pendingCount}
                </span>
              )}
            </button>
            <span className="tip" style={{ left: 'calc(100% + 12px)', bottom: 'auto', top: '50%', transform: 'translateY(-50%)', whiteSpace: 'nowrap' }}>
              {tab.tip}
            </span>
          </div>
        ))}

        <div className="flex-1" />

        {/* Status */}
        <div className="flex flex-col items-center gap-1 mb-1">
          <div className="w-2 h-2 rounded-full animate-pulse" style={{ background: '#00ff88', boxShadow: '0 0 8px #00ff88' }} title="Connected" />
        </div>
      </nav>

      {/* ── Main ─────────────────────────────── */}
      <main className="relative z-10 flex-1 overflow-y-auto">
        <div className="max-w-[580px] mx-auto px-6 py-8">

          {/* Header */}
          <div className="flex items-center justify-between mb-8">
            <div>
              <p className="text-xs font-bold uppercase tracking-widest mb-0.5"
                 style={{ color: '#0d2030', letterSpacing: '.14em' }}>
                {TABS.find(t => t.id === activeTab)?.label}
              </p>
              <h1 className="text-2xl font-black text-white">
                {activeTab === 'dashboard' && 'Your Wallet'}
                {activeTab === 'send'      && 'Send ETH'}
                {activeTab === 'history'   && 'Transactions'}
                {activeTab === 'contracts' && 'Smart Contracts'}
              </h1>
            </div>
            <div className="flex items-center gap-2 px-4 py-2 rounded-full"
                 style={{ background: 'rgba(0,255,136,.06)', border: '1px solid rgba(0,255,136,.12)' }}>
              <span className="w-2 h-2 rounded-full animate-pulse" style={{ background: '#00ff88', boxShadow: '0 0 6px #00ff88' }} />
              <span className="text-xs font-bold text-neon-green">{wallet.networkName}</span>
            </div>
          </div>

          {/* Tab views */}
          {activeTab === 'dashboard'  && <Dashboard wallet={wallet} />}
          {activeTab === 'send'       && <SendEth wallet={wallet} onTransactionSent={addTransaction} onTransactionConfirmed={updateTransaction} />}
          {activeTab === 'history'    && <TransactionList transactions={transactions} onClear={clearTransactions} />}
          {activeTab === 'contracts'  && <ContractReader wallet={wallet} />}
        </div>
      </main>
    </div>
  )
}
