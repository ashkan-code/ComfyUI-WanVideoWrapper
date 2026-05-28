import { useState } from 'react'
import { useWallet } from './hooks/useWallet'
import { useTransactions } from './hooks/useTransactions'
import { WalletConnect } from './components/WalletConnect'
import { Dashboard } from './components/Dashboard'
import { SendEth } from './components/SendEth'
import { TransactionList } from './components/TransactionList'
import { ContractReader } from './components/ContractReader'

type Tab = 'dashboard' | 'send' | 'history' | 'contracts'

interface TabItem { id: Tab; label: string; icon: string }

const TABS: TabItem[] = [
  { id: 'dashboard', label: 'Dashboard', icon: '◈' },
  { id: 'send',      label: 'Send',      icon: '↗' },
  { id: 'history',   label: 'History',   icon: '⧖' },
  { id: 'contracts', label: 'Contracts', icon: '⬡' },
]

export function App() {
  const wallet = useWallet()
  const { transactions, addTransaction, updateTransaction, clearTransactions } = useTransactions()
  const [activeTab, setActiveTab] = useState<Tab>('dashboard')

  const pendingCount = transactions.filter(t => t.status === 'pending').length

  if (!wallet.isConnected) return <WalletConnect wallet={wallet} />

  return (
    <div className="flex min-h-screen" style={{ background: '#07090f' }}>

      {/* Ambient background glows */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden">
        <div className="absolute top-0 left-1/4 w-96 h-96 rounded-full opacity-10" style={{ background: 'radial-gradient(circle, #7c3aed, transparent 70%)' }} />
        <div className="absolute bottom-0 right-1/4 w-80 h-80 rounded-full opacity-8" style={{ background: 'radial-gradient(circle, #2563eb, transparent 70%)' }} />
      </div>

      {/* Sidebar */}
      <nav className="relative z-10 w-[72px] flex flex-col items-center py-6 gap-2 shrink-0"
           style={{ background: 'rgba(255,255,255,0.015)', borderRight: '1px solid rgba(255,255,255,0.05)' }}>

        {/* Logo */}
        <div className="w-11 h-11 rounded-2xl flex items-center justify-center mb-5 float"
             style={{ background: 'linear-gradient(135deg, #7c3aed, #2563eb)', boxShadow: '0 8px 32px rgba(124,58,237,0.4)' }}>
          <span className="text-xl text-white font-bold">⟠</span>
        </div>

        {TABS.map(tab => (
          <button key={tab.id} onClick={() => setActiveTab(tab.id)} title={tab.label}
            className="relative w-12 h-12 rounded-2xl flex items-center justify-center text-lg transition-all duration-300"
            style={activeTab === tab.id
              ? { background: 'linear-gradient(135deg, rgba(124,58,237,0.3), rgba(37,99,235,0.3))', border: '1px solid rgba(139,92,246,0.4)', color: '#a78bfa', boxShadow: '0 4px 20px rgba(124,58,237,0.2)' }
              : { color: '#334155', border: '1px solid transparent' }
            }>
            {tab.icon}
            {tab.id === 'history' && pendingCount > 0 && (
              <span className="absolute -top-1 -right-1 w-4 h-4 rounded-full text-xs font-bold flex items-center justify-center text-white"
                    style={{ background: 'linear-gradient(135deg, #f59e0b, #ef4444)' }}>
                {pendingCount}
              </span>
            )}
          </button>
        ))}

        <div className="flex-1" />

        {/* Connected dot */}
        <div className="w-2 h-2 rounded-full pulse-ring" style={{ background: '#10b981' }} title="Connected" />
      </nav>

      {/* Main content */}
      <main className="relative z-10 flex-1 overflow-y-auto">
        <div className="max-w-xl mx-auto px-6 py-8">

          {/* Header */}
          <div className="flex items-center justify-between mb-8">
            <div>
              <p className="text-xs font-medium mb-0.5" style={{ color: '#475569', letterSpacing: '0.1em', textTransform: 'uppercase' }}>
                {TABS.find(t => t.id === activeTab)?.label}
              </p>
              <h1 className="text-2xl font-bold text-white">
                {activeTab === 'dashboard' && 'Your Wallet'}
                {activeTab === 'send' && 'Send ETH'}
                {activeTab === 'history' && 'Transactions'}
                {activeTab === 'contracts' && 'Smart Contracts'}
              </h1>
            </div>
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-full"
                 style={{ background: 'rgba(16,185,129,0.1)', border: '1px solid rgba(16,185,129,0.2)' }}>
              <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: '#10b981' }} />
              <span className="text-xs font-medium" style={{ color: '#10b981' }}>{wallet.networkName}</span>
            </div>
          </div>

          {activeTab === 'dashboard'  && <Dashboard wallet={wallet} />}
          {activeTab === 'send'       && <SendEth wallet={wallet} onTransactionSent={addTransaction} onTransactionConfirmed={updateTransaction} />}
          {activeTab === 'history'    && <TransactionList transactions={transactions} onClear={clearTransactions} />}
          {activeTab === 'contracts'  && <ContractReader wallet={wallet} />}
        </div>
      </main>
    </div>
  )
}
