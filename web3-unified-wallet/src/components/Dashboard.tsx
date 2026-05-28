import { useState } from 'react'
import { WalletState, WalletActions } from '../hooks/useWallet'
import { shortenAddress, NETWORKS, getExplorerAddressUrl } from '../lib/ethers'

interface Props { wallet: WalletState & WalletActions }

const NETS = [
  { chainId: 1,        label: 'Mainnet', color: '#627EEA' },
  { chainId: 5,        label: 'Goerli',  color: '#F6C343' },
  { chainId: 11155111, label: 'Sepolia', color: '#CFB5F0' },
]

export function Dashboard({ wallet }: Props) {
  const [copied, setCopied] = useState(false)
  const [refreshing, setRefreshing] = useState(false)

  const copy = () => {
    if (!wallet.address) return
    navigator.clipboard.writeText(wallet.address).then(() => {
      setCopied(true); setTimeout(() => setCopied(false), 2000)
    }).catch(() => undefined)
  }

  const refresh = async () => {
    setRefreshing(true)
    await wallet.refreshBalance()
    setRefreshing(false)
  }

  const netColor = wallet.chainId ? (NETWORKS[wallet.chainId]?.color ?? '#6366f1') : '#6366f1'

  return (
    <div className="space-y-4">
      {/* Balance Card */}
      <div className="rounded-3xl p-px" style={{ background: `linear-gradient(135deg, ${netColor}40, rgba(37,99,235,0.2), rgba(0,0,0,0))` }}>
        <div className="rounded-3xl p-6 relative overflow-hidden" style={{ background: 'linear-gradient(135deg, #0d1117 0%, #0a0f1a 100%)' }}>
          {/* Decorative glow */}
          <div className="absolute -top-12 -right-12 w-48 h-48 rounded-full pointer-events-none"
               style={{ background: `radial-gradient(circle, ${netColor}20, transparent 70%)` }} />

          <div className="relative">
            <div className="flex justify-between items-start mb-6">
              <div>
                <p className="text-xs font-semibold mb-2" style={{ color: '#334155', letterSpacing: '0.12em', textTransform: 'uppercase' }}>
                  Connected Wallet
                </p>
                <button onClick={copy} className="flex items-center gap-2 transition-all group">
                  <span className="font-mono text-base text-white group-hover:opacity-70 transition-opacity">
                    {wallet.address ? shortenAddress(wallet.address) : '—'}
                  </span>
                  <span className="text-sm" style={{ color: copied ? '#10b981' : '#334155' }}>
                    {copied ? '✓' : '⎘'}
                  </span>
                </button>
                {wallet.address && wallet.chainId && (
                  <a href={getExplorerAddressUrl(wallet.chainId, wallet.address)} target="_blank" rel="noopener noreferrer"
                     className="text-xs mt-0.5 block transition-colors hover:opacity-80" style={{ color: '#475569' }}>
                    View on Etherscan ↗
                  </a>
                )}
              </div>
              <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium"
                   style={{ background: `${netColor}15`, border: `1px solid ${netColor}30`, color: netColor }}>
                <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: netColor }} />
                {wallet.networkName}
              </div>
            </div>

            <div className="flex items-end justify-between">
              <div>
                <p className="text-xs font-semibold mb-2" style={{ color: '#334155', letterSpacing: '0.12em', textTransform: 'uppercase' }}>
                  Balance
                </p>
                <p className="text-5xl font-bold tracking-tight text-white">
                  {wallet.balance ?? '—'}
                  <span className="text-2xl font-medium ml-2" style={{ color: '#475569' }}>ETH</span>
                </p>
              </div>
              <button onClick={refresh} disabled={refreshing} className="transition-all hover:opacity-60 disabled:opacity-30"
                      style={{ color: '#475569' }}>
                <span className={`text-xl block ${refreshing ? 'animate-spin' : ''}`}>↻</span>
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Network Switcher */}
      <div className="rounded-2xl p-5" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)' }}>
        <p className="text-xs font-semibold mb-3" style={{ color: '#334155', letterSpacing: '0.1em', textTransform: 'uppercase' }}>
          Switch Network
        </p>
        <div className="flex gap-2">
          {NETS.map(n => (
            <button key={n.chainId} onClick={() => wallet.switchNetwork(n.chainId)}
              className="flex-1 py-2.5 px-3 rounded-xl text-sm font-medium transition-all duration-200"
              style={wallet.chainId === n.chainId
                ? { background: `${n.color}15`, border: `1px solid ${n.color}35`, color: n.color }
                : { background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)', color: '#334155' }
              }>
              {n.label}
            </button>
          ))}
        </div>
        {wallet.error && (
          <p className="text-xs mt-2" style={{ color: '#ef4444' }}>⚠ {wallet.error}</p>
        )}
      </div>

      {/* Info Grid */}
      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-2xl p-4" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)' }}>
          <p className="text-xs mb-2" style={{ color: '#334155', letterSpacing: '0.1em', textTransform: 'uppercase' }}>Chain ID</p>
          <p className="font-mono font-bold text-white text-lg">{wallet.chainId ?? '—'}</p>
        </div>
        <div className="rounded-2xl p-4" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)' }}>
          <p className="text-xs mb-2" style={{ color: '#334155', letterSpacing: '0.1em', textTransform: 'uppercase' }}>Wallet</p>
          <p className="font-semibold text-white">{window.ethereum?.isMetaMask ? '🦊 MetaMask' : 'Web3'}</p>
        </div>
      </div>

      <button onClick={wallet.disconnect}
        className="w-full py-3 rounded-2xl text-sm font-medium transition-all duration-200"
        style={{ color: '#334155', border: '1px solid transparent' }}
        onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.color = '#ef4444'; (e.currentTarget as HTMLButtonElement).style.borderColor = 'rgba(239,68,68,0.15)'; (e.currentTarget as HTMLButtonElement).style.background = 'rgba(239,68,68,0.05)' }}
        onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.color = '#334155'; (e.currentTarget as HTMLButtonElement).style.borderColor = 'transparent'; (e.currentTarget as HTMLButtonElement).style.background = 'transparent' }}>
        Disconnect Wallet
      </button>
    </div>
  )
}
