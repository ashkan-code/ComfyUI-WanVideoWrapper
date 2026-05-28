import { useState } from 'react'
import { ethers } from 'ethers'
import { WalletState } from '../hooks/useWallet'
import { ERC20_ABI, USDC_ADDRESS, shortenAddress } from '../lib/ethers'

interface Props {
  wallet: WalletState
}

interface TokenResult {
  symbol: string
  name: string
  balance: string
  address: string
}

// Well-known ERC-20 contracts for quick selection
const PRESETS = [
  { label: 'USDC',  address: '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48', note: 'USD Coin (Mainnet)' },
  { label: 'USDT',  address: '0xdAC17F958D2ee523a2206206994597C13D831ec7', note: 'Tether USD (Mainnet)' },
  { label: 'LINK',  address: '0x514910771AF9Ca656af840dff83E8264EcF986CA', note: 'Chainlink (Mainnet)' },
]

export function ContractReader({ wallet }: Props) {
  const [contractAddr, setContractAddr] = useState(USDC_ADDRESS)
  const [queryAddr, setQueryAddr]       = useState('')
  const [result, setResult]             = useState<TokenResult | null>(null)
  const [isLoading, setIsLoading]       = useState(false)
  const [error, setError]               = useState<string | null>(null)

  const readBalance = async () => {
    if (!wallet.provider) { setError('Connect your wallet first'); return }
    if (!ethers.isAddress(contractAddr)) { setError('Invalid contract address'); return }
    if (!ethers.isAddress(queryAddr))    { setError('Invalid address to query'); return }

    setIsLoading(true)
    setError(null)
    setResult(null)

    try {
      const contract = new ethers.Contract(contractAddr, ERC20_ABI, wallet.provider)

      const [balance, decimals, symbol, name] = await Promise.all([
        contract.balanceOf(queryAddr) as Promise<bigint>,
        contract.decimals()           as Promise<number>,
        contract.symbol()             as Promise<string>,
        contract.name()               as Promise<string>,
      ])

      setResult({
        symbol,
        name,
        balance: parseFloat(ethers.formatUnits(balance, decimals))
          .toLocaleString(undefined, { maximumFractionDigits: 4 }),
        address: queryAddr,
      })
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Contract call failed'
      setError(msg.includes('BAD_DATA') ? 'Not a valid ERC-20 contract on this network' : msg)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="bg-slate-800/60 rounded-xl p-6 border border-slate-700/50">
      <div className="flex justify-between items-center mb-5">
        <h2 className="text-white font-semibold text-lg">ERC-20 Contract Reader</h2>
        <span className="text-xs bg-indigo-500/15 text-indigo-400 border border-indigo-500/20 px-2.5 py-1 rounded-full font-medium">
          Smart Contract Demo
        </span>
      </div>

      <div className="space-y-4">
        {/* Preset Contracts */}
        <div>
          <p className="text-slate-400 text-xs font-medium uppercase tracking-wider mb-2">Quick Select</p>
          <div className="flex gap-2 flex-wrap">
            {PRESETS.map(p => (
              <button
                key={p.address}
                onClick={() => setContractAddr(p.address)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all border ${
                  contractAddr === p.address
                    ? 'bg-indigo-600 text-white border-indigo-500'
                    : 'bg-slate-700/40 text-slate-400 border-slate-600/40 hover:text-white hover:bg-slate-700'
                }`}
                title={p.note}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        {/* Contract Address */}
        <div>
          <label className="block text-slate-400 text-xs font-medium uppercase tracking-wider mb-1.5">
            Contract Address
          </label>
          <input
            type="text"
            value={contractAddr}
            onChange={e => setContractAddr(e.target.value)}
            placeholder="0x… ERC-20 contract"
            spellCheck={false}
            className="w-full bg-slate-700/50 text-white rounded-xl px-4 py-3 text-xs font-mono border border-slate-600/50 focus:border-indigo-500 focus:outline-none transition-colors placeholder:text-slate-600"
          />
        </div>

        {/* Query Address */}
        <div>
          <div className="flex justify-between items-center mb-1.5">
            <label className="text-slate-400 text-xs font-medium uppercase tracking-wider">
              Wallet to Query
            </label>
            {wallet.address && (
              <button
                onClick={() => setQueryAddr(wallet.address!)}
                className="text-indigo-400 hover:text-indigo-300 text-xs transition-colors"
              >
                Use my address
              </button>
            )}
          </div>
          <input
            type="text"
            value={queryAddr}
            onChange={e => setQueryAddr(e.target.value)}
            placeholder="0x… wallet address"
            spellCheck={false}
            className="w-full bg-slate-700/50 text-white rounded-xl px-4 py-3 text-sm font-mono border border-slate-600/50 focus:border-indigo-500 focus:outline-none transition-colors placeholder:text-slate-600"
          />
        </div>

        {/* Error */}
        {error && (
          <div className="bg-red-500/10 border border-red-500/30 text-red-300 rounded-xl p-3 text-sm flex items-start gap-2">
            <span className="shrink-0 mt-0.5">⚠</span>
            <span>{error}</span>
          </div>
        )}

        {/* Result */}
        {result && (
          <div className="bg-gradient-to-br from-slate-700/40 to-slate-700/20 rounded-xl p-5 border border-slate-600/30">
            <div className="flex justify-between items-start mb-3">
              <div>
                <p className="text-slate-400 text-xs">{result.name}</p>
                <p className="text-slate-500 text-xs font-mono mt-0.5">{shortenAddress(result.address)}</p>
              </div>
              <span className="text-xs bg-slate-600/50 text-slate-300 px-2.5 py-1 rounded-full font-mono">
                {result.symbol}
              </span>
            </div>
            <p className="text-4xl font-bold text-white tracking-tight">
              {result.balance}
              <span className="text-xl text-slate-400 ml-2 font-medium">{result.symbol}</span>
            </p>
          </div>
        )}

        <button
          onClick={readBalance}
          disabled={!queryAddr || !contractAddr || isLoading}
          className="w-full bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white py-3 rounded-xl text-sm font-semibold transition-all duration-200 shadow-lg shadow-indigo-500/10"
        >
          {isLoading ? (
            <span className="flex items-center justify-center gap-2">
              <span className="w-3 h-3 border border-white/40 border-t-white rounded-full animate-spin" />
              Reading contract…
            </span>
          ) : '⬡ Read Token Balance'}
        </button>
      </div>
    </div>
  )
}
