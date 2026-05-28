import { Transaction, TxStatus } from '../hooks/useTransactions'
import { shortenAddress, getExplorerTxUrl } from '../lib/ethers'

interface Props { transactions: Transaction[]; onClear: () => void }

const STATUS: Record<TxStatus, { label: string; cls: string; dot: string; icon: string }> = {
  pending:   { label: 'Pending',   cls: 'badge-amber', dot: 'animate-pulse', icon: '⏳' },
  confirmed: { label: 'Confirmed', cls: 'badge-green',  dot: '',              icon: '✓'  },
  failed:    { label: 'Failed',    cls: 'badge-red',    dot: '',              icon: '✗'  },
}

function timeAgo(ts: number): string {
  const d = Math.floor((Date.now() - ts) / 1000)
  if (d < 60) return `${d}s ago`
  if (d < 3600) return `${Math.floor(d / 60)}m ago`
  return `${Math.floor(d / 3600)}h ago`
}

export function TransactionList({ transactions, onClear }: Props) {
  if (transactions.length === 0) {
    return (
      <div className="neon-card p-16 text-center animate-slideUp scan-container">
        <div className="scan-line opacity-30" />
        <div className="text-5xl mb-4" style={{ filter: 'grayscale(1)', opacity: .15 }}>⧖</div>
        <p className="font-bold text-white mb-1">No transactions yet</p>
        <p className="text-xs" style={{ color: '#0d2030' }}>
          Go to <span className="text-neon-cyan font-mono">↗ Send</span> to make your first transaction.
          It will appear here with live status.
        </p>
      </div>
    )
  }

  return (
    <div className="neon-card overflow-hidden animate-slideUp">
      <div className="px-5 py-4 flex justify-between items-center"
           style={{ borderBottom: '1px solid rgba(0,212,255,.06)' }}>
        <div className="flex items-center gap-2">
          <span className="text-white font-bold text-sm">Transaction History</span>
          <span className="badge-cyan text-xs px-2 py-0.5 rounded-full font-bold">{transactions.length}</span>
        </div>
        <button onClick={onClear} className="text-xs transition-all hover:opacity-80" style={{ color: '#0d2030' }}>
          Clear all
        </button>
      </div>

      <div>
        {transactions.map((tx, i) => {
          const s = STATUS[tx.status]
          return (
            <div key={tx.hash} className="px-5 py-4 transition-all hover:bg-white/[0.015] animate-fadeIn"
                 style={i < transactions.length - 1 ? { borderBottom: '1px solid rgba(0,212,255,.04)' } : {}}>
              <div className="flex justify-between items-start mb-2">
                <div className={`${s.cls} flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-bold`}>
                  <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} style={{ background: 'currentColor' }} />
                  {s.icon} {s.label}
                </div>
                <div className="text-right">
                  <p className="text-white font-bold text-sm">{tx.value} ETH</p>
                  <p className="text-xs" style={{ color: '#0d2030' }}>{timeAgo(tx.timestamp)}</p>
                </div>
              </div>
              <div className="flex justify-between items-center mt-2">
                <p className="font-mono text-xs" style={{ color: '#1e3a4a' }}>→ {shortenAddress(tx.to)}</p>
                <a href={getExplorerTxUrl(tx.chainId, tx.hash)} target="_blank" rel="noopener noreferrer"
                   className="text-xs font-semibold transition-all hover:opacity-80 text-neon-cyan">
                  Etherscan ↗
                </a>
              </div>
              <p className="font-mono text-xs mt-1" style={{ color: '#0d2030' }}>{shortenAddress(tx.hash)}</p>
            </div>
          )
        })}
      </div>
    </div>
  )
}
