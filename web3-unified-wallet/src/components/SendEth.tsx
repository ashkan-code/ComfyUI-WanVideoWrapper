import { useState } from 'react'
import { ethers } from 'ethers'
import { WalletState } from '../hooks/useWallet'
import { Transaction } from '../hooks/useTransactions'
import { getExplorerTxUrl, shortenAddress } from '../lib/ethers'

interface Props {
  wallet: WalletState
  onTransactionSent: (tx: Omit<Transaction, 'timestamp' | 'status'>) => void
  onTransactionConfirmed: (hash: string, status: 'confirmed' | 'failed') => void
}

export function SendEth({ wallet, onTransactionSent, onTransactionConfirmed }: Props) {
  const [to, setTo]         = useState('')
  const [amount, setAmount] = useState('')
  const [gasEth, setGasEth] = useState<string | null>(null)
  const [isEstimating, setIsEstimating] = useState(false)
  const [isSending, setIsSending] = useState(false)
  const [error, setError]   = useState<string | null>(null)
  const [sentHash, setSentHash] = useState<string | null>(null)

  const isValidAddress = to.length > 0 && ethers.isAddress(to)
  const isValidAmount  = amount.length > 0 && parseFloat(amount) > 0

  const estimateGas = async () => {
    if (!wallet.provider || !isValidAddress || !isValidAmount) return
    setIsEstimating(true); setError(null); setGasEth(null)
    try {
      const signer   = await wallet.provider.getSigner()
      const value    = ethers.parseEther(amount)
      const feeData  = await wallet.provider.getFeeData()
      const gasLimit = await wallet.provider.estimateGas({ from: signer.address, to, value })
      const gasPrice = feeData.maxFeePerGas ?? feeData.gasPrice ?? 0n
      setGasEth(ethers.formatEther(gasLimit * gasPrice))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Estimation failed')
    } finally { setIsEstimating(false) }
  }

  const send = async () => {
    if (!wallet.provider || !isValidAddress || !isValidAmount) return
    setIsSending(true); setError(null); setSentHash(null)
    let pendingHash: string | null = null
    try {
      const signer  = await wallet.provider.getSigner()
      const tx      = await signer.sendTransaction({ to, value: ethers.parseEther(amount) })
      pendingHash   = tx.hash
      setSentHash(tx.hash)
      onTransactionSent({ hash: tx.hash, to, value: amount, chainId: wallet.chainId ?? 1 })
      const receipt = await tx.wait()
      const status  = receipt === null ? 'failed' : receipt.status === 1 ? 'confirmed' : 'failed'
      onTransactionConfirmed(tx.hash, status)
      if (status === 'confirmed') { setTo(''); setAmount(''); setGasEth(null) }
      else setError('Transaction reverted on-chain')
    } catch (err) {
      const msg = err instanceof Error ? (err.message.includes('rejected') ? 'Rejected by user' : err.message) : 'Transaction failed'
      setError(msg)
      if (pendingHash) onTransactionConfirmed(pendingHash, 'failed')
    } finally { setIsSending(false) }
  }

  return (
    <div className="rounded-3xl p-6" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)' }}>

      <div className="space-y-4">
        {/* To */}
        <div>
          <label className="block text-xs font-semibold mb-2" style={{ color: '#334155', letterSpacing: '0.1em', textTransform: 'uppercase' }}>
            Recipient Address
          </label>
          <div className="relative">
            <input type="text" value={to} onChange={e => { setTo(e.target.value); setGasEth(null) }}
              placeholder="0x…" spellCheck={false}
              className="w-full py-3.5 px-4 pr-20 rounded-2xl font-mono text-sm text-white transition-all outline-none"
              style={{ background: 'rgba(255,255,255,0.03)', border: `1px solid ${to.length > 0 ? (isValidAddress ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)') : 'rgba(255,255,255,0.06)'}`, color: '#e2e8f0' }} />
            {to.length > 0 && (
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs font-semibold px-2 py-0.5 rounded-full"
                    style={isValidAddress ? { background: 'rgba(16,185,129,0.1)', color: '#10b981' } : { background: 'rgba(239,68,68,0.1)', color: '#ef4444' }}>
                {isValidAddress ? '✓' : '✗'}
              </span>
            )}
          </div>
        </div>

        {/* Amount */}
        <div>
          <label className="block text-xs font-semibold mb-2" style={{ color: '#334155', letterSpacing: '0.1em', textTransform: 'uppercase' }}>
            Amount
          </label>
          <div className="relative">
            <input type="number" value={amount} onChange={e => { setAmount(e.target.value); setGasEth(null) }}
              placeholder="0.0" min="0" step="0.001"
              className="w-full py-3.5 px-4 pr-16 rounded-2xl text-sm text-white outline-none transition-all"
              style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)' }} />
            <span className="absolute right-4 top-1/2 -translate-y-1/2 text-sm font-semibold" style={{ color: '#475569' }}>ETH</span>
          </div>
          {wallet.balance && (
            <button onClick={() => setAmount(wallet.balance!)} className="mt-1 text-xs transition-colors hover:opacity-80" style={{ color: '#7c3aed' }}>
              Max: {wallet.balance} ETH
            </button>
          )}
        </div>

        {/* Gas estimate */}
        {gasEth && (
          <div className="rounded-2xl px-4 py-3 flex justify-between items-center"
               style={{ background: 'rgba(124,58,237,0.06)', border: '1px solid rgba(124,58,237,0.15)' }}>
            <span className="text-sm flex items-center gap-2" style={{ color: '#7c3aed' }}>⛽ Estimated gas</span>
            <span className="font-mono text-sm font-semibold" style={{ color: '#a78bfa' }}>~{parseFloat(gasEth).toFixed(6)} ETH</span>
          </div>
        )}

        {/* Sent hash */}
        {sentHash && (
          <div className="rounded-2xl px-4 py-3" style={{ background: 'rgba(16,185,129,0.06)', border: '1px solid rgba(16,185,129,0.15)' }}>
            <p className="text-xs font-semibold mb-1" style={{ color: '#10b981' }}>Transaction submitted</p>
            <a href={getExplorerTxUrl(wallet.chainId ?? 1, sentHash)} target="_blank" rel="noopener noreferrer"
               className="font-mono text-xs transition-colors hover:opacity-80" style={{ color: '#34d399' }}>
              {shortenAddress(sentHash)} ↗
            </a>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="rounded-2xl px-4 py-3 flex gap-2 text-sm" style={{ background: 'rgba(239,68,68,0.06)', border: '1px solid rgba(239,68,68,0.15)', color: '#fca5a5' }}>
            <span>⚠</span><span>{error}</span>
          </div>
        )}

        {/* Buttons */}
        <div className="flex gap-3 pt-1">
          <button onClick={estimateGas} disabled={!isValidAddress || !isValidAmount || isEstimating || isSending}
            className="flex-1 py-3.5 rounded-2xl text-sm font-semibold transition-all disabled:opacity-30"
            style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', color: '#94a3b8' }}>
            {isEstimating ? <span className="flex items-center justify-center gap-2"><span className="w-3 h-3 rounded-full border border-white/30 border-t-white/70 animate-spin"/>Estimating…</span> : '⛽ Estimate Gas'}
          </button>

          <button onClick={send} disabled={!isValidAddress || !isValidAmount || isSending || isEstimating}
            className="flex-1 py-3.5 rounded-2xl text-sm font-semibold transition-all disabled:opacity-30 text-white"
            style={{ background: 'linear-gradient(135deg, #7c3aed, #2563eb)', boxShadow: '0 8px 24px rgba(124,58,237,0.25)' }}>
            {isSending ? <span className="flex items-center justify-center gap-2"><span className="w-3 h-3 rounded-full border border-white/30 border-t-white animate-spin"/>Sending…</span> : '↗ Send ETH'}
          </button>
        </div>
      </div>
    </div>
  )
}
