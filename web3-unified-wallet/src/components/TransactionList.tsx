import { Transaction, TxStatus } from '../hooks/useTransactions'
import { shortenAddress, getExplorerTxUrl } from '../lib/ethers'

interface Props { transactions: Transaction[]; onClear: () => void }

const STATUS: Record<TxStatus, { label: string; color: string; bg: string; dot: string }> = {
  pending:   { label: 'Pending',   color: '#f59e0b', bg: 'rgba(245,158,11,0.08)',  dot: 'animate-pulse' },
  confirmed: { label: 'Confirmed', color: '#10b981', bg: 'rgba(16,185,129,0.08)',  dot: '' },
  failed:    { label: 'Failed',    color: '#ef4444', bg: 'rgba(239,68,68,0.08)',   dot: '' },
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
      <div className="rounded-3xl p-16 text-center" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)' }}>
        <div className="text-5xl mb-4 opacity-20">⧖</div>
        <p className="text-sm font-medium" style={{ color: '#334155' }}>No transactions yet</p>
        <p className="text-xs mt-1" style={{ color: '#1e293b' }}>Sent transactions will appear here</p>
      </div>
    )
  }

  return (
    <div className="rounded-3xl overflow-hidden" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)' }}>
      <div className="px-5 py-4 flex justify-between items-center" style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
        <p className="font-semibold text-white text-sm">Transaction History</p>
        <button onClick={onClear} className="text-xs transition-colors hover:opacity-80" style={{ color: '#334155' }}>Clear all</button>
      </div>

      <div>
        {transactions.map((tx, i) => {
          const s = STATUS[tx.status]
          return (
            <div key={tx.hash} className="px-5 py-4 transition-colors hover:bg-white/[0.02]"
                 style={i < transactions.length - 1 ? { borderBottom: '1px solid rgba(255,255,255,0.03)' } : {}}>
              <div className="flex justify-between items-start mb-2">
                <div className="flex items-center gap-2 px-2.5 py-1 rounded-full"
                     style={{ background: s.bg, border: `1px solid ${s.color}25` }}>
                  <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} style={{ background: s.color }} />
                  <span className="text-xs font-semibold" style={{ color: s.color }}>{s.label}</span>
                </div>
                <div className="text-right">
                  <p className="text-white font-semibold text-sm">{tx.value} ETH</p>
                  <p className="text-xs" style={{ color: '#334155' }}>{timeAgo(tx.timestamp)}</p>
                </div>
              </div>
              <div className="flex justify-between items-center">
                <p className="font-mono text-xs" style={{ color: '#475569' }}>To: {shortenAddress(tx.to)}</p>
                <a href={getExplorerTxUrl(tx.chainId, tx.hash)} target="_blank" rel="noopener noreferrer"
                   className="text-xs transition-colors hover:opacity-80" style={{ color: '#7c3aed' }}>
                  Etherscan ↗
                </a>
              </div>
              <p className="font-mono text-xs mt-0.5" style={{ color: '#1e293b' }}>{shortenAddress(tx.hash)}</p>
            </div>
          )
        })}
      </div>
    </div>
  )
}
