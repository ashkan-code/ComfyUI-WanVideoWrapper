import { useState, useEffect } from 'react'
import { WalletState, WalletActions } from '../hooks/useWallet'
import { shortenAddress, NETWORKS, getExplorerAddressUrl } from '../lib/ethers'

interface Props { wallet: WalletState & WalletActions }

const NETS = [
  { chainId: 1,        label: 'Mainnet', color: '#627EEA' },
  { chainId: 5,        label: 'Goerli',  color: '#F6C343' },
  { chainId: 11155111, label: 'Sepolia', color: '#a78bfa' },
]

function Tip({ text }: { text: string }) {
  return (
    <div className="tooltip">
      <span className="w-4 h-4 rounded-full flex items-center justify-center text-xs cursor-help"
            style={{ background: 'rgba(0,212,255,.08)', border: '1px solid rgba(0,212,255,.15)', color: '#00d4ff', fontSize: '10px' }}>?</span>
      <span className="tip">{text}</span>
    </div>
  )
}

export function Dashboard({ wallet }: Props) {
  const [copied, setCopied] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [balanceKey, setBalanceKey] = useState(0)

  useEffect(() => { setBalanceKey(k => k + 1) }, [wallet.balance])

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

  const netColor = wallet.chainId ? (NETWORKS[wallet.chainId]?.color ?? '#00d4ff') : '#00d4ff'

  return (
    <div className="space-y-4 animate-slideUp">

      {/* ── Balance Card ─────────────────────── */}
      <div className="holo-card p-6 relative">
        {/* Corner decoration */}
        <div className="absolute top-4 right-4 w-16 h-16 opacity-10 pointer-events-none"
             style={{ background: `radial-gradient(circle, ${netColor}, transparent 70%)` }} />

        {/* Header row */}
        <div className="flex justify-between items-start mb-5">
          <div>
            <p className="text-xs font-bold uppercase tracking-widest mb-1.5 flex items-center gap-2"
               style={{ color: '#1e3a4a', letterSpacing: '.12em' }}>
              Connected Wallet
              <Tip text="Your Ethereum wallet address" />
            </p>
            <button onClick={copy} className="flex items-center gap-2 group" title="Copy full address">
              <span className="font-mono font-semibold text-base" style={{ color: '#94a3b8' }}>
                {wallet.address ? shortenAddress(wallet.address) : '—'}
              </span>
              <span className="text-sm transition-all" style={{ color: copied ? '#00ff88' : '#1e3a4a' }}>
                {copied ? '✓ Copied' : '⎘'}
              </span>
            </button>
            {wallet.address && wallet.chainId && (
              <a href={getExplorerAddressUrl(wallet.chainId, wallet.address)} target="_blank" rel="noopener noreferrer"
                 className="text-xs mt-0.5 flex items-center gap-1 transition-all hover:opacity-80"
                 style={{ color: '#0d2030' }}>
                <span>🔍</span> View on Etherscan
              </a>
            )}
          </div>

          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full"
               style={{ background: `${netColor}12`, border: `1px solid ${netColor}30` }}>
            <span className="w-2 h-2 rounded-full animate-pulse" style={{ background: netColor }} />
            <span className="text-xs font-bold" style={{ color: netColor }}>{wallet.networkName}</span>
          </div>
        </div>

        {/* Balance */}
        <div className="flex items-end justify-between">
          <div>
            <p className="text-xs font-bold uppercase tracking-widest mb-2 flex items-center gap-2"
               style={{ color: '#1e3a4a', letterSpacing: '.12em' }}>
              ETH Balance <Tip text="Native Ether balance on selected network" />
            </p>
            <div key={balanceKey} className="animate-ticker flex items-baseline gap-2">
              <span className="text-5xl font-black text-white tracking-tight" style={{ fontVariantNumeric: 'tabular-nums' }}>
                {wallet.balance ?? '0.0000'}
              </span>
              <span className="text-xl font-semibold" style={{ color: '#1e3a4a' }}>ETH</span>
            </div>
          </div>
          <button onClick={refresh} disabled={refreshing} title="Refresh balance"
            className="w-9 h-9 rounded-xl flex items-center justify-center transition-all hover:bg-white/5 disabled:opacity-30"
            style={{ border: '1px solid rgba(0,212,255,.1)', color: '#00d4ff' }}>
            <span className={`text-lg ${refreshing ? 'animate-spin' : ''}`}>↻</span>
          </button>
        </div>

        {/* Chain detail strip */}
        <div className="mt-5 pt-4 flex items-center gap-4" style={{ borderTop: '1px solid rgba(0,212,255,.06)' }}>
          <div>
            <p className="text-xs" style={{ color: '#0d2030' }}>Chain ID</p>
            <p className="font-mono font-bold text-white">{wallet.chainId ?? '—'}</p>
          </div>
          <div style={{ width: 1, height: 28, background: 'rgba(0,212,255,.06)' }} />
          <div>
            <p className="text-xs" style={{ color: '#0d2030' }}>Wallet</p>
            <p className="font-semibold text-white text-sm">{window.ethereum?.isMetaMask ? '🦊 MetaMask' : 'Web3'}</p>
          </div>
          <div style={{ width: 1, height: 28, background: 'rgba(0,212,255,.06)' }} />
          <div>
            <p className="text-xs" style={{ color: '#0d2030' }}>Status</p>
            <p className="text-neon-green font-bold text-sm">● Live</p>
          </div>
        </div>
      </div>

      {/* ── Network Switcher ──────────────────── */}
      <div className="neon-card p-5">
        <p className="text-xs font-bold uppercase tracking-widest mb-3 flex items-center gap-2"
           style={{ color: '#1e3a4a', letterSpacing: '.12em' }}>
          Switch Network <Tip text="Switch between Ethereum networks. Sepolia is free for testing." />
        </p>
        <div className="flex gap-2">
          {NETS.map(n => (
            <button key={n.chainId} onClick={() => wallet.switchNetwork(n.chainId)}
              className="flex-1 py-3 rounded-2xl text-sm font-bold transition-all duration-200 relative overflow-hidden"
              style={wallet.chainId === n.chainId
                ? { background: `${n.color}12`, border: `1px solid ${n.color}35`, color: n.color, boxShadow: `0 0 20px ${n.color}15` }
                : { background: 'rgba(255,255,255,.02)', border: '1px solid rgba(255,255,255,.05)', color: '#1e3a4a' }
              }>
              {wallet.chainId === n.chainId && (
                <span className="absolute top-1.5 right-1.5 w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: n.color }} />
              )}
              {n.label}
            </button>
          ))}
        </div>
        {wallet.error && (
          <p className="text-xs mt-3 flex items-center gap-1" style={{ color: 'var(--red)' }}>
            ⚠ {wallet.error}
          </p>
        )}
      </div>

      {/* ── Guide strip ───────────────────────── */}
      <div className="rounded-2xl p-4 flex items-start gap-3"
           style={{ background: 'rgba(0,212,255,.03)', border: '1px solid rgba(0,212,255,.06)' }}>
        <span className="text-xl shrink-0">💡</span>
        <div>
          <p className="text-xs font-bold text-white mb-0.5">Quick guide</p>
          <p className="text-xs" style={{ color: '#1e3a4a' }}>
            Use <span className="text-neon-cyan font-mono">↗ Send</span> to transfer ETH ·
            Check <span className="text-neon-cyan font-mono">⬡ Contracts</span> to read any ERC-20 balance ·
            Use Sepolia for free test transactions
          </p>
        </div>
      </div>

      <button onClick={wallet.disconnect}
        className="w-full py-3 rounded-2xl text-sm font-semibold transition-all duration-200"
        style={{ color: '#1e3a4a', border: '1px solid transparent' }}
        onMouseEnter={e => { const b = e.currentTarget; b.style.color='var(--red)'; b.style.borderColor='rgba(255,51,102,.15)'; b.style.background='rgba(255,51,102,.04)' }}
        onMouseLeave={e => { const b = e.currentTarget; b.style.color='#1e3a4a'; b.style.borderColor='transparent'; b.style.background='transparent' }}>
        Disconnect Wallet
      </button>
    </div>
  )
}
