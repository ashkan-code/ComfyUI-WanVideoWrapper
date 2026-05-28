import { useState } from 'react'
import { ethers } from 'ethers'
import { WalletState } from '../hooks/useWallet'
import { ERC20_ABI, USDC_ADDRESS, shortenAddress } from '../lib/ethers'

interface Props { wallet: WalletState }

interface TokenResult { symbol: string; name: string; balance: string }

const PRESETS = [
  { label: 'USDC', address: USDC_ADDRESS,                                  note: 'USD Coin' },
  { label: 'USDT', address: '0xdAC17F958D2ee523a2206206994597C13D831ec7', note: 'Tether USD' },
  { label: 'LINK', address: '0x514910771AF9Ca656af840dff83E8264EcF986CA', note: 'Chainlink' },
]

export function ContractReader({ wallet }: Props) {
  const [contractAddr, setContractAddr] = useState(USDC_ADDRESS)
  const [queryAddr, setQueryAddr]       = useState('')
  const [result, setResult]             = useState<TokenResult | null>(null)
  const [isLoading, setIsLoading]       = useState(false)
  const [error, setError]               = useState<string | null>(null)

  const read = async () => {
    if (!wallet.provider)               { setError('Connect wallet first'); return }
    if (!ethers.isAddress(contractAddr)){ setError('Invalid contract address'); return }
    if (!ethers.isAddress(queryAddr))   { setError('Invalid wallet address'); return }

    setIsLoading(true); setError(null); setResult(null)
    try {
      const c = new ethers.Contract(contractAddr, ERC20_ABI, wallet.provider)
      const [balance, decimals, symbol, name] = await Promise.all([
        c.balanceOf(queryAddr) as Promise<bigint>,
        c.decimals()           as Promise<bigint>,
        c.symbol()             as Promise<string>,
        c.name()               as Promise<string>,
      ])
      setResult({
        symbol, name,
        balance: parseFloat(ethers.formatUnits(balance, Number(decimals)))
          .toLocaleString(undefined, { maximumFractionDigits: 4 }),
      })
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Contract call failed'
      setError(msg.includes('BAD_DATA') ? 'Not a valid ERC-20 on this network' : msg)
    } finally { setIsLoading(false) }
  }

  return (
    <div className="rounded-3xl p-6" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)' }}>

      <div className="flex justify-between items-center mb-5">
        <p className="font-semibold text-white">ERC-20 Reader</p>
        <span className="text-xs px-2.5 py-1 rounded-full font-medium"
              style={{ background: 'rgba(124,58,237,0.1)', color: '#a78bfa', border: '1px solid rgba(124,58,237,0.2)' }}>
          Smart Contract
        </span>
      </div>

      <div className="space-y-4">
        {/* Presets */}
        <div>
          <p className="text-xs font-semibold mb-2" style={{ color: '#334155', letterSpacing: '0.1em', textTransform: 'uppercase' }}>Quick Select</p>
          <div className="flex gap-2">
            {PRESETS.map(p => (
              <button key={p.address} onClick={() => setContractAddr(p.address)} title={p.note}
                className="px-4 py-2 rounded-xl text-sm font-semibold transition-all duration-200"
                style={contractAddr === p.address
                  ? { background: 'linear-gradient(135deg, rgba(124,58,237,0.2), rgba(37,99,235,0.15))', border: '1px solid rgba(139,92,246,0.35)', color: '#a78bfa' }
                  : { background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)', color: '#475569' }}>
                {p.label}
              </button>
            ))}
          </div>
        </div>

        {/* Contract address */}
        <div>
          <label className="block text-xs font-semibold mb-2" style={{ color: '#334155', letterSpacing: '0.1em', textTransform: 'uppercase' }}>
            Contract Address
          </label>
          <input type="text" value={contractAddr} onChange={e => setContractAddr(e.target.value)}
            placeholder="0x… ERC-20 contract" spellCheck={false}
            className="w-full py-3 px-4 rounded-2xl font-mono text-xs text-white outline-none"
            style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)' }} />
        </div>

        {/* Query address */}
        <div>
          <div className="flex justify-between items-center mb-2">
            <label className="text-xs font-semibold" style={{ color: '#334155', letterSpacing: '0.1em', textTransform: 'uppercase' }}>
              Wallet to Query
            </label>
            {wallet.address && (
              <button onClick={() => setQueryAddr(wallet.address!)} className="text-xs transition-colors hover:opacity-80" style={{ color: '#7c3aed' }}>
                Use my address
              </button>
            )}
          </div>
          <input type="text" value={queryAddr} onChange={e => setQueryAddr(e.target.value)}
            placeholder="0x… wallet address" spellCheck={false}
            className="w-full py-3 px-4 rounded-2xl font-mono text-sm text-white outline-none"
            style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)' }} />
        </div>

        {/* Error */}
        {error && (
          <div className="rounded-2xl px-4 py-3 flex gap-2 text-sm" style={{ background: 'rgba(239,68,68,0.06)', border: '1px solid rgba(239,68,68,0.15)', color: '#fca5a5' }}>
            <span>⚠</span><span>{error}</span>
          </div>
        )}

        {/* Result */}
        {result && (
          <div className="rounded-2xl p-5" style={{ background: 'linear-gradient(135deg, rgba(124,58,237,0.06), rgba(37,99,235,0.04))', border: '1px solid rgba(139,92,246,0.15)' }}>
            <div className="flex justify-between items-center mb-2">
              <p className="text-sm" style={{ color: '#94a3b8' }}>{result.name}</p>
              <span className="font-mono text-xs px-2 py-0.5 rounded-full" style={{ background: 'rgba(255,255,255,0.05)', color: '#475569' }}>{result.symbol}</span>
            </div>
            <p className="text-4xl font-bold text-white tracking-tight">
              {result.balance}
              <span className="text-xl font-medium ml-2" style={{ color: '#475569' }}>{result.symbol}</span>
            </p>
            <p className="font-mono text-xs mt-1" style={{ color: '#334155' }}>{shortenAddress(queryAddr)}</p>
          </div>
        )}

        <button onClick={read} disabled={!queryAddr || !contractAddr || isLoading}
          className="w-full py-4 rounded-2xl text-sm font-semibold text-white transition-all disabled:opacity-30"
          style={{ background: 'linear-gradient(135deg, #7c3aed, #2563eb)', boxShadow: '0 8px 24px rgba(124,58,237,0.2)' }}>
          {isLoading
            ? <span className="flex items-center justify-center gap-2"><span className="w-3 h-3 rounded-full border border-white/30 border-t-white animate-spin"/>Reading…</span>
            : '⬡ Read Token Balance'}
        </button>
      </div>
    </div>
  )
}
