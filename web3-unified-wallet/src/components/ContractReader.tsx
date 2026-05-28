import { useState } from 'react'
import { ethers } from 'ethers'
import { WalletState } from '../hooks/useWallet'
import { ERC20_ABI, USDC_ADDRESS, shortenAddress } from '../lib/ethers'

interface Props { wallet: WalletState }
interface TokenResult { symbol: string; name: string; balance: string }

const PRESETS = [
  { label: 'USDC', address: USDC_ADDRESS,                                    note: 'USD Coin (Mainnet)' },
  { label: 'USDT', address: '0xdAC17F958D2ee523a2206206994597C13D831ec7',   note: 'Tether USD (Mainnet)' },
  { label: 'LINK', address: '0x514910771AF9Ca656af840dff83E8264EcF986CA',   note: 'Chainlink Token (Mainnet)' },
]

export function ContractReader({ wallet }: Props) {
  const [contractAddr, setContractAddr] = useState(USDC_ADDRESS)
  const [queryAddr, setQueryAddr]       = useState('')
  const [result, setResult]             = useState<TokenResult | null>(null)
  const [isLoading, setIsLoading]       = useState(false)
  const [error, setError]               = useState<string | null>(null)

  const read = async () => {
    if (!wallet.provider)                { setError('Connect wallet first'); return }
    if (!ethers.isAddress(contractAddr)) { setError('Invalid contract address'); return }
    if (!ethers.isAddress(queryAddr))    { setError('Invalid wallet address'); return }

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
    <div className="neon-card p-6 animate-slideUp">

      <div className="flex justify-between items-center mb-5">
        <div>
          <p className="text-white font-bold">ERC-20 Contract Reader</p>
          <p className="text-xs mt-0.5" style={{ color: '#0d2030' }}>Read any token balance on-chain</p>
        </div>
        <span className="badge-purple text-xs px-2.5 py-1 rounded-full font-bold">⬡ Smart Contract</span>
      </div>

      {/* Guide */}
      <div className="rounded-xl p-3 mb-5 flex gap-2"
           style={{ background: 'rgba(147,51,234,.04)', border: '1px solid rgba(147,51,234,.1)' }}>
        <span>💡</span>
        <p className="text-xs" style={{ color: '#1e3a4a' }}>
          Select a token, enter any wallet address, and click <strong style={{ color: '#a855f7' }}>Read</strong> to fetch the on-chain balance directly from the smart contract.
          Only works on Mainnet for USDC/USDT/LINK.
        </p>
      </div>

      <div className="space-y-4">
        {/* Presets */}
        <div>
          <p className="text-xs font-bold uppercase tracking-widest mb-2" style={{ color: '#1e3a4a', letterSpacing: '.12em' }}>Token Presets</p>
          <div className="flex gap-2">
            {PRESETS.map(p => (
              <div key={p.address} className="tooltip flex-1">
                <button onClick={() => setContractAddr(p.address)}
                  className="w-full py-2.5 rounded-xl text-sm font-bold transition-all duration-200"
                  style={contractAddr === p.address
                    ? { background: 'rgba(147,51,234,.12)', border: '1px solid rgba(147,51,234,.3)', color: '#a855f7', boxShadow: '0 0 16px rgba(147,51,234,.1)' }
                    : { background: 'rgba(255,255,255,.02)', border: '1px solid rgba(255,255,255,.05)', color: '#1e3a4a' }}>
                  {p.label}
                </button>
                <span className="tip">{p.note}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Contract addr */}
        <div>
          <label className="block text-xs font-bold uppercase tracking-widest mb-1.5" style={{ color: '#1e3a4a', letterSpacing: '.12em' }}>
            Contract Address
          </label>
          <input type="text" value={contractAddr} onChange={e => setContractAddr(e.target.value)}
            placeholder="0x… ERC-20 contract" spellCheck={false}
            className="cyber-input py-3 px-4 font-mono text-xs" />
        </div>

        {/* Query addr */}
        <div>
          <div className="flex justify-between items-center mb-1.5">
            <label className="text-xs font-bold uppercase tracking-widest" style={{ color: '#1e3a4a', letterSpacing: '.12em' }}>
              Wallet to Query
            </label>
            {wallet.address && (
              <button onClick={() => setQueryAddr(wallet.address!)}
                      className="text-xs font-semibold transition-all hover:opacity-80" style={{ color: '#7c3aed' }}>
                ⎘ Use my address
              </button>
            )}
          </div>
          <input type="text" value={queryAddr} onChange={e => setQueryAddr(e.target.value)}
            placeholder="0x… any Ethereum wallet address" spellCheck={false}
            className="cyber-input py-3.5 px-4 font-mono text-sm" />
        </div>

        {/* Error */}
        {error && (
          <div className="rounded-xl px-4 py-3 flex gap-2 text-sm badge-red animate-slideUp">
            <span>⚠</span><span>{error}</span>
          </div>
        )}

        {/* Result */}
        {result && (
          <div className="rounded-2xl p-5 animate-slideUp scan-container"
               style={{ background: 'linear-gradient(135deg, rgba(147,51,234,.06), rgba(14,165,233,.04))', border: '1px solid rgba(147,51,234,.2)' }}>
            <div className="scan-line opacity-30" />
            <div className="flex justify-between items-start mb-3">
              <div>
                <p className="text-xs" style={{ color: '#475569' }}>{result.name}</p>
                <p className="font-mono text-xs mt-0.5" style={{ color: '#0d2030' }}>{shortenAddress(queryAddr)}</p>
              </div>
              <span className="badge-purple text-xs px-2 py-0.5 rounded-full font-mono font-bold">{result.symbol}</span>
            </div>
            <div className="animate-ticker">
              <span className="text-4xl font-black text-white tracking-tight">{result.balance}</span>
              <span className="text-xl font-semibold ml-2" style={{ color: '#475569' }}>{result.symbol}</span>
            </div>
          </div>
        )}

        <button onClick={read} disabled={!queryAddr || !contractAddr || isLoading}
          className="btn-primary w-full py-4 text-sm">
          {isLoading
            ? <span className="flex items-center justify-center gap-2">
                <span className="w-3 h-3 rounded-full border-2 border-white/30 border-t-white animate-spin"/>
                Reading contract…
              </span>
            : '⬡ Read Token Balance'}
        </button>
      </div>
    </div>
  )
}
