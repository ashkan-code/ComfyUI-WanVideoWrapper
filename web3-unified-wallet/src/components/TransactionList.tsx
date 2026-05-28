import { Transaction, TxStatus } from '../hooks/useTransactions'
import { shortenAddress, getExplorerTxUrl } from '../lib/ethers'

interface Props {
  transactions: Transaction[]
  onClear: () => void
}

interface StatusConfig {
  label: string
  dotClass: string
  badgeClass: string
}

const STATUS: Record<TxStatus, StatusConfig> = {
  pending:   { label: 'Pending',   dotClass: 'bg-yellow-400 animate-pulse', badgeClass: 'text-yellow-400 bg-yellow-400/10 border-yellow-400/20' },
  confirmed: { label: 'Confirmed', dotClass: 'bg-green-400',                badgeClass: 'text-green-400 bg-green-400/10 border-green-400/20'   },
  failed:    { label: 'Failed',    dotClass: 'bg-red-400',                  badgeClass: 'text-red-400 bg-red-400/10 border-red-400/20'         },
}

function timeAgo(timestamp: number): string {
  const diff = Math.floor((Date.now() - timestamp) / 1000)
  if (diff < 60)  return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  return `${Math.floor(diff / 3600)}h ago`
}

export function TransactionList({ transactions, onClear }: Props) {
  if (transactions.length === 0) {
    return (
      <div className="bg-slate-800/60 rounded-xl border border-slate-700/50 p-12 text-center">
        <div className="text-4xl mb-3 opacity-30">⟠</div>
        <p className="text-slate-500 text-sm">No transactions yet</p>
        <p className="text-slate-600 text-xs mt-1">Sent transactions will appear here</p>
      </div>
    )
  }

  return (
    <div className="bg-slate-800/60 rounded-xl border border-slate-700/50 overflow-hidden">
      <div className="px-5 py-4 border-b border-slate-700/50 flex justify-between items-center">
        <h2 className="text-white font-semibold">Transaction History</h2>
        <button
          onClick={onClear}
          className="text-slate-600 hover:text-slate-400 text-xs transition-colors"
        >
          Clear all
        </button>
      </div>

      <div className="divide-y divide-slate-700/30">
        {transactions.map(tx => {
          const cfg = STATUS[tx.status]
          return (
            <div key={tx.hash} className="px-5 py-4 hover:bg-slate-700/20 transition-colors">
              <div className="flex justify-between items-start mb-2">
                <span className={`inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full font-medium border ${cfg.badgeClass}`}>
                  <span className={`w-1.5 h-1.5 rounded-full ${cfg.dotClass}`} />
                  {cfg.label}
                </span>
                <div className="text-right">
                  <span className="text-white font-semibold text-sm">{tx.value} ETH</span>
                  <p className="text-slate-500 text-xs mt-0.5">{timeAgo(tx.timestamp)}</p>
                </div>
              </div>

              <div className="flex justify-between items-center mt-2">
                <div className="text-slate-400 text-xs font-mono">
                  To: {shortenAddress(tx.to)}
                </div>
                <a
                  href={getExplorerTxUrl(tx.chainId, tx.hash)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-indigo-400 hover:text-indigo-300 text-xs transition-colors flex items-center gap-1"
                >
                  Etherscan ↗
                </a>
              </div>

              <p className="text-slate-600 text-xs font-mono mt-1">{shortenAddress(tx.hash)}</p>
            </div>
          )
        })}
      </div>
    </div>
  )
}
