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
  const [isSending, setIsSending]       = useState(false)
  const [error, setError]   = useState<string | null>(null)
  const [sentHash, setSentHash] = useState<string | null>(null)

  const isValidAddress = to.length > 0 && ethers.isAddress(to)
  const isValidAmount  = amount.length > 0 && parseFloat(amount) > 0
  const canSend        = isValidAddress && isValidAmount && !isSending && !isEstimating

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
      setError(err instanceof Error ? err.message : 'Gas estimation failed')
    } finally { setIsEstimating(false) }
  }

  const send = async () => {
    if (!wallet.provider || !isValidAddress || !isValidAmount) return
    setIsSending(true); setError(null); setSentHash(null)
    let hash: string | null = null
    try {
      const signer  = await wallet.provider.getSigner()
      const tx      = await signer.sendTransaction({ to, value: ethers.parseEther(amount) })
      hash = tx.hash; setSentHash(hash)
      onTransactionSent({ hash, to, value: amount, chainId: wallet.chainId ?? 1 })
      const receipt = await tx.wait()
      const status  = receipt === null ? 'failed' : receipt.status === 1 ? 'confirmed' : 'failed'
      onTransactionConfirmed(hash, status)
      if (status === 'confirmed') { setTo(''); setAmount(''); setGasEth(null) }
      else setError('Transaction reverted on-chain')
    } catch (err) {
      const msg = err instanceof Error ? (err.message.includes('rejected') ? 'Rejected by user' : err.message) : 'Failed'
      setError(msg)
      if (hash) onTransactionConfirmed(hash, 'failed')
    } finally { setIsSending(false) }
  }

  return (
    <div className="neon-card p-6 animate-slideUp">

      {/* Guide */}
      <div className="rounded-xl p-3 mb-5 flex items-start gap-2"
           style={{ background: 'rgba(0,212,255,.04)', border: '1px solid rgba(0,212,255,.08)' }}>
        <span>💡</span>
        <p className="text-xs" style={{ color: '#1e3a4a' }}>
          Enter an address and amount, then click <strong style={{ color: '#00d4ff' }}>Estimate Gas</strong> to preview the fee before sending.
          Use Sepolia testnet to send without real ETH.
        </p>
      </div>

      <div className="space-y-4">
        {/* To */}
        <div>
          <label className="flex items-center justify-between mb-1.5">
            <span className="text-xs font-bold uppercase tracking-widest" style={{ color: '#1e3a4a', letterSpacing: '.12em' }}>Recipient Address</span>
            {to.length > 0 && (
              <span className="text-xs font-semibold px-2 py-0.5 rounded-full"
                    style={isValidAddress ? { background: 'rgba(0,255,136,.08)', color: '#00ff88', border: '1px solid rgba(0,255,136,.2)' } : { background: 'rgba(255,51,102,.08)', color: '#ff3366', border: '1px solid rgba(255,51,102,.2)' }}>
                {isValidAddress ? '✓ Valid address' : '✗ Invalid address'}
              </span>
            )}
          </label>
          <div className="relative">
            <input type="text" value={to} onChange={e => { setTo(e.target.value); setGasEth(null) }}
              placeholder="0x… paste wallet address" spellCheck={false}
              className="cyber-input py-3.5 px-4 pr-4 font-mono text-sm"
              style={{ borderColor: to.length > 0 ? (isValidAddress ? 'rgba(0,255,136,.25)' : 'rgba(255,51,102,.25)') : undefined }} />
          </div>
        </div>

        {/* Amount */}
        <div>
          <label className="flex items-center justify-between mb-1.5">
            <span className="text-xs font-bold uppercase tracking-widest" style={{ color: '#1e3a4a', letterSpacing: '.12em' }}>Amount (ETH)</span>
            {wallet.balance && (
              <button onClick={() => setAmount(wallet.balance!)}
                      className="text-xs font-semibold transition-all hover:opacity-80" style={{ color: '#7c3aed' }}>
                Max: {wallet.balance} ETH
              </button>
            )}
          </label>
          <div className="relative">
            <input type="number" value={amount} onChange={e => { setAmount(e.target.value); setGasEth(null) }}
              placeholder="0.0" min="0" step="0.001"
              className="cyber-input py-3.5 px-4 pr-16 text-sm" />
            <span className="absolute right-4 top-1/2 -translate-y-1/2 font-bold text-sm" style={{ color: '#1e3a4a' }}>ETH</span>
          </div>
        </div>

        {/* Gas */}
        {gasEth && (
          <div className="rounded-xl px-4 py-3 flex justify-between items-center animate-slideUp"
               style={{ background: 'rgba(0,212,255,.05)', border: '1px solid rgba(0,212,255,.12)' }}>
            <span className="text-sm flex items-center gap-2 text-neon-cyan">⛽ Estimated gas fee</span>
            <span className="font-mono text-sm font-bold text-neon-cyan">~{parseFloat(gasEth).toFixed(6)} ETH</span>
          </div>
        )}

        {/* TX hash */}
        {sentHash && (
          <div className="rounded-xl px-4 py-3 animate-slideUp"
               style={{ background: 'rgba(0,255,136,.05)', border: '1px solid rgba(0,255,136,.15)' }}>
            <p className="text-xs font-bold text-neon-green mb-1">✓ Transaction submitted</p>
            <a href={getExplorerTxUrl(wallet.chainId ?? 1, sentHash)} target="_blank" rel="noopener noreferrer"
               className="font-mono text-xs transition-all hover:opacity-80 text-neon-green">
              {shortenAddress(sentHash)} — View on Etherscan ↗
            </a>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="rounded-xl px-4 py-3 flex gap-2 text-sm animate-slideUp badge-red">
            <span>⚠</span><span>{error}</span>
          </div>
        )}

        {/* Buttons */}
        <div className="flex gap-3 pt-1">
          <button onClick={estimateGas} disabled={!isValidAddress || !isValidAmount || isEstimating || isSending}
            className="btn-cyber flex-1 py-4 text-sm">
            {isEstimating
              ? <span className="flex items-center justify-center gap-2"><span className="w-3 h-3 rounded-full border border-cyan-400/30 border-t-cyan-400 animate-spin"/>Estimating…</span>
              : '⛽ Estimate Gas'}
          </button>
          <button onClick={send} disabled={!canSend}
            className="btn-primary flex-1 py-4 text-sm">
            {isSending
              ? <span className="flex items-center justify-center gap-2"><span className="w-3 h-3 rounded-full border-2 border-white/30 border-t-white animate-spin"/>Sending…</span>
              : '↗ Send ETH'}
          </button>
        </div>
      </div>
    </div>
  )
}
