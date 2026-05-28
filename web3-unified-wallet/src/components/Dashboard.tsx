import { useState } from 'react'
import { WalletState, WalletActions } from '../hooks/useWallet'
import { shortenAddress, NETWORKS, getExplorerAddressUrl } from '../lib/ethers'

interface Props {
  wallet: WalletState & WalletActions
}

const SUPPORTED_NETWORKS = [
  { chainId: 1,        label: 'Mainnet' },
  { chainId: 5,        label: 'Goerli'  },
  { chainId: 11155111, label: 'Sepolia' },
]

export function Dashboard({ wallet }: Props) {
  const [copied, setCopied] = useState(false)
  const [refreshing, setRefreshing] = useState(false)

  const copyAddress = () => {
    if (!wallet.address) return
    navigator.clipboard.writeText(wallet.address).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }).catch(() => undefined)
  }

  const handleRefresh = async () => {
    setRefreshing(true)
    await wallet.refreshBalance()
    setRefreshing(false)
  }

  const networkColor = wallet.chainId ? (NETWORKS[wallet.chainId]?.color ?? '#94a3b8') : '#94a3b8'

  return (
    <div className="space-y-4">
      {/* Balance Card */}
      <div className="relative overflow-hidden bg-gradient-to-br from-indigo-600 via-indigo-700 to-purple-800 rounded-2xl p-6 text-white shadow-xl shadow-indigo-500/10">
        {/* Decorative circles */}
        <div className="absolute -top-8 -right-8 w-40 h-40 rounded-full bg-white/5" />
        <div className="absolute -bottom-12 -left-6 w-48 h-48 rounded-full bg-white/5" />

        <div className="relative">
          <div className="flex justify-between items-start mb-6">
            <div>
              <p className="text-indigo-300 text-xs font-medium uppercase tracking-widest mb-1">
                Connected Wallet
              </p>
              <button
                onClick={copyAddress}
                className="flex items-center gap-2 font-mono text-base text-white hover:text-indigo-200 transition-colors group"
                title="Copy address"
              >
                {wallet.address ? shortenAddress(wallet.address) : '—'}
                <span className="text-indigo-300 group-hover:text-white transition-colors text-xs">
                  {copied ? '✓' : '⎘'}
                </span>
              </button>
              {wallet.address && wallet.chainId && (
                <a
                  href={getExplorerAddressUrl(wallet.chainId, wallet.address)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-indigo-300 hover:text-white text-xs transition-colors"
                >
                  View on Etherscan ↗
                </a>
              )}
            </div>

            <div className="flex items-center gap-2">
              <span
                className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full font-medium"
                style={{ backgroundColor: `${networkColor}20`, color: networkColor, border: `1px solid ${networkColor}40` }}
              >
                <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ backgroundColor: networkColor }} />
                {wallet.networkName}
              </span>
            </div>
          </div>

          <div className="flex items-end justify-between">
            <div>
              <p className="text-indigo-300 text-xs font-medium uppercase tracking-widest mb-1">Balance</p>
              <p className="text-4xl font-bold tracking-tight">
                {wallet.balance ?? '—'}
                <span className="text-xl text-indigo-300 ml-2 font-medium">ETH</span>
              </p>
            </div>
            <button
              onClick={handleRefresh}
              disabled={refreshing}
              className="text-indigo-300 hover:text-white transition-colors text-lg disabled:opacity-50"
              title="Refresh balance"
            >
              <span className={refreshing ? 'inline-block animate-spin' : ''}>↻</span>
            </button>
          </div>
        </div>
      </div>

      {/* Network Switcher */}
      <div className="bg-slate-800/60 rounded-xl p-4 border border-slate-700/50">
        <p className="text-slate-400 text-xs font-medium uppercase tracking-widest mb-3">Network</p>
        <div className="flex gap-2">
          {SUPPORTED_NETWORKS.map(({ chainId, label }) => {
            const isActive = wallet.chainId === chainId
            const color = NETWORKS[chainId]?.color ?? '#6366f1'
            return (
              <button
                key={chainId}
                onClick={() => wallet.switchNetwork(chainId)}
                className={`flex-1 py-2.5 px-3 rounded-lg text-sm font-medium transition-all duration-200 ${
                  isActive
                    ? 'text-white shadow-sm'
                    : 'bg-slate-700/40 text-slate-400 hover:text-white hover:bg-slate-700'
                }`}
                style={isActive ? { backgroundColor: `${color}25`, border: `1px solid ${color}50`, color } : {}}
              >
                {label}
              </button>
            )
          })}
        </div>
        {wallet.error && (
          <p className="text-red-400 text-xs mt-2 flex items-center gap-1">
            <span>⚠</span> {wallet.error}
          </p>
        )}
      </div>

      {/* Info Grid */}
      <div className="grid grid-cols-2 gap-3">
        <div className="bg-slate-800/60 rounded-xl p-4 border border-slate-700/50">
          <p className="text-slate-500 text-xs mb-1">Chain ID</p>
          <p className="text-white font-mono font-semibold">{wallet.chainId ?? '—'}</p>
        </div>
        <div className="bg-slate-800/60 rounded-xl p-4 border border-slate-700/50">
          <p className="text-slate-500 text-xs mb-1">Wallet Type</p>
          <p className="text-white font-semibold text-sm">
            {window.ethereum?.isMetaMask ? 'MetaMask' : 'Web3 Wallet'}
          </p>
        </div>
      </div>

      <button
        onClick={wallet.disconnect}
        className="w-full py-2.5 text-slate-600 hover:text-red-400 text-sm transition-colors rounded-xl hover:bg-red-400/5"
      >
        Disconnect Wallet
      </button>
    </div>
  )
}
