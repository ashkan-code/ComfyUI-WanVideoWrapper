import { useState } from 'react'
import { useWallet } from './hooks/useWallet'
import { useTransactions } from './hooks/useTransactions'
import { WalletConnect } from './components/WalletConnect'
import { Dashboard } from './components/Dashboard'
import { SendEth } from './components/SendEth'
import { TransactionList } from './components/TransactionList'
import { ContractReader } from './components/ContractReader'

type Tab = 'dashboard' | 'send' | 'history' | 'contracts'

interface TabItem {
  id: Tab
  label: string
  icon: string
}

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

  if (!wallet.isConnected) {
    return <WalletConnect wallet={wallet} />
  }

  return (
    <div className="flex min-h-screen bg-slate-900">
      {/* Sidebar */}
      <nav className="w-[68px] bg-slate-800/80 border-r border-slate-700/50 flex flex-col items-center py-5 gap-1 shrink-0">
        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center mb-4 shadow-lg shadow-indigo-500/20">
          <span className="text-lg">⟠</span>
        </div>

        {TABS.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            title={tab.label}
            className={`relative w-11 h-11 rounded-xl flex items-center justify-center text-lg transition-all duration-200 ${
              activeTab === tab.id
                ? 'bg-indigo-600 text-white shadow-md shadow-indigo-600/30'
                : 'text-slate-500 hover:text-slate-300 hover:bg-slate-700/50'
            }`}
          >
            {tab.icon}
            {tab.id === 'history' && pendingCount > 0 && (
              <span className="absolute -top-0.5 -right-0.5 w-4 h-4 bg-yellow-500 rounded-full text-xs text-black font-bold flex items-center justify-center">
                {pendingCount}
              </span>
            )}
          </button>
        ))}

        {/* Spacer */}
        <div className="flex-1" />

        {/* Network dot */}
        <div className="w-2.5 h-2.5 rounded-full bg-green-400 animate-pulse mb-2" title="Connected" />
      </nav>

      {/* Main */}
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-2xl mx-auto px-6 py-6">
          {/* Header */}
          <div className="flex items-center justify-between mb-6">
            <h1 className="text-white font-bold text-xl">
              {TABS.find(t => t.id === activeTab)?.label}
            </h1>
            <div className="flex items-center gap-2 text-sm text-slate-400">
              <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
              {wallet.networkName}
            </div>
          </div>

          {/* Tab content */}
          {activeTab === 'dashboard' && (
            <Dashboard wallet={wallet} />
          )}
          {activeTab === 'send' && (
            <SendEth
              wallet={wallet}
              onTransactionSent={addTransaction}
              onTransactionConfirmed={updateTransaction}
            />
          )}
          {activeTab === 'history' && (
            <TransactionList transactions={transactions} onClear={clearTransactions} />
          )}
          {activeTab === 'contracts' && (
            <ContractReader wallet={wallet} />
          )}
        </div>
      </main>
    </div>
  )
}
